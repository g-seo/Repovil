"""Historical star bootstrap for newly discovered repositories.

GitHub history reports created stars in provider-defined daily buckets. It cannot
represent unstars and its day boundaries are not guaranteed to be UTC, so every
derived value in this module is explicitly estimated.
"""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol, cast

from psycopg import Connection

from repovil.db import connect_database
from repovil.github_client import (
    GitHubClientError,
    RepositoryStats,
    RequestMetadata,
    StarHistoryPage,
    StarHistoryWeek,
)
from repovil.observability import configure_logging
from repovil.settings import get_settings
from repovil.worker import create_github_client

logger = logging.getLogger(__name__)

BOOTSTRAP_LOCK_ID = 3_861_435_965_787_790_205
BOOTSTRAP_HISTORY_DAYS = 30
HISTORY_PAGE_SIZE = 30
BootstrapPeriod = Literal["7d", "30d"]


class BootstrapAlreadyRunningError(RuntimeError):
    """Raised when another bootstrap process owns the database lock."""


class BootstrapHistoryError(ValueError):
    """Raised when history buckets cannot be mapped without ambiguity."""


class BootstrapClient(Protocol):
    """Narrow GitHubClient surface used by the bootstrap worker."""

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats: ...

    def get_star_history(
        self,
        owner: str,
        name: str,
        *,
        page: int = 1,
        per_page: int = 30,
    ) -> StarHistoryPage: ...


@dataclass(frozen=True, slots=True)
class PendingRepository:
    """A repository needing initial bootstrap or a bounded history refresh."""

    repository_id: int
    owner: str
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class BootstrapBaseline:
    """A recomputable estimated baseline; never valid for the 24h period."""

    period: BootstrapPeriod
    target_time: datetime
    star_count: int
    star_gain: int
    is_estimated: bool = True


@dataclass(frozen=True, slots=True)
class BootstrapFailure:
    """A retryable repository bootstrap failure."""

    repository_id: int
    error_type: str
    error_message: str
    response_status: int | None
    retry_count: int
    duration_ms: int | None


@dataclass(frozen=True, slots=True)
class BootstrapRepositoryResult:
    """One successful fetch and any valid estimated baseline candidates."""

    repository_id: int
    stored_day_count: int
    baselines: tuple[BootstrapBaseline, ...]


@dataclass(frozen=True, slots=True)
class BootstrapRunResult:
    """Summary of a locked pass over repositories pending bootstrap."""

    processed_count: int
    success_count: int
    failed_count: int
    repositories: tuple[BootstrapRepositoryResult, ...]
    failures: tuple[BootstrapFailure, ...]


def star_history_days(weeks: Sequence[StarHistoryWeek]) -> dict[date, int]:
    """Map provider week/day buckets to date labels without treating them as snapshots."""
    daily: dict[date, int] = {}
    for week in weeks:
        try:
            week_start = datetime.fromtimestamp(week.week, tz=UTC).date()
        except (OSError, OverflowError, ValueError) as error:
            raise BootstrapHistoryError("star history contains an invalid week epoch") from error
        for offset, stars_created in enumerate(week.days):
            bucket_date = week_start + timedelta(days=offset)
            if bucket_date in daily:
                raise BootstrapHistoryError(
                    f"star history contains a duplicate date bucket: {bucket_date.isoformat()}"
                )
            daily[bucket_date] = stars_created
    return daily


def calculate_bootstrap_baseline(
    current_stars: int,
    measured_at: datetime,
    daily_stars_created: Mapping[date, int],
    period: str,
) -> BootstrapBaseline | None:
    """Estimate a 7d/30d baseline, returning None for incomplete or invalid input."""
    if period == "7d":
        days = 7
    elif period == "30d":
        days = 30
    else:
        raise ValueError("bootstrap baselines are only valid for 7d and 30d")
    if current_stars < 0:
        raise ValueError("current_stars must be non-negative")
    if measured_at.tzinfo is None or measured_at.utcoffset() is None:
        raise ValueError("measured_at must be timezone-aware")

    measured_at = measured_at.astimezone(UTC)
    target_time = measured_at - timedelta(days=days)
    required_dates = tuple(
        target_time.date() + timedelta(days=offset) for offset in range(1, days + 1)
    )
    counts: list[int] = []
    for required_date in required_dates:
        value = daily_stars_created.get(required_date)
        if type(value) is not int or value < 0:
            return None
        counts.append(value)

    star_gain = sum(counts)
    baseline = current_stars - star_gain
    if baseline < 0:
        return None
    return BootstrapBaseline(
        period=cast(BootstrapPeriod, period),
        target_time=target_time,
        star_count=baseline,
        star_gain=star_gain,
    )


