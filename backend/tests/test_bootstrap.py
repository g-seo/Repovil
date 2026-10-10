from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from typing import cast

import psycopg
import pytest
from test_migrations import _alembic_config

from alembic import command
from repovil.bootstrap import (
    BOOTSTRAP_LOCK_ID,
    BootstrapAlreadyRunningError,
    BootstrapHistoryError,
    calculate_bootstrap_baseline,
    calculate_bootstrap_baselines,
    run_bootstrap,
    star_history_days,
)
from repovil.db import connect_database
from repovil.github_client import (
    GitHubRateLimitError,
    RateLimit,
    RepositoryStats,
    RequestMetadata,
    StarHistoryPage,
    StarHistoryWeek,
)

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)
REQUEST = RequestMetadata(
    status_code=200,
    retry_count=0,
    duration_ms=5,
    rate_limit=RateLimit(limit=5_000, remaining=4_999, reset_at=2_000, resource="core"),
)


@pytest.fixture
def bootstrap_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    return postgres_schema_url


def _daily_counts(*, count: int = 1) -> dict[date, int]:
    return {
        NOW.date() - timedelta(days=offset): count
        for offset in range(30)
    }


def _history_weeks(*, count: int = 1) -> tuple[StarHistoryWeek, ...]:
    days_since_sunday = (NOW.date().weekday() + 1) % 7
    first_sunday = NOW.date() - timedelta(days=days_since_sunday)
    starts = tuple(first_sunday - timedelta(days=7 * offset) for offset in range(6))
    return tuple(
        StarHistoryWeek(
            week=int(datetime.combine(start, time(), tzinfo=UTC).timestamp()),
            total=count * 7,
            days=(count,) * 7,
        )
        for start in starts
    )


class FakeClient:
    def __init__(
        self,
        *,
        current_stars: int = 1_000,
        weeks: tuple[StarHistoryWeek, ...] | None = None,
        error: GitHubRateLimitError | None = None,
    ) -> None:
        self.current_stars = current_stars
        self.weeks = weeks if weeks is not None else _history_weeks()
        self.error = error
        self.stats_calls: list[tuple[str, str]] = []
        self.history_calls: list[tuple[str, str, int, int]] = []

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats:
        self.stats_calls.append((owner, name))
        if self.error is not None:
            raise self.error
        return RepositoryStats(star_count=self.current_stars, request=REQUEST)

    def get_star_history(
        self,
        owner: str,
        name: str,
        *,
        page: int = 1,
        per_page: int = 30,
    ) -> StarHistoryPage:
        self.history_calls.append((owner, name, page, per_page))
        return StarHistoryPage(
            weeks=self.weeks,
            page=page,
            per_page=per_page,
            request=REQUEST,
        )


