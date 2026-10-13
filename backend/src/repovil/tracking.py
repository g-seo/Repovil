"""Six-hour repository tracking and immutable star snapshot collection."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast

from psycopg import Connection

from repovil.db import connect_database
from repovil.github_client import (
    GitHubAuthenticationError,
    GitHubClientError,
    GitHubNotFoundError,
    Repository,
    RepositoryResult,
    RepositoryStats,
    RequestMetadata,
)
from repovil.observability import configure_logging
from repovil.ranking import publish_rankings
from repovil.settings import get_settings
from repovil.worker import create_github_client

logger = logging.getLogger(__name__)

TRACKING_LOCK_ID = 7_705_564_582_714_604_993
TRACKING_INTERVAL_HOURS = 6
MINIMUM_STARS = 200


class TrackingAlreadyRunningError(RuntimeError):
    """Raised when another tracking process owns the database lock."""


class RepositoryIdentityMismatchError(RuntimeError):
    """Raised when a saved owner/name resolves to a different GitHub repository."""


class TrackingClient(Protocol):
    """Narrow GitHubClient surface used by the tracking worker."""

    def get_repository(self, owner: str, name: str) -> RepositoryResult: ...

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats: ...


@dataclass(frozen=True, slots=True)
class TrackingTarget:
    """One repository fixed into a tracking run at its start."""

    repository_id: int
    github_id: int
    owner: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class TrackingRunResult:
    """Committed tracking run summary."""

    run_id: int
    scheduled_at: datetime
    status: str
    total_count: int
    success_count: int
    failed_count: int
    skipped_count: int
    published_at: datetime | None
    ranking_count: int
    already_finished: bool = False


def schedule_slot(value: datetime) -> datetime:
    """Return the containing six-hour UTC schedule slot."""
    value = _as_utc(value, label="schedule time")
    return value.replace(
        hour=value.hour - value.hour % TRACKING_INTERVAL_HOURS,
        minute=0,
        second=0,
        microsecond=0,
    )


def _validate_schedule_slot(value: datetime) -> datetime:
    value = _as_utc(value, label="scheduled_at")
    if value != schedule_slot(value):
        raise ValueError("scheduled_at must be aligned to a six-hour UTC slot")
    return value


def _as_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


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


def _start_or_load_run(
    connection: Connection[tuple[object, ...]],
    scheduled_at: datetime,
    started_at: datetime,
) -> tuple[int, bool]:
    inserted = connection.execute(
        """
        INSERT INTO tracking_runs (scheduled_at, started_at, status)
        VALUES (%s, %s, 'RUNNING')
        ON CONFLICT (scheduled_at) DO NOTHING
        RETURNING id
        """,
        (scheduled_at, started_at),
    ).fetchone()
    if inserted is None:
        existing = connection.execute(
            "SELECT id, status FROM tracking_runs WHERE scheduled_at = %s",
            (scheduled_at,),
        ).fetchone()
        if existing is None:
            raise RuntimeError("tracking run conflict did not return the existing run")
        connection.commit()
        return cast(int, existing[0]), cast(str, existing[1]) != "RUNNING"

    run_id = cast(int, inserted[0])
    connection.execute(
        """
        INSERT INTO tracking_run_items (tracking_run_id, repository_id)
        SELECT %s, id
        FROM repositories
        WHERE status = 'active'
        ORDER BY id
        """,
        (run_id,),
    )
    connection.execute(
        """
        UPDATE tracking_runs
        SET total_count = (
                SELECT count(*) FROM tracking_run_items WHERE tracking_run_id = %s
            ),
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (run_id, run_id),
    )
    connection.commit()
    return run_id, False


