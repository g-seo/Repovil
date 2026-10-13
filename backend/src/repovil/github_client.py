"""GitHub REST adapter used exclusively by background workers."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC
from email.utils import parsedate_to_datetime
from typing import NoReturn, Protocol, TypeVar, cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, build_opener

GITHUB_API_VERSION = "2026-03-10"
DEFAULT_BASE_URL = "https://api.github.com"
DEFAULT_USER_AGENT = "repovil/0.1"
RATE_LIMIT_RESET_BUFFER_SECONDS = 1.0

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class RateLimit:
    """Rate-limit values returned with a GitHub response."""

    limit: int | None
    remaining: int | None
    reset_at: int | None
    resource: str | None


@dataclass(frozen=True, slots=True)
class RequestMetadata:
    """Request facts workers can persist on run items or structured logs."""

    status_code: int | None
    retry_count: int
    duration_ms: int
    rate_limit: RateLimit


@dataclass(frozen=True, slots=True)
class Repository:
    """GitHub repository fields required by discovery and tracking."""

    github_id: int
    owner: str
    name: str
    full_name: str
    github_url: str
    description: str | None
    language: str | None
    stars: int
    topics: tuple[str, ...]
    visibility: str
    fork: bool
    archived: bool


@dataclass(frozen=True, slots=True)
class SearchRepositoriesPage:
    """One explicitly requested repository Search page."""

    total_count: int
    incomplete_results: bool
    repositories: tuple[Repository, ...]
    page: int
    per_page: int
    request: RequestMetadata


@dataclass(frozen=True, slots=True)
class RepositoryResult:
    """A repository lookup and its request metadata."""

    repository: Repository
    request: RequestMetadata


@dataclass(frozen=True, slots=True)
class RepositoryStats:
    """Current aggregate star count."""

    star_count: int
    request: RequestMetadata


@dataclass(frozen=True, slots=True)
class StarHistoryWeek:
    """One GitHub-defined history week; its boundary is not assumed to be UTC."""

    week: int
    total: int
    days: tuple[int, int, int, int, int, int, int]


@dataclass(frozen=True, slots=True)
class StarHistoryPage:
    """One explicitly requested star-history page."""

    weeks: tuple[StarHistoryWeek, ...]
    page: int
    per_page: int
    request: RequestMetadata


class GitHubClientError(Exception):
    """Base exception for a failed GitHub request."""

    def __init__(self, message: str, *, request: RequestMetadata) -> None:
        super().__init__(message)
        self.request = request


class GitHubTransportError(GitHubClientError):
    """A timeout or connection failure after retries are exhausted."""


class GitHubNotFoundError(GitHubClientError):
    """The requested repository does not exist or is no longer visible."""


class GitHubAuthenticationError(GitHubClientError):
    """The configured credential is missing required access or is invalid."""


class GitHubRateLimitError(GitHubClientError):
    """A primary or secondary rate limit remained exhausted after retries."""


class GitHubValidationError(GitHubClientError):
    """GitHub rejected the request parameters."""


class GitHubServerError(GitHubClientError):
    """GitHub returned a server error after retries are exhausted."""


class GitHubResponseError(GitHubClientError):
    """GitHub returned another non-success response."""


class GitHubResponseFormatError(GitHubClientError):
    """A successful response did not match the verified API contract."""


@dataclass(frozen=True, slots=True)
class TransportResponse:
    """Small HTTP response shape used by the client and unit-test transports."""

    status_code: int
    headers: Mapping[str, str]
    body: bytes


class GitHubTransport(Protocol):
    """Replaceable transport boundary for deterministic adapter tests."""

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse: ...


class UrllibGitHubTransport:
    """Production transport using Python's redirect-aware HTTPS implementation."""

    def __init__(self) -> None:
        self._opener = build_opener()

    def send(
        self,
        *,
        method: str,
        url: str,
        headers: Mapping[str, str],
        timeout: float,
    ) -> TransportResponse:
        request = Request(url, method=method, headers=dict(headers))
        try:
            with self._opener.open(request, timeout=timeout) as response:
                return TransportResponse(
                    status_code=response.status,
                    headers=dict(response.headers.items()),
                    body=response.read(),
                )
        except HTTPError as error:
            return TransportResponse(
                status_code=error.code,
                headers=dict(error.headers.items()) if error.headers is not None else {},
                body=error.read(),
            )