def _insert_pending_repository(database_url: str, github_id: int = 101) -> int:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            INSERT INTO repositories (
                github_id, owner, name, github_url, current_stars, status, discovered_at
            )
            VALUES (%s, 'owner', %s, %s, 900, 'bootstrap_pending', %s)
            RETURNING id
            """,
            (
                github_id,
                f"repo-{github_id}",
                f"https://github.com/owner/repo-{github_id}",
                NOW - timedelta(hours=1),
            ),
        ).fetchone()
    assert row is not None
    return cast(int, row[0])


def test_known_daily_counts_produce_estimated_7d_and_30d_baselines() -> None:
    baselines = calculate_bootstrap_baselines(1_000, NOW, _daily_counts())

    assert [(item.period, item.star_count, item.star_gain) for item in baselines] == [
        ("7d", 993, 7),
        ("30d", 970, 30),
    ]
    assert all(item.is_estimated for item in baselines)
    assert baselines[0].target_time == NOW - timedelta(days=7)


def test_created_star_history_remains_estimated_when_unstars_are_not_represented() -> None:
    # GitHub reports 14 creations. Any unstars in the same period are unknowable, so
    # the arithmetic result remains an estimate rather than an actual snapshot.
    baseline = calculate_bootstrap_baseline(100, NOW, _daily_counts(count=2), "7d")

    assert baseline is not None
    assert baseline.star_count == 86
    assert baseline.star_gain == 14
    assert baseline.is_estimated is True


def test_invalid_or_incomplete_history_does_not_create_a_baseline() -> None:
    missing_recent_day = _daily_counts()
    del missing_recent_day[NOW.date() - timedelta(days=2)]
    older_days_missing = {
        bucket_date: value
        for bucket_date, value in _daily_counts().items()
        if bucket_date >= NOW.date() - timedelta(days=6)
    }

    assert calculate_bootstrap_baseline(1_000, NOW, missing_recent_day, "7d") is None
    partial = calculate_bootstrap_baselines(1_000, NOW, older_days_missing)
    assert [item.period for item in partial] == ["7d"]
    assert calculate_bootstrap_baseline(5, NOW, _daily_counts(), "7d") is None


def test_bootstrap_rejects_24h_and_naive_measurement_times() -> None:
    with pytest.raises(ValueError, match="only valid for 7d and 30d"):
        calculate_bootstrap_baseline(1_000, NOW, _daily_counts(), "24h")
    with pytest.raises(ValueError, match="timezone-aware"):
        calculate_bootstrap_baseline(
            1_000,
            NOW.replace(tzinfo=None),
            _daily_counts(),
            "7d",
        )


def test_week_page_boundaries_are_flattened_and_duplicate_buckets_are_rejected() -> None:
    weeks = _history_weeks()
    daily = star_history_days(weeks[:2])

    assert len(daily) == 14
    assert all(value == 1 for value in daily.values())
    with pytest.raises(BootstrapHistoryError, match="duplicate date bucket"):
        star_history_days((weeks[0], weeks[0]))


@pytest.mark.integration
def test_bootstrap_stores_source_activates_tracking_and_is_idempotent(
    bootstrap_database_url: str,
) -> None:
    repository_id = _insert_pending_repository(bootstrap_database_url)
    first_client = FakeClient()

    first = run_bootstrap(bootstrap_database_url, first_client, clock=lambda: NOW)
    second = run_bootstrap(bootstrap_database_url, FakeClient(), clock=lambda: NOW)

    assert first.processed_count == first.success_count == 1
    assert first.failed_count == 0
    assert [(item.period, item.star_count) for item in first.repositories[0].baselines] == [
        ("7d", 993),
        ("30d", 970),
    ]
    assert first.repositories[0].stored_day_count == 30
    assert second.processed_count == second.success_count == second.failed_count == 0
    assert first_client.stats_calls == [("owner", "repo-101")]
    assert first_client.history_calls == [("owner", "repo-101", 1, 30)]

    with psycopg.connect(bootstrap_database_url) as connection:
        repository_row = connection.execute(
            """
            SELECT status, current_stars, tracking_started_at, bootstrap_completed_at,
                   bootstrap_attempt_count, bootstrap_error_type
            FROM repositories WHERE id = %s
            """,
            (repository_id,),
        ).fetchone()
        history_row = connection.execute(
            """
            SELECT count(*), sum(stars_created), min(fetched_at), max(fetched_at)
            FROM bootstrap_star_history WHERE repository_id = %s
            """,
            (repository_id,),
        ).fetchone()

    assert repository_row == ("active", 1_000, NOW, NOW, 1, None)
    assert history_row == (30, 30, NOW, NOW)


@pytest.mark.integration
def test_duplicate_fetch_preserves_original_source_rows(
    bootstrap_database_url: str,
) -> None:
    repository_id = _insert_pending_repository(bootstrap_database_url)
    run_bootstrap(bootstrap_database_url, FakeClient(), clock=lambda: NOW)
    later = NOW + timedelta(days=1)
    with psycopg.connect(bootstrap_database_url) as connection:
        connection.execute(
            "UPDATE repositories SET status = 'bootstrap_pending' WHERE id = %s",
            (repository_id,),
        )

    run_bootstrap(
        bootstrap_database_url,
        FakeClient(current_stars=1_100, weeks=_history_weeks(count=9)),
        clock=lambda: later,
    )

    with psycopg.connect(bootstrap_database_url) as connection:
        original_overlap = connection.execute(
            """
            SELECT stars_created, fetched_at
            FROM bootstrap_star_history
            WHERE repository_id = %s AND date = %s
            """,
            (repository_id, NOW.date()),
        ).fetchone()
        counts = connection.execute(
            "SELECT count(*) FROM bootstrap_star_history WHERE repository_id = %s",
            (repository_id,),
        ).fetchone()

    assert original_overlap == (1, NOW)
    assert counts == (31,)


@pytest.mark.integration
def test_api_failure_stays_pending_records_cause_and_succeeds_on_retry(
    bootstrap_database_url: str,
) -> None:
    repository_id = _insert_pending_repository(bootstrap_database_url)
    failure_request = RequestMetadata(
        status_code=429,
        retry_count=3,
        duration_ms=250,
        rate_limit=RateLimit(limit=5_000, remaining=0, reset_at=2_000, resource="core"),
    )
    error = GitHubRateLimitError("rate limit remained exhausted", request=failure_request)

    failed = run_bootstrap(
        bootstrap_database_url,
        FakeClient(error=error),
        clock=lambda: NOW,
    )

    assert failed.success_count == 0
    assert failed.failed_count == 1
    assert failed.failures[0].response_status == 429
    with psycopg.connect(bootstrap_database_url) as connection:
        pending = connection.execute(
            """
            SELECT status, bootstrap_attempt_count, bootstrap_error_type,
                   bootstrap_response_status, bootstrap_retry_count,
                   bootstrap_duration_ms
            FROM repositories WHERE id = %s
            """,
            (repository_id,),
        ).fetchone()
        source_count = connection.execute(
            "SELECT count(*) FROM bootstrap_star_history WHERE repository_id = %s",
            (repository_id,),
        ).fetchone()
    assert pending == ("bootstrap_pending", 1, "GitHubRateLimitError", 429, 3, 250)
    assert source_count == (0,)

    retried = run_bootstrap(
        bootstrap_database_url,
        FakeClient(),
        clock=lambda: NOW + timedelta(minutes=5),
    )

    assert retried.success_count == 1
    with psycopg.connect(bootstrap_database_url) as connection:
        completed = connection.execute(
            """
            SELECT status, bootstrap_attempt_count, bootstrap_error_type,
                   bootstrap_response_status, bootstrap_retry_count
            FROM repositories WHERE id = %s
            """,
            (repository_id,),
        ).fetchone()
    assert completed == ("active", 2, None, None, 0)


@pytest.mark.integration
def test_incomplete_history_activates_tracking_without_invalid_estimates(
    bootstrap_database_url: str,
) -> None:
    repository_id = _insert_pending_repository(bootstrap_database_url)
    one_week = (_history_weeks()[0],)

    result = run_bootstrap(
        bootstrap_database_url,
        FakeClient(weeks=one_week),
        clock=lambda: NOW,
    )

    assert result.success_count == 1
    assert result.repositories[0].baselines == ()
    with psycopg.connect(bootstrap_database_url) as connection:
        status = connection.execute(
            "SELECT status FROM repositories WHERE id = %s",
            (repository_id,),
        ).fetchone()
    assert status == ("active",)


@pytest.mark.integration
def test_database_lock_prevents_a_concurrent_bootstrap(
    bootstrap_database_url: str,
) -> None:
    with connect_database(bootstrap_database_url) as lock_connection:
        assert lock_connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (BOOTSTRAP_LOCK_ID,),
        ).fetchone() == (True,)

        with pytest.raises(BootstrapAlreadyRunningError):
            run_bootstrap(bootstrap_database_url, FakeClient(), clock=lambda: NOW)

        lock_connection.execute("SELECT pg_advisory_unlock(%s)", (BOOTSTRAP_LOCK_ID,))