def _run_result(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    *,
    already_finished: bool = False,
) -> TrackingRunResult:
    row = connection.execute(
        """
        SELECT scheduled_at, status, total_count, success_count, failed_count, skipped_count,
               published_at,
               (SELECT count(*) FROM rankings WHERE tracking_run_id = tracking_runs.id)
        FROM tracking_runs
        WHERE id = %s
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"tracking run {run_id} does not exist")
    return TrackingRunResult(
        run_id=run_id,
        scheduled_at=cast(datetime, row[0]).astimezone(UTC),
        status=cast(str, row[1]),
        total_count=cast(int, row[2]),
        success_count=cast(int, row[3]),
        failed_count=cast(int, row[4]),
        skipped_count=cast(int, row[5]),
        published_at=(cast(datetime, row[6]).astimezone(UTC) if row[6] is not None else None),
        ranking_count=cast(int, row[7]),
        already_finished=already_finished,
    )


def _pending_targets(
    connection: Connection[tuple[object, ...]],
    run_id: int,
) -> tuple[TrackingTarget, ...]:
    rows = connection.execute(
        """
        SELECT repositories.id, repositories.github_id, repositories.owner,
               repositories.name, repositories.status
        FROM tracking_run_items
        JOIN repositories ON repositories.id = tracking_run_items.repository_id
        WHERE tracking_run_items.tracking_run_id = %s
          AND tracking_run_items.status IS NULL
        ORDER BY repositories.id
        """,
        (run_id,),
    ).fetchall()
    return tuple(
        TrackingTarget(
            repository_id=cast(int, row[0]),
            github_id=cast(int, row[1]),
            owner=cast(str, row[2]),
            name=cast(str, row[3]),
            status=cast(str, row[4]),
        )
        for row in rows
    )


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


def _metadata_ineligibility(repository: Repository, active_topics: set[str]) -> str | None:
    if repository.visibility.casefold() != "public":
        return "repository is not public"
    if repository.fork:
        return "repository is a fork"
    if repository.archived:
        return "repository is archived"
    if not active_topics.intersection(repository.topics):
        return "repository has no active configured topic"
    return None


def _combined_request(*requests: RequestMetadata) -> tuple[int | None, int, int]:
    return (
        requests[-1].status_code,
        sum(request.retry_count for request in requests),
        sum(request.duration_ms for request in requests),
    )


def _set_item_result(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    repository_id: int,
    status: str,
    *,
    error_type: str | None = None,
    error_message: str | None = None,
    response_status: int | None = None,
    retry_count: int = 0,
    duration_ms: int | None = None,
) -> None:
    connection.execute(
        """
        UPDATE tracking_run_items
        SET status = %s,
            error_type = %s,
            error_message = %s,
            response_status = %s,
            retry_count = %s,
            duration_ms = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE tracking_run_id = %s
          AND repository_id = %s
          AND status IS NULL
        """,
        (
            status,
            error_type,
            error_message,
            response_status,
            retry_count,
            duration_ms,
            run_id,
            repository_id,
        ),
    )


def _store_failed(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    target: TrackingTarget,
    error: Exception,
    requests: Sequence[RequestMetadata],
) -> None:
    response_status, retry_count, duration_ms = _combined_request(*requests)
    _set_item_result(
        connection,
        run_id,
        target.repository_id,
        "failed",
        error_type=type(error).__name__,
        error_message=str(error),
        response_status=response_status,
        retry_count=retry_count,
        duration_ms=duration_ms,
    )
    connection.commit()
    logger.warning(
        "tracking_repository_failed",
        extra={
            "run_id": run_id,
            "repository_id": target.repository_id,
            "response_status": response_status,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
            "error_type": type(error).__name__,
        },
    )


def _store_skipped_without_metadata(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    target: TrackingTarget,
    *,
    reason_type: str,
    reason: str,
    request: RequestMetadata | None = None,
) -> None:
    if target.status == "active":
        connection.execute(
            """
            UPDATE repositories
            SET status = 'inactive', updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            """,
            (target.repository_id,),
        )
    _set_item_result(
        connection,
        run_id,
        target.repository_id,
        "skipped",
        error_type=reason_type,
        error_message=reason,
        response_status=request.status_code if request else None,
        retry_count=request.retry_count if request else 0,
        duration_ms=request.duration_ms if request else None,
    )
    connection.commit()
    logger.info(
        "tracking_repository_skipped",
        extra={
            "run_id": run_id,
            "repository_id": target.repository_id,
            "response_status": request.status_code if request else None,
            "retry_count": request.retry_count if request else 0,
            "duration_ms": request.duration_ms if request else None,
            "reason_type": reason_type,
        },
    )


def _update_repository(
    connection: Connection[tuple[object, ...]],
    target: TrackingTarget,
    repository: Repository,
    star_count: int,
    status: str,
    topic_ids: Sequence[int],
) -> None:
    connection.execute(
        """
        UPDATE repositories
        SET owner = %s,
            name = %s,
            description = %s,
            github_url = %s,
            language = %s,
            current_stars = %s,
            status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            repository.owner,
            repository.name,
            repository.description,
            repository.github_url,
            repository.language,
            star_count,
            status,
            target.repository_id,
        ),
    )
    _sync_repository_topics(connection, target.repository_id, topic_ids)


