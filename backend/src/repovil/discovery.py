"""Daily topic-based repository discovery worker."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from psycopg import Connection
from psycopg.types.json import Jsonb

from repovil.db import connect_database
from repovil.github_client import (
    GitHubClientError,
    Repository,
    SearchRepositoriesPage,
)
from repovil.observability import configure_logging
from repovil.settings import get_settings
from repovil.worker import create_github_client

logger = logging.getLogger(__name__)

DISCOVERY_LOCK_ID = 7_263_570_386_938_852_465
MINIMUM_STARS = 200
SEARCH_PAGE_SIZE = 100
SEARCH_RESULT_LIMIT = 1_000


class DiscoveryAlreadyRunningError(RuntimeError):
    """Raised when another discovery process owns the database lock."""


class DiscoveryConfigurationError(RuntimeError):
    """Raised when discovery has no valid active topic work to perform."""


class DiscoveryClient(Protocol):
    """Narrow GitHubClient surface used by discovery."""

    def search_repositories(
        self,
        topic: str,
        *,
        min_stars: int = 200,
        max_stars: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> SearchRepositoriesPage: ...


@dataclass(frozen=True, slots=True)
class StarRange:
    """One inclusive GitHub Search star range."""

    topic: str
    minimum: int
    maximum: int | None


@dataclass(frozen=True, slots=True)
class FailedRange:
    """A range that can be retried without repeating successful ranges."""

    topic: str
    minimum: int
    maximum: int | None
    error_type: str
    error_message: str
    response_status: int | None = None
    retry_count: int = 0
    duration_ms: int | None = None

    def as_json(self) -> dict[str, object]:
        return {
            "topic": self.topic,
            "min_stars": self.minimum,
            "max_stars": self.maximum,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "response_status": self.response_status,
            "retry_count": self.retry_count,
            "duration_ms": self.duration_ms,
        }


@dataclass(frozen=True, slots=True)
class SearchResult:
    """Complete result of one or more requested search ranges."""

    repositories: tuple[Repository, ...]
    failed_ranges: tuple[FailedRange, ...]
    successful_range_count: int


@dataclass(frozen=True, slots=True)
class DiscoveryRunResult:
    """Committed discovery run summary."""

    run_id: int
    status: str
    discovered_count: int
    added_count: int
    failed_ranges: tuple[FailedRange, ...]


def _failure_from_error(star_range: StarRange, error: GitHubClientError) -> FailedRange:
    request = error.request
    return FailedRange(
        topic=star_range.topic,
        minimum=star_range.minimum,
        maximum=star_range.maximum,
        error_type=type(error).__name__,
        error_message=str(error),
        response_status=request.status_code,
        retry_count=request.retry_count,
        duration_ms=request.duration_ms,
    )


def _incomplete_failure(
    star_range: StarRange,
    page: SearchRepositoriesPage,
) -> FailedRange:
    return FailedRange(
        topic=star_range.topic,
        minimum=star_range.minimum,
        maximum=star_range.maximum,
        error_type="incomplete_results",
        error_message="GitHub Search returned incomplete_results=true",
        response_status=page.request.status_code,
        retry_count=page.request.retry_count,
        duration_ms=page.request.duration_ms,
    )


def _overfull_failure(star_range: StarRange, page: SearchRepositoriesPage) -> FailedRange:
    return FailedRange(
        topic=star_range.topic,
        minimum=star_range.minimum,
        maximum=star_range.maximum,
        error_type="unsplittable_range",
        error_message=(
            f"star range contains {page.total_count} results and cannot be split further"
        ),
        response_status=page.request.status_code,
        retry_count=page.request.retry_count,
        duration_ms=page.request.duration_ms,
    )


def _request_page(
    client: DiscoveryClient,
    star_range: StarRange,
    page_number: int,
    run_id: int | None,
) -> SearchRepositoriesPage | FailedRange:
    try:
        page = client.search_repositories(
            star_range.topic,
            min_stars=star_range.minimum,
            max_stars=star_range.maximum,
            page=page_number,
            per_page=SEARCH_PAGE_SIZE,
        )
    except GitHubClientError as error:
        failure = _failure_from_error(star_range, error)
        logger.warning(
            "discovery_search_failed",
            extra={
                "run_id": run_id,
                "topic": star_range.topic,
                "min_stars": star_range.minimum,
                "max_stars": star_range.maximum,
                "page": page_number,
                "response_status": failure.response_status,
                "retry_count": failure.retry_count,
                "duration_ms": failure.duration_ms,
                "error_type": failure.error_type,
            },
        )
        return failure
    logger.info(
        "discovery_search",
        extra={
            "run_id": run_id,
            "topic": star_range.topic,
            "min_stars": star_range.minimum,
            "max_stars": star_range.maximum,
            "page": page_number,
            "response_status": page.request.status_code,
            "retry_count": page.request.retry_count,
            "duration_ms": page.request.duration_ms,
        },
    )
    if page.incomplete_results:
        return _incomplete_failure(star_range, page)
    return page


def _search_range(
    client: DiscoveryClient,
    star_range: StarRange,
    run_id: int | None,
) -> SearchResult:
    first = _request_page(client, star_range, 1, run_id)
    if isinstance(first, FailedRange):
        return SearchResult((), (first,), 0)

    if first.total_count > SEARCH_RESULT_LIMIT:
        maximum = star_range.maximum
        if maximum is None:
            if not first.repositories:
                failure = FailedRange(
                    topic=star_range.topic,
                    minimum=star_range.minimum,
                    maximum=None,
                    error_type="invalid_search_result",
                    error_message="overfull Search response did not include a maximum star value",
                    response_status=first.request.status_code,
                    retry_count=first.request.retry_count,
                    duration_ms=first.request.duration_ms,
                )
                return SearchResult((), (failure,), 0)
            maximum = max(repository.stars for repository in first.repositories)

        if maximum <= star_range.minimum:
            bounded_range = StarRange(star_range.topic, star_range.minimum, maximum)
            return SearchResult((), (_overfull_failure(bounded_range, first),), 0)

        midpoint = (star_range.minimum + maximum) // 2
        lower_result = _search_range(
            client,
            StarRange(star_range.topic, star_range.minimum, midpoint),
            run_id,
        )
        upper_result = _search_range(
            client,
            StarRange(star_range.topic, midpoint + 1, maximum),
            run_id,
        )
        return SearchResult(
            repositories=lower_result.repositories + upper_result.repositories,
            failed_ranges=lower_result.failed_ranges + upper_result.failed_ranges,
            successful_range_count=(
                lower_result.successful_range_count + upper_result.successful_range_count
            ),
        )

    repositories = list(first.repositories)
    page_count = (first.total_count + SEARCH_PAGE_SIZE - 1) // SEARCH_PAGE_SIZE
    for page_number in range(2, page_count + 1):
        page = _request_page(client, star_range, page_number, run_id)
        if isinstance(page, FailedRange):
            return SearchResult((), (page,), 0)
        repositories.extend(page.repositories)

    return SearchResult(tuple(repositories), (), 1)


def search_repositories(
    client: DiscoveryClient,
    ranges: Sequence[StarRange],
    *,
    run_id: int | None = None,
) -> SearchResult:
    """Search all requested ranges, retaining retryable descriptions for failures."""
    repositories: list[Repository] = []
    failures: list[FailedRange] = []
    successful_range_count = 0
    for star_range in ranges:
        result = _search_range(client, star_range, run_id)
        repositories.extend(result.repositories)
        failures.extend(result.failed_ranges)
        successful_range_count += result.successful_range_count
    return SearchResult(tuple(repositories), tuple(failures), successful_range_count)


def _active_topics(connection: Connection[tuple[object, ...]]) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT topics.name, topics.id
        FROM topics
        WHERE topics.active
          AND EXISTS (
              SELECT 1
              FROM category_topics
              JOIN categories ON categories.id = category_topics.category_id
              WHERE category_topics.topic_id = topics.id
                AND category_topics.active
                AND categories.active
          )
        ORDER BY topics.name
        """
    ).fetchall()
    return {cast(str, row[0]): cast(int, row[1]) for row in rows}


