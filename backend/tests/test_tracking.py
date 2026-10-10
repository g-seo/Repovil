from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone
from typing import cast

import psycopg
import pytest
from test_category_sync import DEFAULT_CONFIG
from test_migrations import _alembic_config

from alembic import command
from repovil.category_sync import sync_categories
from repovil.db import connect_database
from repovil.github_client import (
    GitHubAuthenticationError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubTransportError,
    RateLimit,
    Repository,
    RepositoryResult,
    RepositoryStats,
    RequestMetadata,
)
from repovil.tracking import (
    TRACKING_LOCK_ID,
    TrackingAlreadyRunningError,
    run_tracking,
    schedule_slot,
)

NOW = datetime(2026, 10, 11, 12, 34, 56, 123456, tzinfo=UTC)
SLOT = datetime(2026, 10, 11, 12, tzinfo=UTC)
METADATA_REQUEST = RequestMetadata(
    status_code=200,
    retry_count=1,
    duration_ms=5,
    rate_limit=RateLimit(limit=5_000, remaining=4_999, reset_at=2_000, resource="core"),
)
STATS_REQUEST = RequestMetadata(
    status_code=200,
    retry_count=2,
    duration_ms=7,
    rate_limit=RateLimit(limit=5_000, remaining=4_998, reset_at=2_000, resource="core"),
)


@pytest.fixture
def tracking_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    sync_categories(postgres_schema_url, DEFAULT_CONFIG)
    return postgres_schema_url


