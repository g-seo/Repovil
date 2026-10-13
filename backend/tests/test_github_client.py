from __future__ import annotations

import ast
import json
import logging
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import NoReturn
from urllib.parse import parse_qs, urlsplit

import pytest

from repovil.github_client import (
    GITHUB_API_VERSION,
    GitHubAuthenticationError,
    GitHubClient,
    GitHubClientError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubResponseFormatError,
    GitHubServerError,
    GitHubTransportError,
    GitHubValidationError,
    TransportResponse,
)


class SequenceTransport:
    def __init__(self, *outcomes: TransportResponse | Exception) -> None:
        self.outcomes = list(outcomes)
        self.requests: list[tuple[str, str, Mapping[str, str], float]] = []

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        self.requests.append((method, url, dict(headers), timeout))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def json_response(
    status_code: int,
    body: object,
    headers: Mapping[str, str] | None = None,
) -> TransportResponse:
    return TransportResponse(
        status_code=status_code,
        headers=headers or {},
        body=json.dumps(body).encode(),
    )


def repository_payload(*, github_id: int = 160_919_119) -> dict[str, object]:
    return {
        "id": github_id,
        "owner": {"login": "fastapi"},
        "name": "fastapi",
        "full_name": "fastapi/fastapi",
        "html_url": "https://github.com/fastapi/fastapi",
        "description": "FastAPI framework",
        "language": "Python",
        "stargazers_count": 100_000,
        "topics": ["api", "python"],
        "visibility": "public",
        "private": False,
        "fork": False,
        "archived": False,
    }


def fail(message: str) -> NoReturn:
    raise AssertionError(message)


def test_search_parses_repository_and_supplies_verified_headers() -> None:
    transport = SequenceTransport(
        json_response(
            200,
            {
                "total_count": 1,
                "incomplete_results": False,
                "items": [repository_payload()],
            },
            {
                "X-RateLimit-Limit": "30",
                "X-RateLimit-Remaining": "29",
                "X-RateLimit-Reset": "2000",
                "X-RateLimit-Resource": "search",
            },
        )
    )
    client = GitHubClient(token="secret-token", transport=transport, timeout=4.5)

    result = client.search_repositories(
        "ai-agent",
        min_stars=200,
        max_stars=499,
        page=2,
    )

    assert result.total_count == 1
    assert result.incomplete_results is False
    assert result.repositories[0].github_id == 160_919_119
    assert result.repositories[0].topics == ("api", "python")
    assert result.request.status_code == 200
    assert result.request.rate_limit.remaining == 29
    assert result.request.rate_limit.resource == "search"

    method, url, headers, timeout = transport.requests[0]
    query = parse_qs(urlsplit(url).query)
    assert method == "GET"
    assert query == {
        "q": [
            "topic:ai-agent stars:200..499 fork:false archived:false is:public"
        ],
        "sort": ["stars"],
        "order": ["desc"],
        "per_page": ["100"],
        "page": ["2"],
    }
    assert headers == {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": GITHUB_API_VERSION,
        "User-Agent": "repovil/0.1",
        "Authorization": "Bearer secret-token",
    }
    assert timeout == 4.5


def test_repository_stats_and_history_parse_endpoint_specific_responses() -> None:
    transport = SequenceTransport(
        json_response(200, repository_payload()),
        json_response(200, {"count": 100_001}),
        json_response(
            200,
            [{"week": 1_799_539_200, "total": 7, "days": [1, 0, 2, 0, 1, 1, 2]}],
        ),
    )
    client = GitHubClient(transport=transport)

    repository = client.get_repository("old owner", "old/name")
    stats = client.get_repository_stats("fastapi", "fastapi")
    history = client.get_star_history("fastapi", "fastapi", page=3, per_page=12)

    assert repository.repository.full_name == "fastapi/fastapi"
    assert stats.star_count == 100_001
    assert history.weeks[0].days == (1, 0, 2, 0, 1, 1, 2)
    assert history.page == 3
    assert history.per_page == 12
    assert urlsplit(transport.requests[0][1]).path == "/repos/old%20owner/old%2Fname"
    assert parse_qs(urlsplit(transport.requests[2][1]).query) == {
        "per_page": ["12"],
        "page": ["3"],
    }