def _retry_ranges(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    active_topics: set[str],
) -> list[StarRange]:
    row = connection.execute(
        "SELECT failed_ranges FROM discovery_runs WHERE id = %s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise DiscoveryConfigurationError(f"discovery run {run_id} does not exist")
    raw_ranges = row[0]
    if not isinstance(raw_ranges, list):
        raise DiscoveryConfigurationError(f"discovery run {run_id} has invalid failed ranges")

    ranges: list[StarRange] = []
    for raw in raw_ranges:
        if not isinstance(raw, dict):
            raise DiscoveryConfigurationError(f"discovery run {run_id} has invalid failed ranges")
        topic = raw.get("topic")
        minimum = raw.get("min_stars")
        maximum = raw.get("max_stars")
        if (
            not isinstance(topic, str)
            or type(minimum) is not int
            or (maximum is not None and type(maximum) is not int)
        ):
            raise DiscoveryConfigurationError(f"discovery run {run_id} has invalid failed ranges")
        if topic in active_topics:
            ranges.append(StarRange(topic, minimum, maximum))
    if not ranges:
        raise DiscoveryConfigurationError(
            f"discovery run {run_id} has no failed ranges for active topics"
        )
    return ranges


def _eligible(repository: Repository, active_topics: set[str]) -> bool:
    return (
        repository.visibility.casefold() == "public"
        and not repository.fork
        and not repository.archived
        and repository.stars >= MINIMUM_STARS
        and bool(active_topics.intersection(repository.topics))
    )


def _upsert_repository(
    connection: Connection[tuple[object, ...]],
    repository: Repository,
    discovered_at: datetime,
) -> tuple[int, bool]:
    inserted = connection.execute(
        """
        INSERT INTO repositories (
            github_id, owner, name, description, github_url, language,
            current_stars, status, discovered_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, 'bootstrap_pending', %s)
        ON CONFLICT (github_id) DO NOTHING
        RETURNING id
        """,
        (
            repository.github_id,
            repository.owner,
            repository.name,
            repository.description,
            repository.github_url,
            repository.language,
            repository.stars,
            discovered_at,
        ),
    ).fetchone()
    if inserted is not None:
        return cast(int, inserted[0]), True

    updated = connection.execute(
        """
        UPDATE repositories
        SET owner = %s,
            name = %s,
            description = %s,
            github_url = %s,
            language = %s,
            current_stars = %s,
            status = CASE WHEN status = 'inactive' THEN 'active' ELSE status END,
            updated_at = CURRENT_TIMESTAMP
        WHERE github_id = %s
          AND (owner, name, description, github_url, language, current_stars, status)
              IS DISTINCT FROM
              (%s, %s, %s, %s, %s, %s,
               CASE WHEN status = 'inactive' THEN 'active' ELSE status END)
        RETURNING id
        """,
        (
            repository.owner,
            repository.name,
            repository.description,
            repository.github_url,
            repository.language,
            repository.stars,
            repository.github_id,
            repository.owner,
            repository.name,
            repository.description,
            repository.github_url,
            repository.language,
            repository.stars,
        ),
    ).fetchone()
    if updated is not None:
        return cast(int, updated[0]), False
    existing = connection.execute(
        "SELECT id FROM repositories WHERE github_id = %s",
        (repository.github_id,),
    ).fetchone()
    if existing is None:
        raise RuntimeError(f"repository upsert did not return an id: {repository.github_id}")
    return cast(int, existing[0]), False


def _sync_repository_topics(
    connection: Connection[tuple[object, ...]],
    repository_id: int,
    topic_ids: Sequence[int],
) -> None:
    connection.execute(
        """
        UPDATE repository_topics
        SET active = false, updated_at = CURRENT_TIMESTAMP
        WHERE repository_id = %s
          AND active
          AND NOT (topic_id = ANY(%s))
        """,
        (repository_id, list(topic_ids)),
    )
    for topic_id in topic_ids:
        connection.execute(
            """
            INSERT INTO repository_topics (repository_id, topic_id)
            VALUES (%s, %s)
            ON CONFLICT (repository_id, topic_id) DO UPDATE
            SET active = true, updated_at = CURRENT_TIMESTAMP
            WHERE NOT repository_topics.active
            """,
            (repository_id, topic_id),
        )


def _store_repositories(
    connection: Connection[tuple[object, ...]],
    repositories: Sequence[Repository],
    active_topics: dict[str, int],
    discovered_at: datetime,
    run_id: int,
) -> tuple[int, int]:
    by_github_id: dict[int, Repository] = {}
    repository_topics: dict[int, set[str]] = {}
    active_topic_names = set(active_topics)
    for repository in repositories:
        if not _eligible(repository, active_topic_names):
            continue
        by_github_id[repository.github_id] = repository
        repository_topics.setdefault(repository.github_id, set()).update(
            active_topic_names.intersection(repository.topics)
        )

    added_count = 0
    for github_id in sorted(by_github_id):
        repository = by_github_id[github_id]
        repository_id, added = _upsert_repository(connection, repository, discovered_at)
        added_count += int(added)
        topic_ids = sorted(active_topics[name] for name in repository_topics[github_id])
        _sync_repository_topics(connection, repository_id, topic_ids)
        logger.info(
            "discovery_repository",
            extra={
                "run_id": run_id,
                "repository_id": repository_id,
                "github_id": github_id,
            },
        )
    return len(by_github_id), added_count


def _finish_failed_run(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    finished_at: datetime,
) -> None:
    connection.rollback()
    connection.execute(
        """
        UPDATE discovery_runs
        SET status = 'FAILED', finished_at = %s, updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (finished_at, run_id),
    )
    connection.commit()


def run_discovery(
    database_url: str,
    client: DiscoveryClient,
    *,
    retry_run_id: int | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> DiscoveryRunResult:
    """Execute one locked discovery run and commit its auditable result."""
    with connect_database(database_url) as connection:
        lock_row = connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (DISCOVERY_LOCK_ID,),
        ).fetchone()
        if lock_row != (True,):
            raise DiscoveryAlreadyRunningError("another discovery run is already active")

        run_id: int | None = None
        try:
            active_topics = _active_topics(connection)
            if not active_topics:
                raise DiscoveryConfigurationError("no active discovery topics are configured")
            ranges = (
                _retry_ranges(connection, retry_run_id, set(active_topics))
                if retry_run_id is not None
                else [StarRange(topic, MINIMUM_STARS, None) for topic in active_topics]
            )

            started_at = clock().astimezone(UTC)
            row = connection.execute(
                """
                INSERT INTO discovery_runs (started_at, status)
                VALUES (%s, 'RUNNING')
                RETURNING id
                """,
                (started_at,),
            ).fetchone()
            if row is None:
                raise RuntimeError("discovery run insert did not return an id")
            run_id = cast(int, row[0])
            connection.commit()

            result = search_repositories(client, ranges, run_id=run_id)
            discovered_count, added_count = _store_repositories(
                connection,
                result.repositories,
                active_topics,
                started_at,
                run_id,
            )
            if result.failed_ranges:
                status = "PARTIAL" if result.successful_range_count else "FAILED"
            else:
                status = "COMPLETED"
            finished_at = clock().astimezone(UTC)
            connection.execute(
                """
                UPDATE discovery_runs
                SET finished_at = %s,
                    discovered_count = %s,
                    added_count = %s,
                    status = %s,
                    failed_ranges = %s,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (
                    finished_at,
                    discovered_count,
                    added_count,
                    status,
                    Jsonb([failure.as_json() for failure in result.failed_ranges]),
                    run_id,
                ),
            )
            connection.commit()
            logger.info(
                "discovery_run_finished",
                extra={
                    "run_id": run_id,
                    "status": status,
                    "discovered_count": discovered_count,
                    "added_count": added_count,
                    "failed_range_count": len(result.failed_ranges),
                },
            )
            return DiscoveryRunResult(
                run_id=run_id,
                status=status,
                discovered_count=discovered_count,
                added_count=added_count,
                failed_ranges=result.failed_ranges,
            )
        except Exception as error:
            if run_id is not None:
                _finish_failed_run(connection, run_id, clock().astimezone(UTC))
            logger.exception(
                "discovery_run_failed",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )
            raise
        finally:
            connection.execute("SELECT pg_advisory_unlock(%s)", (DISCOVERY_LOCK_ID,))
            connection.commit()


def main(argv: Sequence[str] | None = None) -> int:
    """Run daily discovery, optionally retrying one prior run's failed ranges."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Discover eligible GitHub repositories")
    parser.add_argument("--retry-run", type=int, default=None)
    arguments = parser.parse_args(argv)
    try:
        settings = get_settings()
        result = run_discovery(
            str(settings.database_url),
            create_github_client(settings),
            retry_run_id=arguments.retry_run,
        )
    except Exception as error:
        logger.exception(
            "discovery_job_failed",
            extra={"error_type": type(error).__name__},
        )
        return 1
    print(
        f"Discovery run {result.run_id} {result.status}: "
        f"{result.discovered_count} discovered, {result.added_count} added, "
        f"{len(result.failed_ranges)} failed ranges"
    )
    return 0 if result.status == "COMPLETED" else 1