def calculate_bootstrap_baselines(
    current_stars: int,
    measured_at: datetime,
    daily_stars_created: Mapping[date, int],
) -> tuple[BootstrapBaseline, ...]:
    """Return only valid candidates while keeping 7d and 30d independently usable."""
    return tuple(
        baseline
        for period in ("7d", "30d")
        if (
            baseline := calculate_bootstrap_baseline(
                current_stars,
                measured_at,
                daily_stars_created,
                period,
            )
        )
        is not None
    )


def _pending_repositories(
    connection: Connection[tuple[object, ...]],
    *,
    refresh_active: bool,
    refresh_cutoff: datetime,
) -> tuple[PendingRepository, ...]:
    rows = connection.execute(
        """
        SELECT id, owner, name, status
        FROM repositories
        WHERE status = 'bootstrap_pending'
           OR (%s AND status = 'active' AND tracking_started_at >= %s)
        ORDER BY id
        """,
        (refresh_active, refresh_cutoff),
    ).fetchall()
    return tuple(
        PendingRepository(
            cast(int, row[0]),
            cast(str, row[1]),
            cast(str, row[2]),
            cast(str, row[3]),
        )
        for row in rows
    )


def _mark_attempt(
    connection: Connection[tuple[object, ...]],
    repository_id: int,
    attempted_at: datetime,
    *,
    refresh_active: bool,
    refresh_cutoff: datetime,
) -> bool:
    row = connection.execute(
        """
        UPDATE repositories
        SET bootstrap_attempt_count = bootstrap_attempt_count + 1,
            bootstrap_last_attempted_at = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
          AND (
              status = 'bootstrap_pending'
              OR (%s AND status = 'active' AND tracking_started_at >= %s)
          )
        RETURNING id
        """,
        (attempted_at, repository_id, refresh_active, refresh_cutoff),
    ).fetchone()
    connection.commit()
    return row is not None


def _store_failure(
    connection: Connection[tuple[object, ...]],
    failure: BootstrapFailure,
) -> None:
    connection.execute(
        """
        UPDATE repositories
        SET bootstrap_error_type = %s,
            bootstrap_error_message = %s,
            bootstrap_response_status = %s,
            bootstrap_retry_count = %s,
            bootstrap_duration_ms = %s,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s AND status = 'bootstrap_pending'
        """,
        (
            failure.error_type,
            failure.error_message,
            failure.response_status,
            failure.retry_count,
            failure.duration_ms,
            failure.repository_id,
        ),
    )
    connection.commit()


def _complete_repository(
    connection: Connection[tuple[object, ...]],
    repository_id: int,
    current_stars: int | None,
    fetched_at: datetime,
    daily_stars_created: Mapping[date, int],
) -> bool:
    status_row = connection.execute(
        "SELECT status FROM repositories WHERE id = %s FOR UPDATE",
        (repository_id,),
    ).fetchone()
    if status_row is None or status_row[0] not in {"bootstrap_pending", "active"}:
        connection.rollback()
        return False
    status = status_row[0]

    earliest = fetched_at.date() - timedelta(days=BOOTSTRAP_HISTORY_DAYS - 1)
    recent_days = {
        bucket_date: stars_created
        for bucket_date, stars_created in daily_stars_created.items()
        if earliest <= bucket_date <= fetched_at.date()
    }
    for bucket_date in sorted(recent_days):
        connection.execute(
            """
            INSERT INTO bootstrap_star_history (
                repository_id, date, stars_created, fetched_at
            )
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (repository_id, date) DO NOTHING
            """,
            (repository_id, bucket_date, recent_days[bucket_date], fetched_at),
        )
    if status == "active":
        connection.commit()
        return True

    if current_stars is None:
        raise RuntimeError("initial bootstrap requires a current star count")
    connection.execute(
        """
        UPDATE repositories
        SET current_stars = %s,
            status = 'active',
            tracking_started_at = COALESCE(tracking_started_at, %s),
            bootstrap_completed_at = %s,
            bootstrap_error_type = NULL,
            bootstrap_error_message = NULL,
            bootstrap_response_status = NULL,
            bootstrap_retry_count = 0,
            bootstrap_duration_ms = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
        """,
        (current_stars, fetched_at, fetched_at, repository_id),
    )
    connection.commit()
    return True


def _failure(
    repository_id: int,
    error: Exception,
    metadata: RequestMetadata,
) -> BootstrapFailure:
    return BootstrapFailure(
        repository_id=repository_id,
        error_type=type(error).__name__,
        error_message=str(error),
        response_status=metadata.status_code,
        retry_count=metadata.retry_count,
        duration_ms=metadata.duration_ms,
    )