_ResultT = TypeVar("_ResultT")


class GitHubClient:
    """Minimal, policy-free adapter around the verified GitHub REST endpoints."""

    def __init__(
        self,
        *,
        token: str | None = None,
        api_version: str = GITHUB_API_VERSION,
        timeout: float = 10.0,
        max_retries: int = 3,
        backoff_base: float = 1.0,
        max_backoff: float = 60.0,
        user_agent: str = DEFAULT_USER_AGENT,
        base_url: str = DEFAULT_BASE_URL,
        transport: GitHubTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        if max_retries < 0:
            raise ValueError("max_retries must be zero or greater")
        if backoff_base <= 0 or max_backoff <= 0:
            raise ValueError("backoff values must be greater than zero")
        if not api_version or not user_agent:
            raise ValueError("api_version and user_agent must not be empty")

        self._token = token or None
        self._api_version = api_version
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._max_backoff = max_backoff
        self._user_agent = user_agent
        self._base_url = base_url.rstrip("/")
        self._transport = transport or UrllibGitHubTransport()
        self._sleep = sleep
        self._monotonic = monotonic
        self._wall_clock = wall_clock

    def search_repositories(
        self,
        topic: str,
        *,
        min_stars: int = 200,
        max_stars: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> SearchRepositoriesPage:
        """Return one Search page for an inclusive star range."""
        normalized_topic = topic.strip()
        if not normalized_topic:
            raise ValueError("topic must not be empty")
        if min_stars < 0 or (max_stars is not None and max_stars < min_stars):
            raise ValueError("star range must be non-negative and ordered")
        self._validate_pagination(page, per_page, maximum_per_page=100)
        if (page - 1) * per_page >= 1_000:
            raise ValueError("repository Search cannot access results after the first 1,000")

        upper = "*" if max_stars is None else str(max_stars)
        query = (
            f"topic:{normalized_topic} stars:{min_stars}..{upper} "
            "fork:false archived:false is:public"
        )
        body, metadata = self._request_json(
            "/search/repositories",
            params={
                "q": query,
                "sort": "stars",
                "order": "desc",
                "per_page": per_page,
                "page": page,
            },
        )
        payload = self._require_mapping(body, metadata)
        items = self._require_list(payload, "items", metadata)
        repositories = tuple(self._parse_repository(item, metadata) for item in items)
        return SearchRepositoriesPage(
            total_count=self._require_nonnegative_int(payload, "total_count", metadata),
            incomplete_results=self._require_bool(payload, "incomplete_results", metadata),
            repositories=repositories,
            page=page,
            per_page=per_page,
            request=metadata,
        )

    def get_repository(self, owner: str, name: str) -> RepositoryResult:
        """Return current metadata, following safe GET redirects in the transport."""
        path = self._repository_path(owner, name)
        body, metadata = self._request_json(path)
        return RepositoryResult(
            repository=self._parse_repository(body, metadata),
            request=metadata,
        )

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats:
        """Return the current aggregate star count."""
        path = f"{self._repository_path(owner, name)}/stargazers/count"
        body, metadata = self._request_json(path)
        payload = self._require_mapping(body, metadata)
        return RepositoryStats(
            star_count=self._require_nonnegative_int(payload, "count", metadata),
            request=metadata,
        )

    def get_star_history(
        self,
        owner: str,
        name: str,
        *,
        page: int = 1,
        per_page: int = 30,
    ) -> StarHistoryPage:
        """Return one latest-first history page using GitHub-defined week boundaries."""
        self._validate_pagination(page, per_page, maximum_per_page=30)
        if page > 100:
            raise ValueError("star history page must not exceed 100")

        path = f"{self._repository_path(owner, name)}/stargazers/history"
        body, metadata = self._request_json(
            path,
            params={"per_page": per_page, "page": page},
        )
        items = self._require_list_value(body, metadata)
        weeks = tuple(self._parse_history_week(item, metadata) for item in items)
        return StarHistoryPage(
            weeks=weeks,
            page=page,
            per_page=per_page,
            request=metadata,
        )

    def _request_json(
        self,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
    ) -> tuple[object, RequestMetadata]:
        url = f"{self._base_url}{path}"
        if params:
            url = f"{url}?{urlencode(params)}"
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": self._api_version,
            "User-Agent": self._user_agent,
        }
        if self._token is not None:
            headers["Authorization"] = f"Bearer {self._token}"

        started_at = self._monotonic()
        for attempt in range(self._max_retries + 1):
            try:
                response = self._transport.send(
                    method="GET",
                    url=url,
                    headers=headers,
                    timeout=self._timeout,
                )
            except (TimeoutError, URLError, ConnectionError, OSError) as error:
                metadata = self._metadata(None, {}, attempt, started_at)
                self._log_request(path, metadata)
                if attempt < self._max_retries:
                    self._sleep(self._exponential_delay(attempt))
                    continue
                raise GitHubTransportError(
                    f"GitHub request failed after {attempt + 1} attempts: "
                    f"{type(error).__name__}",
                    request=metadata,
                ) from error

            normalized_headers = {key.lower(): value for key, value in response.headers.items()}
            metadata = self._metadata(
                response.status_code,
                normalized_headers,
                attempt,
                started_at,
            )
            self._log_request(path, metadata)

            if 200 <= response.status_code < 300:
                body = self._decode_json(response.body, metadata)
                return body, metadata

            body = self._decode_error_json(response.body)

            is_rate_limited = self._is_rate_limited(
                response.status_code,
                normalized_headers,
                body,
            )
            retryable = response.status_code >= 500 or is_rate_limited
            if retryable and attempt < self._max_retries:
                delay = self._retry_delay(
                    attempt,
                    normalized_headers,
                    is_rate_limited=is_rate_limited,
                )
                logger.info(
                    "github_request_retry_scheduled",
                    extra={
                        "github_endpoint": path,
                        "retry_count": attempt + 1,
                        "sleep_seconds": delay,
                        "rate_limit_limit": metadata.rate_limit.limit,
                        "rate_limit_remaining": metadata.rate_limit.remaining,
                        "rate_limit_reset_at": metadata.rate_limit.reset_at,
                        "rate_limit_resource": metadata.rate_limit.resource,
                    },
                )
                self._sleep(delay)
                continue
            self._raise_for_response(response.status_code, body, metadata, is_rate_limited)

        raise AssertionError("retry loop must return or raise")

    def _metadata(
        self,
        status_code: int | None,
        headers: Mapping[str, str],
        retry_count: int,
        started_at: float,
    ) -> RequestMetadata:
        return RequestMetadata(
            status_code=status_code,
            retry_count=retry_count,
            duration_ms=max(0, round((self._monotonic() - started_at) * 1_000)),
            rate_limit=RateLimit(
                limit=self._optional_header_int(headers, "x-ratelimit-limit"),
                remaining=self._optional_header_int(headers, "x-ratelimit-remaining"),
                reset_at=self._optional_header_int(headers, "x-ratelimit-reset"),
                resource=headers.get("x-ratelimit-resource"),
            ),
        )

    @staticmethod
    def _log_request(path: str, metadata: RequestMetadata) -> None:
        logger.info(
            "github_request",
            extra={
                "github_endpoint": path,
                "response_status": metadata.status_code,
                "retry_count": metadata.retry_count,
                "duration_ms": metadata.duration_ms,
                "rate_limit_limit": metadata.rate_limit.limit,
                "rate_limit_remaining": metadata.rate_limit.remaining,
                "rate_limit_reset_at": metadata.rate_limit.reset_at,
                "rate_limit_resource": metadata.rate_limit.resource,
            },
        )

    def _retry_delay(
        self,
        attempt: int,
        headers: Mapping[str, str],
        *,
        is_rate_limited: bool,
    ) -> float:
        retry_after = headers.get("retry-after")
        if retry_after is not None:
            parsed_retry_after = self._parse_retry_after(retry_after)
            if parsed_retry_after is not None:
                return parsed_retry_after

        if headers.get("x-ratelimit-remaining") == "0":
            reset_at = self._optional_header_int(headers, "x-ratelimit-reset")
            if reset_at is not None:
                return max(
                    self._exponential_delay(attempt),
                    float(reset_at) - self._wall_clock() + RATE_LIMIT_RESET_BUFFER_SECONDS,
                )

        delay = self._exponential_delay(attempt)
        if is_rate_limited:
            return max(60.0, delay)
        return delay

    def _exponential_delay(self, attempt: int) -> float:
        return float(min(self._max_backoff, self._backoff_base * (2**attempt)))

    def _parse_retry_after(self, value: str) -> float | None:
        try:
            return max(0.0, float(value))
        except ValueError:
            try:
                parsed = parsedate_to_datetime(value)
            except (TypeError, ValueError, OverflowError):
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return max(0.0, parsed.timestamp() - self._wall_clock())

    @staticmethod
    def _is_rate_limited(
        status_code: int,
        headers: Mapping[str, str],
        body: object,
    ) -> bool:
        if status_code == 429:
            return True
        if status_code != 403:
            return False
        if "retry-after" in headers or headers.get("x-ratelimit-remaining") == "0":
            return True
        if isinstance(body, dict):
            message = body.get("message")
            return isinstance(message, str) and (
                "rate limit" in message.lower() or "abuse detection" in message.lower()
            )
        return False

    @staticmethod
    def _raise_for_response(
        status_code: int,
        body: object,
        metadata: RequestMetadata,
        is_rate_limited: bool,
    ) -> None:
        message = "GitHub request failed"
        if isinstance(body, dict) and isinstance(body.get("message"), str):
            message = cast(str, body["message"])
        detail = f"GitHub returned HTTP {status_code}: {message}"

        if is_rate_limited:
            raise GitHubRateLimitError(detail, request=metadata)
        if status_code == 404:
            raise GitHubNotFoundError(detail, request=metadata)
        if status_code in (401, 403):
            raise GitHubAuthenticationError(detail, request=metadata)
        if status_code == 422:
            raise GitHubValidationError(detail, request=metadata)
        if status_code >= 500:
            raise GitHubServerError(detail, request=metadata)
        raise GitHubResponseError(detail, request=metadata)

    @staticmethod
    def _decode_json(body: bytes, metadata: RequestMetadata) -> object:
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise GitHubResponseFormatError(
                "GitHub returned invalid JSON",
                request=metadata,
            ) from error

    @staticmethod
    def _decode_error_json(body: bytes) -> object:
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _repository_path(owner: str, name: str) -> str:
        if not owner.strip() or not name.strip():
            raise ValueError("repository owner and name must not be empty")
        return f"/repos/{quote(owner, safe='')}/{quote(name, safe='')}"

    @staticmethod
    def _validate_pagination(page: int, per_page: int, *, maximum_per_page: int) -> None:
        if page < 1:
            raise ValueError("page must be at least 1")
        if not 1 <= per_page <= maximum_per_page:
            raise ValueError(f"per_page must be between 1 and {maximum_per_page}")

    @classmethod
    def _parse_repository(
        cls,
        value: object,
        metadata: RequestMetadata,
    ) -> Repository:
        payload = cls._require_mapping(value, metadata)
        owner_payload = cls._require_mapping(payload.get("owner"), metadata)
        topics_value = cls._require_list(payload, "topics", metadata)
        topics: list[str] = []
        for topic in topics_value:
            if not isinstance(topic, str):
                cls._format_error("repository topics must contain only strings", metadata)
            topics.append(topic)

        description = payload.get("description")
        language = payload.get("language")
        if description is not None and not isinstance(description, str):
            cls._format_error("repository description must be a string or null", metadata)
        if language is not None and not isinstance(language, str):
            cls._format_error("repository language must be a string or null", metadata)

        private = cls._require_bool(payload, "private", metadata)
        visibility_value = payload.get("visibility", "private" if private else "public")
        if not isinstance(visibility_value, str):
            cls._format_error("repository visibility must be a string", metadata)

        github_id = cls._require_nonnegative_int(payload, "id", metadata)
        if github_id == 0:
            cls._format_error("GitHub response field 'id' must be greater than zero", metadata)

        return Repository(
            github_id=github_id,
            owner=cls._require_str(owner_payload, "login", metadata),
            name=cls._require_str(payload, "name", metadata),
            full_name=cls._require_str(payload, "full_name", metadata),
            github_url=cls._require_str(payload, "html_url", metadata),
            description=description,
            language=language,
            stars=cls._require_nonnegative_int(payload, "stargazers_count", metadata),
            topics=tuple(topics),
            visibility=visibility_value,
            fork=cls._require_bool(payload, "fork", metadata),
            archived=cls._require_bool(payload, "archived", metadata),
        )

    @classmethod
    def _parse_history_week(
        cls,
        value: object,
        metadata: RequestMetadata,
    ) -> StarHistoryWeek:
        payload = cls._require_mapping(value, metadata)
        days_value = cls._require_list(payload, "days", metadata)
        if len(days_value) != 7 or any(type(day) is not int or day < 0 for day in days_value):
            cls._format_error(
                "star history days must contain seven non-negative integers",
                metadata,
            )
        days = cast(tuple[int, int, int, int, int, int, int], tuple(days_value))
        week = cls._require_int(payload, "week", metadata)
        total = cls._require_int(payload, "total", metadata)
        if week < 0 or total < 0:
            cls._format_error("star history week and total must be non-negative", metadata)
        return StarHistoryWeek(week=week, total=total, days=days)

    @classmethod
    def _require_mapping(
        cls,
        value: object,
        metadata: RequestMetadata,
    ) -> dict[str, object]:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            cls._format_error("GitHub response must be a JSON object", metadata)
        return cast(dict[str, object], value)

    @classmethod
    def _require_list_value(
        cls,
        value: object,
        metadata: RequestMetadata,
    ) -> list[object]:
        if not isinstance(value, list):
            cls._format_error("GitHub response must be a JSON array", metadata)
        return cast(list[object], value)

    @classmethod
    def _require_list(
        cls,
        payload: Mapping[str, object],
        key: str,
        metadata: RequestMetadata,
    ) -> list[object]:
        value = payload.get(key)
        if not isinstance(value, list):
            cls._format_error(f"GitHub response field {key!r} must be an array", metadata)
        return cast(list[object], value)

    @classmethod
    def _require_str(
        cls,
        payload: Mapping[str, object],
        key: str,
        metadata: RequestMetadata,
    ) -> str:
        value = payload.get(key)
        if not isinstance(value, str):
            cls._format_error(f"GitHub response field {key!r} must be a string", metadata)
        return value

    @classmethod
    def _require_int(
        cls,
        payload: Mapping[str, object],
        key: str,
        metadata: RequestMetadata,
    ) -> int:
        value = payload.get(key)
        if type(value) is not int:
            cls._format_error(f"GitHub response field {key!r} must be an integer", metadata)
        return value

    @classmethod
    def _require_bool(
        cls,
        payload: Mapping[str, object],
        key: str,
        metadata: RequestMetadata,
    ) -> bool:
        value = payload.get(key)
        if type(value) is not bool:
            cls._format_error(f"GitHub response field {key!r} must be a boolean", metadata)
        return value

    @classmethod
    def _require_nonnegative_int(
        cls,
        payload: Mapping[str, object],
        key: str,
        metadata: RequestMetadata,
    ) -> int:
        value = cls._require_int(payload, key, metadata)
        if value < 0:
            cls._format_error(
                f"GitHub response field {key!r} must be non-negative",
                metadata,
            )
        return value

    @staticmethod
    def _format_error(message: str, metadata: RequestMetadata) -> NoReturn:
        raise GitHubResponseFormatError(message, request=metadata)

    @staticmethod
    def _optional_header_int(headers: Mapping[str, str], key: str) -> int | None:
        value = headers.get(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None