def _store_skipped_metadata(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    target: TrackingTarget,
    repository: Repository,
    star_count: int,
    topic_ids: Sequence[int],
    reason: str,
    requests: Sequence[RequestMetadata],
) -> None:
    response_status, retry_count, duration_ms = _combined_request(*requests)
    _update_repository(
        connection,
        target,
        repository,
        star_count,
        "inactive",
        topic_ids,
    )
    _set_item_result(
        connection,
        run_id,
        target.repository_id,
        "skipped",
        error_type="ineligible",
        error_message=reason,
        response_status=response_status,
        retry_count=retry_count,
        duration_ms=duration_ms,
    )
    connection.commit()
    logger.info(
        "tracking_repository_skipped",
        extra={
            "run_id": run_id,
            "repository_id": target.repository_id,
            "response_status": response_status,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
            "reason_type": "ineligible",
        },
    )


def _store_success(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    target: TrackingTarget,
    repository: Repository,
    stats: RepositoryStats,
    captured_at: datetime,
    topic_ids: Sequence[int],
    metadata_request: RequestMetadata,
) -> None:
    response_status, retry_count, duration_ms = _combined_request(
        metadata_request,
        stats.request,
    )
    _update_repository(
        connection,
        target,
        repository,
        stats.star_count,
        "active",
        topic_ids,
    )
    connection.execute(
        """
        INSERT INTO star_snapshots (
            tracking_run_id, repository_id, captured_at, star_count
        )
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (tracking_run_id, repository_id) DO NOTHING
        """,
        (run_id, target.repository_id, captured_at, stats.star_count),
    )
    _set_item_result(
        connection,
        run_id,
        target.repository_id,
        "success",
        response_status=response_status,
        retry_count=retry_count,
        duration_ms=duration_ms,
    )
    connection.commit()
    logger.info(
        "tracking_repository_succeeded",
        extra={
            "run_id": run_id,
            "repository_id": target.repository_id,
            "response_status": response_status,
            "retry_count": retry_count,
            "duration_ms": duration_ms,
            "captured_at": captured_at.isoformat(),
        },
    )


