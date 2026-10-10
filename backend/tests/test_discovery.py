from __future__ import annotations

from collections.abc import Callable
from typing import cast

import psycopg
import pytest
from test_category_sync import DEFAULT_CONFIG
from test_migrations import _alembic_config

from alembic import command
from repovil.category_sync import sync_categories
from repovil.db import connect_database
from repovil.discovery import (
    DISCOVERY_LOCK_ID,
    DiscoveryAlreadyRunningError,
    StarRange,
    run_discovery,
    search_repositories,
)
from repovil.github_client import (
    GitHubRateLimitError,
    RateLimit,
    Repository,
    RequestMetadata,
    SearchRepositoriesPage,
)

REQUEST = RequestMetadata(
    status_code=200,
    retry_count=0,
    duration_ms=5,
    rate_limit=RateLimit(limit=30, remaining=29, reset_at=2_000, resource="search"),
)


@pytest.fixture
def discovery_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    return postgres_schema_url


def repository(
    github_id: int,
    *,
    stars: int = 200,
    topics: tuple[str, ...] = ("ai-agent",),
    owner: str = "owner",
    name: str | None = None,
    visibility: str = "public",
    fork: bool = False,
    archived: bool = False,
) -> Repository:
    repository_name = name or f"repo-{github_id}"
    return Repository(
        github_id=github_id,
        owner=owner,
        name=repository_name,
        full_name=f"{owner}/{repository_name}",
        github_url=f"https://github.com/{owner}/{repository_name}",
        description=f"Repository {github_id}",
        language="Python",
        stars=stars,
        topics=topics,
        visibility=visibility,
        fork=fork,
        archived=archived,
    )


def page(
    total_count: int,
    repositories: tuple[Repository, ...] = (),
    *,
    page_number: int = 1,
    incomplete: bool = False,
) -> SearchRepositoriesPage:
    return SearchRepositoriesPage(
        total_count=total_count,
        incomplete_results=incomplete,
        repositories=repositories,
        page=page_number,
        per_page=100,
        request=REQUEST,
    )


SearchHandler = Callable[[str, int, int | None, int], SearchRepositoriesPage]