def _utc(clock: Callable[[], datetime]) -> datetime:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("bootstrap clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


def run_bootstrap(
    database_url: str,
    client: BootstrapClient,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    refresh_active: bool = False,
) -> BootstrapRunResult:
    """Bootstrap pending repositories and optionally extend recent source history."""
    with connect_database(database_url) as connection:
        lock_row = connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (BOOTSTRAP_LOCK_ID,),
        ).fetchone()
        if lock_row != (True,):
            raise BootstrapAlreadyRunningError("another bootstrap worker is already active")

        successes: list[BootstrapRepositoryResult] = []
        failures: list[BootstrapFailure] = []
        processed_count = 0
        try:
            refresh_cutoff = _utc(clock) - timedelta(days=BOOTSTRAP_HISTORY_DAYS)
            repositories = _pending_repositories(
                connection,
                refresh_active=refresh_active,
                refresh_cutoff=refresh_cutoff,
            )
            connection.commit()
            for repository in repositories:
                attempted_at = _utc(clock)
                if not _mark_attempt(
                    connection,
                    repository.repository_id,
                    attempted_at,
                    refresh_active=refresh_active,
                    refresh_cutoff=refresh_cutoff,
                ):
                    continue
                processed_count += 1
                try:
                    stats = (
                        client.get_repository_stats(repository.owner, repository.name)
                        if repository.status == "bootstrap_pending"
                        else None
                    )
                    history = client.get_star_history(
                        repository.owner,
                        repository.name,
                        page=1,
                        per_page=HISTORY_PAGE_SIZE,
                    )
                    fetched_at = _utc(clock)
                    daily = star_history_days(history.weeks)
                except GitHubClientError as error:
                    failure = _failure(repository.repository_id, error, error.request)
                    _store_failure(connection, failure)
                    failures.append(failure)
                    logger.warning(
                        "bootstrap_repository_failed",
                        extra={
                            "repository_id": repository.repository_id,
                            "response_status": failure.response_status,
                            "retry_count": failure.retry_count,
                            "duration_ms": failure.duration_ms,
                            "error_type": failure.error_type,
                        },
                    )
                    continue
                except BootstrapHistoryError as error:
                    failure = _failure(repository.repository_id, error, history.request)
                    _store_failure(connection, failure)
                    failures.append(failure)
                    logger.warning(
                        "bootstrap_repository_failed",
                        extra={
                            "repository_id": repository.repository_id,
                            "response_status": failure.response_status,
                            "retry_count": failure.retry_count,
                            "duration_ms": failure.duration_ms,
                            "error_type": failure.error_type,
                        },
                    )
                    continue

                baselines = (
                    calculate_bootstrap_baselines(stats.star_count, fetched_at, daily)
                    if stats is not None
                    else ()
                )
                completed = _complete_repository(
                    connection,
                    repository.repository_id,
                    stats.star_count if stats is not None else None,
                    fetched_at,
                    daily,
                )
                if not completed:
                    continue
                earliest = fetched_at.date() - timedelta(days=BOOTSTRAP_HISTORY_DAYS - 1)
                stored_day_count = sum(
                    earliest <= bucket_date <= fetched_at.date() for bucket_date in daily
                )
                successes.append(
                    BootstrapRepositoryResult(
                        repository_id=repository.repository_id,
                        stored_day_count=stored_day_count,
                        baselines=baselines,
                    )
                )
                logger.info(
                    "bootstrap_repository_completed",
                    extra={
                        "repository_id": repository.repository_id,
                        "response_status": history.request.status_code,
                        "retry_count": history.request.retry_count,
                        "duration_ms": history.request.duration_ms,
                        "stored_day_count": stored_day_count,
                        "baseline_periods": [baseline.period for baseline in baselines],
                    },
                )
        finally:
            connection.rollback()
            connection.execute("SELECT pg_advisory_unlock(%s)", (BOOTSTRAP_LOCK_ID,))
            connection.commit()

    return BootstrapRunResult(
        processed_count=processed_count,
        success_count=len(successes),
        failed_count=len(failures),
        repositories=tuple(successes),
        failures=tuple(failures),
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Run historical bootstrap, optionally refreshing recent active repositories."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Bootstrap repository star history")
    parser.add_argument(
        "--refresh-active",
        action="store_true",
        help="append source-history dates for active repositories under 30 days old",
    )
    arguments = parser.parse_args(argv)
    try:
        settings = get_settings()
        result = run_bootstrap(
            str(settings.database_url),
            create_github_client(settings),
            refresh_active=arguments.refresh_active,
        )
    except Exception as error:
        logger.exception(
            "bootstrap_job_failed",
            extra={"error_type": type(error).__name__},
        )
        return 1
    print(
        f"Bootstrap processed {result.processed_count}: "
        f"{result.success_count} completed, {result.failed_count} failed"
    )
    return int(result.failed_count > 0)