@pytest.mark.parametrize(
    ("call", "message"),
    [
        (lambda client: client.search_repositories("", page=1), "topic"),
        (lambda client: client.search_repositories("ai", min_stars=3, max_stars=2), "star"),
        (lambda client: client.search_repositories("ai", page=11), "1,000"),
        (lambda client: client.search_repositories("ai", per_page=101), "per_page"),
        (lambda client: client.get_star_history("owner", "repo", page=101), "100"),
        (lambda client: client.get_star_history("owner", "repo", per_page=31), "per_page"),
    ],
)
def test_endpoint_pagination_and_parameters_are_validated(
    call: Callable[[GitHubClient], object],
    message: str,
) -> None:
    transport = SequenceTransport()
    client = GitHubClient(transport=transport)

    with pytest.raises(ValueError, match=message):
        call(client)
    assert transport.requests == []


def test_timeout_and_server_errors_use_bounded_exponential_backoff() -> None:
    transport = SequenceTransport(
        TimeoutError("slow"),
        json_response(503, {"message": "Unavailable"}),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(
        transport=transport,
        max_retries=3,
        backoff_base=2,
        max_backoff=3,
        sleep=sleeps.append,
    )

    result = client.get_repository_stats("owner", "repo")

    assert result.star_count == 10
    assert result.request.retry_count == 2
    assert sleeps == [2, 3]
    assert len(transport.requests) == 3


def test_non_json_server_error_is_still_retried() -> None:
    transport = SequenceTransport(
        TransportResponse(502, {}, b"upstream unavailable"),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, sleep=sleeps.append)

    result = client.get_repository_stats("owner", "repo")

    assert result.star_count == 10
    assert sleeps == [1]


def test_retry_after_takes_priority_over_rate_limit_reset() -> None:
    transport = SequenceTransport(
        json_response(
            429,
            {"message": "rate limit exceeded"},
            {
                "Retry-After": "17",
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": "9999",
            },
        ),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, sleep=sleeps.append, wall_clock=lambda: 1000)

    client.get_repository_stats("owner", "repo")

    assert sleeps == [17]


def test_rate_limit_reset_waits_until_after_the_reset_boundary() -> None:
    transport = SequenceTransport(
        json_response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"},
        ),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, sleep=sleeps.append, wall_clock=lambda: 1000)

    client.get_repository_stats("owner", "repo")

    assert sleeps == [31]


@pytest.mark.parametrize("reset_at", ["999", "1000"])
def test_elapsed_rate_limit_reset_still_uses_exponential_backoff(reset_at: str) -> None:
    transport = SequenceTransport(
        json_response(
            403,
            {"message": "API rate limit exceeded"},
            {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset_at},
        ),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, sleep=sleeps.append, wall_clock=lambda: 1000)

    client.get_repository_stats("owner", "repo")

    assert sleeps == [1]


def test_secondary_rate_limit_without_headers_waits_at_least_60_seconds() -> None:
    transport = SequenceTransport(
        json_response(403, {"message": "secondary rate limit"}),
        json_response(200, {"count": 10}),
    )
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, sleep=sleeps.append)

    client.get_repository_stats("owner", "repo")

    assert sleeps == [60]


@pytest.mark.parametrize(
    ("status", "body", "headers", "exception_type"),
    [
        (404, {"message": "Not Found"}, {}, GitHubNotFoundError),
        (422, {"message": "Validation Failed"}, {}, GitHubValidationError),
        (401, {"message": "Bad credentials"}, {}, GitHubAuthenticationError),
        (403, {"message": "Forbidden"}, {}, GitHubAuthenticationError),
        (
            429,
            {"message": "rate limit exceeded"},
            {"Retry-After": "0"},
            GitHubRateLimitError,
        ),
        (503, {"message": "Unavailable"}, {}, GitHubServerError),
    ],
)
def test_http_failures_are_typed_and_non_retryable_4xx_are_not_retried(
    status: int,
    body: object,
    headers: Mapping[str, str],
    exception_type: type[GitHubClientError],
) -> None:
    transport = SequenceTransport(json_response(status, body, headers))
    client = GitHubClient(transport=transport, max_retries=0)

    with pytest.raises(exception_type) as captured:
        client.get_repository("owner", "repo")

    assert captured.value.request.status_code == status
    assert captured.value.request.retry_count == 0
    assert len(transport.requests) == 1