def repository(
    github_id: int,
    *,
    owner: str = "owner",
    name: str | None = None,
    stars: int = 300,
    topics: tuple[str, ...] = ("ai-agent",),
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


MetadataValue = (
    Repository
    | GitHubNotFoundError
    | GitHubRateLimitError
    | GitHubTransportError
    | GitHubAuthenticationError
)
StatsValue = (
    int
    | GitHubNotFoundError
    | GitHubRateLimitError
    | GitHubTransportError
    | GitHubAuthenticationError
)


class FakeClient:
    def __init__(
        self,
        metadata: dict[str, MetadataValue],
        stats: dict[str, StatsValue] | None = None,
        *,
        on_get_repository: Callable[[str], None] | None = None,
    ) -> None:
        self.metadata = metadata
        self.stats = stats or {}
        self.on_get_repository = on_get_repository
        self.metadata_calls: list[tuple[str, str]] = []
        self.stats_calls: list[tuple[str, str]] = []

    def get_repository(self, owner: str, name: str) -> RepositoryResult:
        self.metadata_calls.append((owner, name))
        if self.on_get_repository is not None:
            self.on_get_repository(name)
        value = self.metadata[name]
        if isinstance(value, Exception):
            raise value
        return RepositoryResult(repository=value, request=METADATA_REQUEST)

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats:
        self.stats_calls.append((owner, name))
        value = self.stats.get(name)
        if value is None:
            metadata = self.metadata[name]
            assert isinstance(metadata, Repository)
            value = metadata.stars
        if isinstance(value, Exception):
            raise value
        return RepositoryStats(star_count=value, request=STATS_REQUEST)


def _error_request(status: int | None, *, retries: int = 3) -> RequestMetadata:
    return RequestMetadata(
        status_code=status,
        retry_count=retries,
        duration_ms=250,
        rate_limit=RateLimit(5_000, 0, 2_000, "core"),
    )


def _insert_active_repository(database_url: str, github_id: int, *, topic: str = "ai-agent") -> int:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            INSERT INTO repositories (
                github_id, owner, name, github_url, current_stars, status,
                discovered_at, tracking_started_at
            )
            VALUES (%s, 'owner', %s, %s, 250, 'active', %s, %s)
            RETURNING id
            """,
            (
                github_id,
                f"repo-{github_id}",
                f"https://github.com/owner/repo-{github_id}",
                NOW - timedelta(days=2),
                NOW - timedelta(days=1),
            ),
        ).fetchone()
        assert row is not None
        repository_id = cast(int, row[0])
        connection.execute(
            """
            INSERT INTO repository_topics (repository_id, topic_id)
            SELECT %s, id FROM topics WHERE name = %s
            """,
            (repository_id, topic),
        )
    return repository_id


def test_schedule_slot_is_utc_aligned_and_rejects_naive_values() -> None:
    seoul = timezone(timedelta(hours=9))

    assert schedule_slot(NOW.astimezone(seoul)) == SLOT
    with pytest.raises(ValueError, match="timezone-aware"):
        schedule_slot(NOW.replace(tzinfo=None))


@pytest.mark.integration
def test_success_stores_actual_snapshot_and_updates_renamed_metadata_and_topics(
    tracking_database_url: str,
) -> None:
    repository_id = _insert_active_repository(tracking_database_url, 101)
    renamed = repository(
        101,
        owner="new-owner",
        name="new-name",
        stars=349,
        topics=("mcp-server",),
    )
    client = FakeClient({"repo-101": renamed}, {"new-name": 350})

    result = run_tracking(
        tracking_database_url,
        client,
        scheduled_at=SLOT,
        clock=lambda: NOW,
    )

    assert (result.status, result.total_count) == ("COMPLETED", 1)
    assert (result.success_count, result.failed_count, result.skipped_count) == (1, 0, 0)
    assert result.scheduled_at == SLOT
    assert client.stats_calls == [("new-owner", "new-name")]
    with psycopg.connect(tracking_database_url) as connection:
        repository_row = connection.execute(
            """
            SELECT owner, name, github_url, current_stars, status
            FROM repositories WHERE id = %s
            """,
            (repository_id,),
        ).fetchone()
        snapshot_row = connection.execute(
            """
            SELECT captured_at, star_count FROM star_snapshots
            WHERE tracking_run_id = %s AND repository_id = %s
            """,
            (result.run_id, repository_id),
        ).fetchone()
        item_row = connection.execute(
            """
            SELECT status, response_status, retry_count, duration_ms
            FROM tracking_run_items
            WHERE tracking_run_id = %s AND repository_id = %s
            """,
            (result.run_id, repository_id),
        ).fetchone()
        active_topics = connection.execute(
            """
            SELECT topics.name
            FROM repository_topics
            JOIN topics ON topics.id = repository_topics.topic_id
            WHERE repository_topics.repository_id = %s AND repository_topics.active
            """,
            (repository_id,),
        ).fetchall()

    assert repository_row == (
        "new-owner",
        "new-name",
        "https://github.com/new-owner/new-name",
        350,
        "active",
    )
    assert snapshot_row == (NOW, 350)
    assert item_row == ("success", 200, 3, 12)
    assert active_topics == [("mcp-server",)]
    assert snapshot_row[0] != SLOT


@pytest.mark.integration
def test_duplicate_schedule_slot_returns_finished_run_without_new_calls_or_snapshot(
    tracking_database_url: str,
) -> None:
    _insert_active_repository(tracking_database_url, 101)
    client = FakeClient({"repo-101": repository(101)})

    first = run_tracking(tracking_database_url, client, scheduled_at=SLOT, clock=lambda: NOW)
    second = run_tracking(tracking_database_url, client, scheduled_at=SLOT, clock=lambda: NOW)

    assert second.run_id == first.run_id
    assert second.already_finished is True
    assert client.metadata_calls == [("owner", "repo-101")]
    with psycopg.connect(tracking_database_url) as connection:
        assert connection.execute("SELECT count(*) FROM tracking_runs").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM star_snapshots").fetchone() == (1,)


@pytest.mark.integration
def test_partial_and_all_failed_statuses_do_not_copy_stale_snapshots(
    tracking_database_url: str,
) -> None:
    first_id = _insert_active_repository(tracking_database_url, 101)
    second_id = _insert_active_repository(tracking_database_url, 202)
    previous_slot = SLOT - timedelta(hours=6)
    with psycopg.connect(tracking_database_url) as connection:
        previous_run = connection.execute(
            """
            INSERT INTO tracking_runs (
                scheduled_at, started_at, finished_at, total_count, success_count, status
            ) VALUES (%s, %s, %s, 1, 1, 'COMPLETED') RETURNING id
            """,
            (previous_slot, previous_slot, previous_slot + timedelta(minutes=1)),
        ).fetchone()
        assert previous_run is not None
        connection.execute(
            """
            INSERT INTO tracking_run_items (tracking_run_id, repository_id, status)
            VALUES (%s, %s, 'success')
            """,
            (previous_run[0], second_id),
        )
        connection.execute(
            """
            INSERT INTO star_snapshots (
                tracking_run_id, repository_id, captured_at, star_count
            ) VALUES (%s, %s, %s, 275)
            """,
            (previous_run[0], second_id, previous_slot + timedelta(minutes=1)),
        )

    transport_error = GitHubTransportError(
        "request timed out after retries",
        request=_error_request(None),
    )
    partial = run_tracking(
        tracking_database_url,
        FakeClient(
            {
                "repo-101": repository(101),
                "repo-202": transport_error,
            }
        ),
        scheduled_at=SLOT,
        clock=lambda: NOW,
    )

    assert partial.status == "PARTIAL"
    assert (partial.success_count, partial.failed_count, partial.skipped_count) == (1, 1, 0)
    with psycopg.connect(tracking_database_url) as connection:
        snapshots = connection.execute(
            """
            SELECT tracking_run_id, repository_id, star_count
            FROM star_snapshots ORDER BY tracking_run_id, repository_id
            """
        ).fetchall()
    assert snapshots == [(previous_run[0], second_id, 275), (partial.run_id, first_id, 300)]

    later_slot = SLOT + timedelta(hours=6)
    all_failed = run_tracking(
        tracking_database_url,
        FakeClient(
            {
                "repo-101": transport_error,
                "repo-202": transport_error,
            }
        ),
        scheduled_at=later_slot,
        clock=lambda: NOW + timedelta(hours=6),
    )
    assert all_failed.status == "FAILED"
    assert (all_failed.success_count, all_failed.failed_count) == (0, 2)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("github_id", "metadata", "stats", "reason"),
    [
        (101, repository(101, archived=True), None, "archived"),
        (102, repository(102, visibility="private"), None, "not public"),
        (103, repository(103, fork=True), None, "fork"),
        (104, repository(104, topics=("unconfigured",)), None, "no active configured topic"),
        (105, repository(105), 199, "fewer than 200"),
    ],
)
def test_confirmed_ineligible_repository_is_skipped_and_deactivated(
    tracking_database_url: str,
    github_id: int,
    metadata: Repository,
    stats: int | None,
    reason: str,
) -> None:
    repository_id = _insert_active_repository(tracking_database_url, github_id)
    name = f"repo-{github_id}"
    client = FakeClient({name: metadata}, {name: stats} if stats is not None else {})

    result = run_tracking(tracking_database_url, client, scheduled_at=SLOT, clock=lambda: NOW)

    assert result.status == "COMPLETED"
    assert (result.success_count, result.failed_count, result.skipped_count) == (0, 0, 1)
    with psycopg.connect(tracking_database_url) as connection:
        repository_row = connection.execute(
            "SELECT status, current_stars FROM repositories WHERE id = %s",
            (repository_id,),
        ).fetchone()
        item_row = connection.execute(
            """
            SELECT status, error_message FROM tracking_run_items
            WHERE tracking_run_id = %s AND repository_id = %s
            """,
            (result.run_id, repository_id),
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT count(*) FROM star_snapshots WHERE tracking_run_id = %s",
            (result.run_id,),
        ).fetchone()
    assert repository_row is not None and repository_row[0] == "inactive"
    assert item_row is not None and item_row[0] == "skipped" and reason in item_row[1]
    assert snapshot_count == (0,)


@pytest.mark.integration
def test_deleted_or_private_404_is_skipped_and_preserves_repository_history(
    tracking_database_url: str,
) -> None:
    repository_id = _insert_active_repository(tracking_database_url, 101)
    not_found = GitHubNotFoundError(
        "repository was not found",
        request=_error_request(404, retries=0),
    )

    result = run_tracking(
        tracking_database_url,
        FakeClient({"repo-101": not_found}),
        scheduled_at=SLOT,
        clock=lambda: NOW,
    )

    assert (result.status, result.skipped_count, result.failed_count) == ("COMPLETED", 1, 0)
    with psycopg.connect(tracking_database_url) as connection:
        row = connection.execute(
            "SELECT github_id, owner, name, status FROM repositories WHERE id = %s",
            (repository_id,),
        ).fetchone()
        snapshot_count = connection.execute("SELECT count(*) FROM star_snapshots").fetchone()
    assert row == (101, "owner", "repo-101", "inactive")
    assert snapshot_count == (0,)


@pytest.mark.integration
def test_authentication_failure_marks_unprocessed_targets_failed_and_fails_run(
    tracking_database_url: str,
) -> None:
    _insert_active_repository(tracking_database_url, 101)
    _insert_active_repository(tracking_database_url, 202)
    auth_error = GitHubAuthenticationError(
        "authentication failed",
        request=_error_request(401, retries=0),
    )

    with pytest.raises(GitHubAuthenticationError):
        run_tracking(
            tracking_database_url,
            FakeClient(
                {
                    "repo-101": auth_error,
                    "repo-202": repository(202),
                }
            ),
            scheduled_at=SLOT,
            clock=lambda: NOW,
        )

    with psycopg.connect(tracking_database_url) as connection:
        run_row = connection.execute(
            """
            SELECT status, total_count, success_count, failed_count, skipped_count
            FROM tracking_runs WHERE scheduled_at = %s
            """,
            (SLOT,),
        ).fetchone()
        item_rows = connection.execute(
            """
            SELECT status, error_type FROM tracking_run_items
            ORDER BY repository_id
            """
        ).fetchall()
    assert run_row == ("FAILED", 2, 0, 2, 0)
    assert item_rows == [
        ("failed", "GitHubAuthenticationError"),
        ("failed", "GitHubAuthenticationError"),
    ]


@pytest.mark.integration
def test_target_set_is_fixed_before_github_calls(tracking_database_url: str) -> None:
    _insert_active_repository(tracking_database_url, 101)
    inserted = False

    def add_repository(_name: str) -> None:
        nonlocal inserted
        if not inserted:
            _insert_active_repository(tracking_database_url, 202)
            inserted = True

    client = FakeClient(
        {"repo-101": repository(101), "repo-202": repository(202)},
        on_get_repository=add_repository,
    )

    result = run_tracking(tracking_database_url, client, scheduled_at=SLOT, clock=lambda: NOW)

    assert result.total_count == result.success_count == 1
    assert client.metadata_calls == [("owner", "repo-101")]
    with psycopg.connect(tracking_database_url) as connection:
        targets = connection.execute(
            "SELECT repository_id FROM tracking_run_items WHERE tracking_run_id = %s",
            (result.run_id,),
        ).fetchall()
    assert len(targets) == 1


@pytest.mark.integration
def test_repository_deactivated_after_target_fix_is_skipped_without_api_call(
    tracking_database_url: str,
) -> None:
    _insert_active_repository(tracking_database_url, 101)
    second_id = _insert_active_repository(tracking_database_url, 202)

    def deactivate_second(name: str) -> None:
        if name == "repo-101":
            with psycopg.connect(tracking_database_url) as connection:
                connection.execute(
                    "UPDATE repositories SET status = 'inactive' WHERE id = %s",
                    (second_id,),
                )

    client = FakeClient(
        {"repo-101": repository(101), "repo-202": repository(202)},
        on_get_repository=deactivate_second,
    )

    result = run_tracking(tracking_database_url, client, scheduled_at=SLOT, clock=lambda: NOW)

    assert (result.success_count, result.skipped_count, result.failed_count) == (1, 1, 0)
    assert client.metadata_calls == [("owner", "repo-101")]


@pytest.mark.integration
def test_empty_target_run_is_completed_with_zero_denominator(tracking_database_url: str) -> None:
    result = run_tracking(
        tracking_database_url,
        FakeClient({}),
        scheduled_at=SLOT,
        clock=lambda: NOW,
    )

    assert result.status == "COMPLETED"
    assert (
        result.total_count
        == result.success_count
        == result.failed_count
        == result.skipped_count
        == 0
    )


@pytest.mark.integration
def test_database_lock_blocks_concurrent_tracking(tracking_database_url: str) -> None:
    with connect_database(tracking_database_url) as lock_connection:
        assert lock_connection.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (TRACKING_LOCK_ID,),
        ).fetchone() == (True,)

        with pytest.raises(TrackingAlreadyRunningError):
            run_tracking(
                tracking_database_url,
                FakeClient({}),
                scheduled_at=SLOT,
                clock=lambda: NOW,
            )