def _process_target(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    target: TrackingTarget,
    active_topics: dict[str, int],
    client: TrackingClient,
    clock: Callable[[], datetime],
) -> None:
    current_status_row = connection.execute(
        "SELECT status FROM repositories WHERE id = %s",
        (target.repository_id,),
    ).fetchone()
    if current_status_row is None:
        raise RuntimeError(f"tracking target repository {target.repository_id} does not exist")
    current_status = cast(str, current_status_row[0])
    if current_status != "active":
        _store_skipped_without_metadata(
            connection,
            run_id,
            target,
            reason_type="inactive",
            reason="repository became inactive after the run target list was fixed",
        )
        return

    try:
        metadata = client.get_repository(target.owner, target.name)
    except GitHubNotFoundError as error:
        _store_skipped_without_metadata(
            connection,
            run_id,
            target,
            reason_type=type(error).__name__,
            reason=str(error),
            request=error.request,
        )
        return
    except GitHubClientError as error:
        _store_failed(connection, run_id, target, error, (error.request,))
        if isinstance(error, GitHubAuthenticationError):
            raise
        raise _HandledFailure from error

    repository = metadata.repository
    if repository.github_id != target.github_id:
        mismatch_error = RepositoryIdentityMismatchError(
            f"saved github_id {target.github_id} resolved to {repository.github_id}"
        )
        _store_failed(connection, run_id, target, mismatch_error, (metadata.request,))
        raise _HandledFailure

    relevant_topics = sorted(set(repository.topics).intersection(active_topics))
    topic_ids = [active_topics[name] for name in relevant_topics]
    reason = _metadata_ineligibility(repository, set(active_topics))
    if reason is not None:
        _store_skipped_metadata(
            connection,
            run_id,
            target,
            repository,
            repository.stars,
            topic_ids,
            reason,
            (metadata.request,),
        )
        return

    try:
        stats = client.get_repository_stats(repository.owner, repository.name)
    except GitHubNotFoundError as error:
        _store_skipped_without_metadata(
            connection,
            run_id,
            target,
            reason_type=type(error).__name__,
            reason=str(error),
            request=error.request,
        )
        return
    except GitHubClientError as error:
        _store_failed(connection, run_id, target, error, (metadata.request, error.request))
        if isinstance(error, GitHubAuthenticationError):
            raise
        raise _HandledFailure from error

    if stats.star_count < MINIMUM_STARS:
        _store_skipped_metadata(
            connection,
            run_id,
            target,
            repository,
            stats.star_count,
            topic_ids,
            f"repository has fewer than {MINIMUM_STARS} stars",
            (metadata.request, stats.request),
        )
        return

    captured_at = _as_utc(clock(), label="tracking clock")
    _store_success(
        connection,
        run_id,
        target,
        repository,
        stats,
        captured_at,
        topic_ids,
        metadata.request,
    )


class _HandledFailure(Exception):
    """Internal signal that one failed item has already been persisted."""


def _fail_pending_items(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    error: Exception,
) -> None:
    connection.rollback()
    connection.execute(
        """
        UPDATE tracking_run_items
        SET status = 'failed',
            error_type = %s,
            error_message = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE tracking_run_id = %s AND status IS NULL
        """,
        (type(error).__name__, str(error), run_id),
    )
    connection.commit()