def test_transport_failure_is_typed_after_retry_exhaustion() -> None:
    transport = SequenceTransport(ConnectionError("offline"), TimeoutError("still offline"))
    sleeps: list[float] = []
    client = GitHubClient(transport=transport, max_retries=1, sleep=sleeps.append)

    with pytest.raises(GitHubTransportError) as captured:
        client.get_repository_stats("owner", "repo")

    assert captured.value.request.status_code is None
    assert captured.value.request.retry_count == 1
    assert sleeps == [1]


@pytest.mark.parametrize(
    "response",
    [
        TransportResponse(200, {}, b"not-json"),
        json_response(200, {"count": "ten"}),
        json_response(200, {"count": -1}),
        json_response(200, [{"week": 1, "total": 1, "days": [1, 2]}]),
    ],
)
def test_invalid_success_response_is_rejected(response: TransportResponse) -> None:
    client = GitHubClient(transport=SequenceTransport(response))

    with pytest.raises(GitHubResponseFormatError):
        if response.body.startswith(b"["):
            client.get_star_history("owner", "repo")
        else:
            client.get_repository_stats("owner", "repo")


def test_structured_log_and_error_do_not_expose_token(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "do-not-log-this-token"
    transport = SequenceTransport(json_response(404, {"message": "Not Found"}))
    client = GitHubClient(token=token, transport=transport)
    github_logger = logging.getLogger("repovil.github_client")
    monkeypatch.setattr(github_logger, "disabled", False)

    with caplog.at_level(logging.INFO, logger=github_logger.name), pytest.raises(
        GitHubNotFoundError
    ) as captured:
        client.get_repository("owner", "repo")

    record = caplog.records[0]
    assert record.__dict__["response_status"] == 404
    assert record.__dict__["retry_count"] == 0
    assert isinstance(record.__dict__["duration_ms"], int)
    assert token not in caplog.text
    assert token not in str(captured.value)


def test_api_import_graph_does_not_reach_github_client() -> None:
    package_root = Path(__file__).parents[1] / "src" / "repovil"
    pending = ["api"]
    visited: set[str] = set()

    while pending:
        module = pending.pop()
        if module in visited:
            continue
        visited.add(module)
        module_path = package_root / f"{module.replace('.', '/')}.py"
        if not module_path.exists():
            continue
        tree = ast.parse(module_path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module == "repovil.github_client":
                    fail("user-facing API import graph must not depend on GitHubClient")
                if node.module.startswith("repovil."):
                    pending.append(node.module.removeprefix("repovil."))

    assert "github_client" not in visited


@pytest.mark.live
def test_live_verified_public_endpoints() -> None:
    if os.environ.get("GITHUB_LIVE_TEST") != "1":
        pytest.skip("set GITHUB_LIVE_TEST=1 to call GitHub")

    client = GitHubClient(token=os.environ.get("GITHUB_TOKEN"), max_retries=1)

    search = client.search_repositories("ai-agent", per_page=1)
    repository = client.get_repository("octocat", "Hello-World")
    renamed_repository = client.get_repository("tiangolo", "fastapi")
    stats = client.get_repository_stats("octocat", "Hello-World")
    history = client.get_star_history("octocat", "Hello-World", per_page=1)

    assert search.total_count >= 1
    assert len(search.repositories) == 1
    assert repository.repository.github_id == 1_296_269
    assert renamed_repository.repository.full_name == "fastapi/fastapi"
    assert stats.star_count >= 0
    assert len(history.weeks) <= 1
