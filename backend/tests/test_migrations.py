from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import cast

import psycopg
import pytest
from alembic.config import Config

from alembic import command
from repovil.db import connect_database

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DOMAIN_TABLES = {
    "categories",
    "topics",
    "category_topics",
    "repositories",
    "repository_topics",
    "discovery_runs",
    "tracking_runs",
    "tracking_run_items",
    "star_snapshots",
    "bootstrap_star_history",
    "rankings",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(PROJECT_ROOT / "alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


@pytest.fixture
def migrated_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    return postgres_schema_url


def _table_names(database_url: str) -> set[str]:
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname = current_schema()"
        ).fetchall()
    return {str(row[0]) for row in rows}


@pytest.mark.integration
def test_upgrade_downgrade_upgrade_creates_the_expected_schema(
    postgres_schema_url: str,
) -> None:
    config = _alembic_config(postgres_schema_url)

    command.upgrade(config, "head")
    assert _table_names(postgres_schema_url) >= DOMAIN_TABLES

    command.downgrade(config, "base")
    assert DOMAIN_TABLES.isdisjoint(_table_names(postgres_schema_url))

    command.upgrade(config, "head")
    assert _table_names(postgres_schema_url) >= DOMAIN_TABLES


def _insert_repository(connection: psycopg.Connection[tuple[object, ...]]) -> int:
    row = connection.execute(
        """
        INSERT INTO repositories (
            github_id, owner, name, github_url, current_stars, status, discovered_at
        )
        VALUES (101, 'old-owner', 'project', 'https://github.com/old-owner/project',
                200, 'active', '2026-10-11T00:00:00Z')
        RETURNING id
        """
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _insert_tracking_run(
    connection: psycopg.Connection[tuple[object, ...]],
    scheduled_at: datetime,
) -> int:
    row = connection.execute(
        """
        INSERT INTO tracking_runs (scheduled_at, started_at, total_count, status)
        VALUES (%s, %s, 1, 'RUNNING')
        RETURNING id
        """,
        (scheduled_at, scheduled_at),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


@pytest.mark.integration
def test_identity_history_run_audit_and_utc_round_trip(
    migrated_database_url: str,
) -> None:
    utc = UTC
    scheduled_at = datetime(2026, 10, 11, 9, 0, tzinfo=timezone(timedelta(hours=9)))

    with connect_database(migrated_database_url) as connection:
        repository_id = _insert_repository(connection)
        first_run_id = _insert_tracking_run(connection, scheduled_at)
        connection.execute(
            """
            INSERT INTO tracking_run_items (tracking_run_id, repository_id, status)
            VALUES (%s, %s, 'success')
            """,
            (first_run_id, repository_id),
        )
        connection.execute(
            """
            INSERT INTO star_snapshots (
                tracking_run_id, repository_id, captured_at, star_count
            ) VALUES (%s, %s, %s, 210)
            """,
            (first_run_id, repository_id, scheduled_at),
        )
        connection.execute(
            """
            INSERT INTO rankings (
                tracking_run_id, repository_id, period, score, star_gain,
                current_stars, is_estimated, calculated_at
            ) VALUES (%s, %s, '24h', 0.04, 10, 210, false, %s)
            """,
            (first_run_id, repository_id, scheduled_at),
        )
        connection.execute(
            """
            UPDATE tracking_runs
            SET status = 'COMPLETED', success_count = 1,
                finished_at = %s, published_at = %s
            WHERE id = %s
            """,
            (scheduled_at, scheduled_at, first_run_id),
        )

        second_at = scheduled_at.astimezone(utc) + timedelta(hours=6)
        second_run_id = _insert_tracking_run(connection, second_at)
        connection.execute(
            """
            INSERT INTO tracking_run_items (tracking_run_id, repository_id, status)
            VALUES (%s, %s, 'success')
            """,
            (second_run_id, repository_id),
        )
        connection.execute(
            """
            INSERT INTO star_snapshots (
                tracking_run_id, repository_id, captured_at, star_count
            ) VALUES (%s, %s, %s, 215)
            """,
            (second_run_id, repository_id, second_at),
        )

        connection.execute(
            """
            UPDATE repositories
            SET owner = 'new-owner', name = 'renamed',
                github_url = 'https://github.com/new-owner/renamed'
            WHERE github_id = 101
            """
        )

        stored_time = connection.execute(
            "SELECT scheduled_at FROM tracking_runs WHERE id = %s", (first_run_id,)
        ).fetchone()
        identity = connection.execute(
            "SELECT id, owner, name FROM repositories WHERE github_id = 101"
        ).fetchone()
        snapshot_count = connection.execute(
            "SELECT count(*) FROM star_snapshots WHERE repository_id = %s",
            (repository_id,),
        ).fetchone()
        audit = connection.execute(
            """
            SELECT tracking_runs.status, tracking_runs.published_at,
                   tracking_run_items.status
            FROM tracking_runs
            JOIN tracking_run_items
              ON tracking_run_items.tracking_run_id = tracking_runs.id
            WHERE tracking_runs.id = %s
            """,
            (first_run_id,),
        ).fetchone()

    assert stored_time is not None
    stored_datetime = cast(datetime, stored_time[0])
    assert stored_datetime == datetime(2026, 10, 11, 0, 0, tzinfo=utc)
    assert stored_datetime.utcoffset() == timedelta(0)
    assert identity == (repository_id, "new-owner", "renamed")
    assert snapshot_count == (2,)
    assert audit is not None
    assert audit[0] == "COMPLETED"
    assert audit[1] is not None
    assert audit[2] == "success"


def _assert_integrity_error(
    connection: psycopg.Connection[tuple[object, ...]],
    statement: str,
    parameters: tuple[object, ...] = (),
) -> None:
    with pytest.raises(psycopg.IntegrityError), connection.transaction():
        connection.execute(statement, parameters)


@pytest.mark.integration
def test_key_unique_foreign_key_and_check_constraints(
    migrated_database_url: str,
) -> None:
    now = datetime(2026, 10, 11, tzinfo=UTC)
    with psycopg.connect(migrated_database_url, autocommit=True) as connection:
        repository_id = _insert_repository(connection)
        run_id = _insert_tracking_run(connection, now)
        connection.execute(
            """
            INSERT INTO tracking_run_items (tracking_run_id, repository_id, status)
            VALUES (%s, %s, 'success')
            """,
            (run_id, repository_id),
        )
        connection.execute(
            """
            INSERT INTO star_snapshots (
                tracking_run_id, repository_id, captured_at, star_count
            ) VALUES (%s, %s, %s, 210)
            """,
            (run_id, repository_id, now),
        )

        _assert_integrity_error(
            connection,
            """
            INSERT INTO repositories (
                github_id, owner, name, github_url, current_stars, status, discovered_at
            ) VALUES (101, 'other', 'other', 'https://github.com/other/other',
                      200, 'active', %s)
            """,
            (now,),
        )
        _assert_integrity_error(
            connection,
            """
            INSERT INTO tracking_runs (scheduled_at, started_at, status)
            VALUES (%s, %s, 'RUNNING')
            """,
            (now, now),
        )
        _assert_integrity_error(
            connection,
            "UPDATE repositories SET current_stars = -1 WHERE id = %s",
            (repository_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE repositories SET bootstrap_attempt_count = -1 WHERE id = %s",
            (repository_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE repositories SET bootstrap_retry_count = -1 WHERE id = %s",
            (repository_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE repositories SET bootstrap_response_status = 99 WHERE id = %s",
            (repository_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE repositories SET status = 'tracking' WHERE id = %s",
            (repository_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE tracking_runs SET status = 'DONE' WHERE id = %s",
            (run_id,),
        )
        _assert_integrity_error(
            connection,
            "UPDATE tracking_runs SET failed_count = -1 WHERE id = %s",
            (run_id,),
        )
        _assert_integrity_error(
            connection,
            """
            UPDATE tracking_run_items
            SET status = 'pending'
            WHERE tracking_run_id = %s AND repository_id = %s
            """,
            (run_id, repository_id),
        )
        _assert_integrity_error(
            connection,
            """
            INSERT INTO tracking_run_items (tracking_run_id, repository_id, status)
            VALUES (%s, 999999, 'failed')
            """,
            (run_id,),
        )
        _assert_integrity_error(
            connection,
            """
            INSERT INTO star_snapshots (
                tracking_run_id, repository_id, captured_at, star_count
            ) VALUES (%s, %s, %s, 211)
            """,
            (run_id, repository_id, now),
        )
        _assert_integrity_error(
            connection,
            """
            UPDATE star_snapshots SET star_count = -1
            WHERE tracking_run_id = %s AND repository_id = %s
            """,
            (run_id, repository_id),
        )
        _assert_integrity_error(
            connection,
            """
            INSERT INTO bootstrap_star_history (
                repository_id, date, stars_created, fetched_at
            ) VALUES (%s, '2026-10-10', -1, %s)
            """,
            (repository_id, now),
        )
        connection.execute(
            """
            INSERT INTO rankings (
                tracking_run_id, repository_id, period, score, star_gain,
                current_stars, is_estimated, calculated_at
            ) VALUES (%s, %s, '24h', 0.04, 10, 210, false, %s)
            """,
            (run_id, repository_id, now),
        )
        _assert_integrity_error(
            connection,
            """
            UPDATE rankings SET period = '1d'
            WHERE tracking_run_id = %s AND repository_id = %s AND period = '24h'
            """,
            (run_id, repository_id),
        )
        _assert_integrity_error(
            connection,
            """
            UPDATE rankings SET star_gain = 0
            WHERE tracking_run_id = %s AND repository_id = %s AND period = '24h'
            """,
            (run_id, repository_id),
        )
        _assert_integrity_error(
            connection,
            """
            INSERT INTO discovery_runs (started_at, status, failed_ranges)
            VALUES (%s, 'PARTIAL', '{}'::jsonb)
            """,
            (now,),
        )