def _finish_run(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    finished_at: datetime,
    *,
    force_failed: bool = False,
) -> TrackingRunResult:
    counts = connection.execute(
        """
        SELECT count(*),
               count(*) FILTER (WHERE status = 'success'),
               count(*) FILTER (WHERE status = 'failed'),
               count(*) FILTER (WHERE status = 'skipped'),
               count(*) FILTER (WHERE status IS NULL)
        FROM tracking_run_items
        WHERE tracking_run_id = %s
        """,
        (run_id,),
    ).fetchone()
    if counts is None:
        raise RuntimeError("tracking run item counts were not returned")
    total_count, success_count, failed_count, skipped_count, pending_count = (
        cast(int, value) for value in counts
    )
    if pending_count:
        raise RuntimeError(f"tracking run {run_id} still has {pending_count} pending targets")
    if force_failed or (failed_count > 0 and success_count == 0):
        status = "FAILED"
    elif failed_count > 0:
        status = "PARTIAL"
    else:
        status = "COMPLETED"
    connection.execute(
        """
        UPDATE tracking_runs
        SET finished_at = %s,
            total_count = %s,
            success_count = %s,
            failed_count = %s,
            skipped_count = %s,
            status = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (
            finished_at,
            total_count,
            success_count,
            failed_count,
            skipped_count,
            status,
            run_id,
        ),
    )
    connection.commit()
    result = _run_result(connection, run_id)
    logger.info(
        "tracking_run_finished",
        extra={
            "run_id": run_id,
            "status": status,
            "total_count": total_count,
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_count": skipped_count,
        },
    )
    return result


def run_tracking(
    database_url: str,
    client: TrackingClient,
    *,
    scheduled_at: datetime | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> TrackingRunResult:
    """Track the target set fixed at the start of one UTC schedule slot."""
    initial_time = _as_utc(clock(), label="tracking clock")
    slot = (
        schedule_slot(initial_time)
        if scheduled_at is None
        else _validate_schedule_slot(scheduled_at)
    )
    with connect_database(database_url) as connection:
        lock_row = connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (TRACKING_LOCK_ID,),
        ).fetchone()
        if lock_row != (True,):
            raise TrackingAlreadyRunningError("another tracking worker is already active")

        run_id: int | None = None
        try:
            run_id, already_finished = _start_or_load_run(
                connection,
                slot,
                initial_time,
            )
            if already_finished:
                publish_rankings(
                    connection,
                    run_id,
                    _as_utc(clock(), label="tracking clock"),
                )
                connection.commit()
                return _run_result(connection, run_id, already_finished=True)

            active_topics = _active_topics(connection)
            targets = _pending_targets(connection, run_id)
            connection.commit()
            for target in targets:
                try:
                    _process_target(
                        connection,
                        run_id,
                        target,
                        active_topics,
                        client,
                        clock,
                    )
                except _HandledFailure:
                    continue
            _finish_run(
                connection,
                run_id,
                _as_utc(clock(), label="tracking clock"),
            )
            publish_rankings(
                connection,
                run_id,
                _as_utc(clock(), label="tracking clock"),
            )
            connection.commit()
            return _run_result(connection, run_id)
        except Exception as error:
            if run_id is not None:
                connection.rollback()
                status_row = connection.execute(
                    "SELECT status FROM tracking_runs WHERE id = %s",
                    (run_id,),
                ).fetchone()
                if status_row == ("RUNNING",):
                    _fail_pending_items(connection, run_id, error)
                    _finish_run(
                        connection,
                        run_id,
                        _as_utc(clock(), label="tracking clock"),
                        force_failed=True,
                    )
            logger.exception(
                "tracking_run_failed",
                extra={"run_id": run_id, "error_type": type(error).__name__},
            )
            raise
        finally:
            connection.rollback()
            connection.execute("SELECT pg_advisory_unlock(%s)", (TRACKING_LOCK_ID,))
            connection.commit()


def _parse_scheduled_at(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise argparse.ArgumentTypeError("scheduled time must be ISO 8601") from error
    try:
        return _validate_schedule_slot(parsed)
    except ValueError as error:
        raise argparse.ArgumentTypeError(str(error)) from error


def main(argv: Sequence[str] | None = None) -> int:
    """Run repository tracking for the current or explicitly supplied UTC slot."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Track active GitHub repositories")
    parser.add_argument("--scheduled-at", type=_parse_scheduled_at, default=None)
    arguments = parser.parse_args(argv)
    try:
        settings = get_settings()
        result = run_tracking(
            str(settings.database_url),
            create_github_client(settings),
            scheduled_at=arguments.scheduled_at,
        )
    except Exception as error:
        logger.exception(
            "tracking_job_failed",
            extra={"error_type": type(error).__name__},
        )
        return 1
    suffix = " (already finished)" if result.already_finished else ""
    publication = (
        f", published {result.ranking_count} rankings"
        if result.published_at is not None
        else ", not published"
    )
    print(
        f"Tracking run {result.run_id} {result.status}{suffix}: "
        f"{result.success_count} succeeded, {result.failed_count} failed, "
        f"{result.skipped_count} skipped{publication}"
    )
    return 0 if result.status == "COMPLETED" else 1