class FakeClient:
    def __init__(self, handler: SearchHandler) -> None:
        self.handler = handler
        self.calls: list[tuple[str, int, int | None, int]] = []

    def search_repositories(
        self,
        topic: str,
        *,
        min_stars: int = 200,
        max_stars: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> SearchRepositoriesPage:
        assert per_page == 100
        self.calls.append((topic, min_stars, max_stars, page))
        return self.handler(topic, min_stars, max_stars, page)


@pytest.mark.parametrize("total_count", [999, 1_000])
def test_search_paginates_ranges_at_or_below_the_limit(total_count: int) -> None:
    def handler(
        topic: str,
        minimum: int,
        maximum: int | None,
        page_number: int,
    ) -> SearchRepositoriesPage:
        assert (topic, minimum, maximum) == ("ai-agent", 200, None)
        first_id = (page_number - 1) * 100 + 1
        last_id = min(page_number * 100, total_count)
        items = tuple(repository(value) for value in range(first_id, last_id + 1))
        return page(total_count, items, page_number=page_number)

    client = FakeClient(handler)
    result = search_repositories(client, [StarRange("ai-agent", 200, None)])

    assert len(result.repositories) == total_count
    assert result.failed_ranges == ()
    assert result.successful_range_count == 1
    assert len(client.calls) == (total_count + 99) // 100


def test_search_splits_1001_results_with_non_overlapping_inclusive_boundaries() -> None:
    def handler(
        topic: str,
        minimum: int,
        maximum: int | None,
        page_number: int,
    ) -> SearchRepositoriesPage:
        if (minimum, maximum) == (200, None):
            return page(1_001, (repository(1_001, stars=201),))
        if (minimum, maximum) == (200, 200):
            first_id = (page_number - 1) * 100 + 1
            items = tuple(repository(value) for value in range(first_id, first_id + 100))
            return page(1_000, items, page_number=page_number)
        assert (minimum, maximum, page_number) == (201, 201, 1)
        return page(1, (repository(1_001, stars=201),))

    client = FakeClient(handler)
    result = search_repositories(client, [StarRange("ai-agent", 200, None)])

    assert len(result.repositories) == 1_001
    assert result.failed_ranges == ()
    assert result.successful_range_count == 2
    assert ("ai-agent", 200, 200, 1) in client.calls
    assert ("ai-agent", 201, 201, 1) in client.calls


def test_search_records_an_overfull_single_star_range() -> None:
    client = FakeClient(
        lambda _topic, _minimum, _maximum, _page: page(
            1_001,
            (repository(1, stars=200),),
        )
    )

    result = search_repositories(client, [StarRange("ai-agent", 200, 200)])

    assert result.repositories == ()
    assert result.successful_range_count == 0
    assert result.failed_ranges[0].error_type == "unsplittable_range"
    assert result.failed_ranges[0].minimum == 200
    assert result.failed_ranges[0].maximum == 200


def test_incomplete_result_discards_the_range() -> None:
    client = FakeClient(
        lambda _topic, _minimum, _maximum, _page: page(
            10,
            (repository(1),),
            incomplete=True,
        )
    )

    result = search_repositories(client, [StarRange("ai-agent", 200, None)])

    assert result.repositories == ()
    assert result.failed_ranges[0].error_type == "incomplete_results"


def test_middle_page_failure_discards_partial_range_and_records_retry_metadata() -> None:
    def handler(
        _topic: str,
        _minimum: int,
        _maximum: int | None,
        page_number: int,
    ) -> SearchRepositoriesPage:
        if page_number == 2:
            request = RequestMetadata(
                status_code=429,
                retry_count=3,
                duration_ms=250,
                rate_limit=RateLimit(30, 0, 2_000, "search"),
            )
            raise GitHubRateLimitError("rate limit remained exhausted", request=request)
        return page(150, tuple(repository(value) for value in range(1, 101)))

    result = search_repositories(
        FakeClient(handler),
        [StarRange("ai-agent", 200, None)],
    )

    assert result.repositories == ()
    failure = result.failed_ranges[0]
    assert failure.error_type == "GitHubRateLimitError"
    assert failure.response_status == 429
    assert failure.retry_count == 3
    assert failure.duration_ms == 250


def _topic_handler(
    repositories_by_topic: dict[str, tuple[Repository, ...]],
    *,
    failing_topic: str | None = None,
) -> SearchHandler:
    def handler(
        topic: str,
        _minimum: int,
        _maximum: int | None,
        _page_number: int,
    ) -> SearchRepositoriesPage:
        if topic == failing_topic:
            request = RequestMetadata(
                status_code=429,
                retry_count=3,
                duration_ms=250,
                rate_limit=RateLimit(30, 0, 2_000, "search"),
            )
            raise GitHubRateLimitError("rate limit remained exhausted", request=request)
        items = repositories_by_topic.get(topic, ())
        return page(len(items), items)

    return handler


@pytest.mark.integration
def test_discovery_is_idempotent_updates_identity_topics_and_reactivates(
    discovery_database_url: str,
) -> None:
    sync_categories(discovery_database_url, DEFAULT_CONFIG)
    initial = repository(101, topics=("ai-agent", "mcp-server"), name="project")
    ineligible = repository(202, stars=199)
    forked = repository(203, fork=True)
    archived = repository(204, archived=True)
    private = repository(205, visibility="private")
    first_client = FakeClient(
        _topic_handler(
            {
                "ai-agent": (initial, ineligible, forked, archived, private),
                "mcp-server": (initial,),
            }
        )
    )

    first = run_discovery(discovery_database_url, first_client)

    assert first.status == "COMPLETED"
    assert first.discovered_count == 1
    assert first.added_count == 1
    with psycopg.connect(discovery_database_url) as connection:
        assert connection.execute(
            "SELECT status FROM repositories WHERE github_id = 101"
        ).fetchone() == ("bootstrap_pending",)
        connection.execute(
            "UPDATE repositories SET status = 'inactive' WHERE github_id = 101"
        )

    renamed = repository(
        101,
        stars=250,
        topics=("mcp-server",),
        owner="new-owner",
        name="renamed",
    )
    second = run_discovery(
        discovery_database_url,
        FakeClient(_topic_handler({"mcp-server": (renamed,)})),
    )
    third = run_discovery(
        discovery_database_url,
        FakeClient(_topic_handler({"mcp-server": (renamed,)})),
    )

    assert second.added_count == 0
    assert third.added_count == 0
    with psycopg.connect(discovery_database_url) as connection:
        stored = connection.execute(
            """
            SELECT id, owner, name, current_stars, status
            FROM repositories
            WHERE github_id = 101
            """
        ).fetchone()
        assert stored is not None
        mappings = connection.execute(
            """
            SELECT topics.name, repository_topics.active
            FROM repository_topics
            JOIN topics ON topics.id = repository_topics.topic_id
            WHERE repository_topics.repository_id = %s
            ORDER BY topics.name
            """,
            (stored[0],),
        ).fetchall()
        counts = connection.execute(
            "SELECT count(*), count(DISTINCT github_id) FROM repositories"
        ).fetchone()

    assert stored[1:] == ("new-owner", "renamed", 250, "active")
    assert mappings == [("ai-agent", False), ("mcp-server", True)]
    assert counts == (1, 1)


@pytest.mark.integration
def test_failed_ranges_are_persisted_and_retry_only_repeats_those_ranges(
    discovery_database_url: str,
) -> None:
    sync_categories(discovery_database_url, DEFAULT_CONFIG)
    first = run_discovery(
        discovery_database_url,
        FakeClient(_topic_handler({}, failing_topic="mcp-server")),
    )

    assert first.status == "PARTIAL"
    assert len(first.failed_ranges) == 1
    retry_client = FakeClient(
        _topic_handler({"mcp-server": (repository(303, topics=("mcp-server",)),)})
    )
    retried = run_discovery(
        discovery_database_url,
        retry_client,
        retry_run_id=first.run_id,
    )

    assert retried.status == "COMPLETED"
    assert retried.added_count == 1
    assert {call[0] for call in retry_client.calls} == {"mcp-server"}
    with psycopg.connect(discovery_database_url) as connection:
        stored_failure = connection.execute(
            "SELECT failed_ranges FROM discovery_runs WHERE id = %s",
            (first.run_id,),
        ).fetchone()
    assert stored_failure is not None
    failed_ranges = cast(list[dict[str, object]], stored_failure[0])
    assert failed_ranges[0]["topic"] == "mcp-server"
    assert failed_ranges[0]["response_status"] == 429


@pytest.mark.integration
def test_database_lock_prevents_a_concurrent_discovery_run(
    discovery_database_url: str,
) -> None:
    sync_categories(discovery_database_url, DEFAULT_CONFIG)
    with connect_database(discovery_database_url) as lock_connection:
        assert lock_connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (DISCOVERY_LOCK_ID,),
        ).fetchone() == (True,)

        with pytest.raises(DiscoveryAlreadyRunningError):
            run_discovery(
                discovery_database_url,
                FakeClient(_topic_handler({})),
            )

        lock_connection.execute("SELECT pg_advisory_unlock(%s)", (DISCOVERY_LOCK_ID,))

    with psycopg.connect(discovery_database_url) as connection:
        assert connection.execute("SELECT count(*) FROM discovery_runs").fetchone() == (0,)

