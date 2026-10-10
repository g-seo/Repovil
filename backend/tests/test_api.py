from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import cast

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from pytest import MonkeyPatch
from test_category_sync import DEFAULT_CONFIG
from test_migrations import _alembic_config

from alembic import command
from repovil.category_sync import sync_categories
from repovil.settings import Settings

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


@pytest.fixture
def api_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    sync_categories(postgres_schema_url, DEFAULT_CONFIG)
    return postgres_schema_url


@pytest.fixture
def client(api_database_url: str) -> Iterator[TestClient]:
    from repovil.api import create_app

    settings = Settings(database_url=PostgresDsn(api_database_url))
    with TestClient(create_app(settings, clock=lambda: NOW)) as test_client:
        yield test_client


def _insert_repository(
    connection: psycopg.Connection[tuple[object, ...]],
    github_id: int,
    *,
    owner: str = "owner",
    name: str | None = None,
    topic_names: tuple[str, ...] = (),
) -> int:
    repository_name = name or f"repo-{github_id}"
    row = connection.execute(
        """
        INSERT INTO repositories (
            github_id, owner, name, description, github_url, language,
            current_stars, status, discovered_at, tracking_started_at,
            bootstrap_completed_at
        )
        VALUES (%s, %s, %s, %s, %s, 'Python', 1000, 'active', %s, %s, %s)
        RETURNING id
        """,
        (
            github_id,
            owner,
            repository_name,
            f"Repository {github_id}",
            f"https://github.com/{owner}/{repository_name}",
            NOW - timedelta(days=60),
            NOW - timedelta(days=31),
            NOW - timedelta(days=31),
        ),
    ).fetchone()
    assert row is not None
    repository_id = cast(int, row[0])
    for topic_name in topic_names:
        connection.execute(
            """
            INSERT INTO repository_topics (repository_id, topic_id)
            SELECT %s, id FROM topics WHERE name = %s
            """,
            (repository_id, topic_name),
        )
    return repository_id


def _insert_published_run(
    connection: psycopg.Connection[tuple[object, ...]],
    repositories: list[tuple[int, int, float, int]],
    *,
    published_at: datetime = NOW,
    period: str = "7d",
) -> int:
    run_row = connection.execute(
        """
        INSERT INTO tracking_runs (
            scheduled_at, started_at, finished_at, total_count, success_count,
            status, published_at
        ) VALUES (%s, %s, %s, %s, %s, 'COMPLETED', %s)
        RETURNING id
        """,
        (
            published_at,
            published_at,
            published_at,
            len(repositories),
            len(repositories),
            published_at,
        ),
    ).fetchone()
    assert run_row is not None
    run_id = cast(int, run_row[0])
    for repository_id, _, score, gain in repositories:
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
            ) VALUES (%s, %s, %s, 1000)
            """,
            (run_id, repository_id, published_at),
        )
        connection.execute(
            """
            INSERT INTO rankings (
                tracking_run_id, repository_id, period, score, star_gain,
                current_stars, is_estimated, calculated_at
            ) VALUES (%s, %s, %s, %s, %s, 1000, false, %s)
            """,
            (run_id, repository_id, period, score, gain, published_at),
        )
    return run_id


def _insert_snapshot(
    connection: psycopg.Connection[tuple[object, ...]],
    repository_id: int,
    captured_at: datetime,
    star_count: int,
) -> None:
    run_row = connection.execute(
        """
        INSERT INTO tracking_runs (
            scheduled_at, started_at, finished_at, total_count, success_count, status
        ) VALUES (%s, %s, %s, 1, 1, 'COMPLETED')
        RETURNING id
        """,
        (captured_at, captured_at, captured_at),
    ).fetchone()
    assert run_row is not None
    run_id = cast(int, run_row[0])
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
        ) VALUES (%s, %s, %s, %s)
        """,
        (run_id, repository_id, captured_at, star_count),
    )


def test_fastapi_application_starts() -> None:
    from repovil.api import create_app

    settings = Settings(database_url=PostgresDsn("postgresql://test:test@localhost:5432/test"))

    application = create_app(settings)
    openapi_schema = application.openapi()

    assert openapi_schema["info"] == {"title": "Repovil", "version": "0.1.0"}
    assert application.state.settings is settings


def test_health_does_not_require_database() -> None:
    from repovil.api import create_app

    settings = Settings(database_url=PostgresDsn("postgresql://test:test@localhost:1/test"))

    with TestClient(create_app(settings)) as test_client:
        response = test_client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.integration
def test_readiness_reports_database_health(
    client: TestClient,
    monkeypatch: MonkeyPatch,
) -> None:
    ready = client.get("/ready")

    def fail_connection(_: str) -> None:
        raise psycopg.OperationalError("database unavailable")

    monkeypatch.setattr("repovil.api.check_connection", fail_connection)
    unavailable = client.get("/ready")

    assert ready.status_code == 200
    assert ready.json() == {"status": "ready"}
    assert unavailable.status_code == 503
    assert unavailable.json() == {"status": "not_ready"}


@pytest.mark.integration
def test_rankings_distinguish_preparing_from_ready_empty(
    api_database_url: str,
    client: TestClient,
) -> None:
    preparing = client.get("/rankings")
    with psycopg.connect(api_database_url) as connection:
        run_id = _insert_published_run(connection, [])
    ready = client.get("/rankings", params={"category": "skills", "page": 4})

    assert preparing.status_code == 200
    assert preparing.json() == {
        "state": "preparing",
        "tracking_run_id": None,
        "calculated_at": None,
        "period": "7d",
        "category": None,
        "items": [],
        "pagination": {"page": 1, "page_size": 20, "total_items": 0, "total_pages": 0},
    }
    assert ready.status_code == 200
    assert ready.json()["state"] == "ready"
    assert ready.json()["tracking_run_id"] == run_id
    assert ready.json()["calculated_at"] == NOW.isoformat().replace("+00:00", "Z")
    assert ready.json()["items"] == []
    assert ready.json()["pagination"] == {
        "page": 4,
        "page_size": 20,
        "total_items": 0,
        "total_pages": 0,
    }


@pytest.mark.integration
def test_ranking_validation_identifies_period_page_and_category_errors(
    client: TestClient,
) -> None:
    bad_period = client.get("/rankings", params={"period": "year"})
    zero_page = client.get("/rankings", params={"page": 0})
    text_page = client.get("/rankings", params={"page": "first"})
    bad_category = client.get("/rankings", params={"category": "not-configured"})

    assert bad_period.status_code == 422
    assert bad_period.json()["detail"][0]["loc"][-1] == "period"
    assert zero_page.status_code == 422
    assert zero_page.json()["detail"][0]["loc"][-1] == "page"
    assert text_page.status_code == 422
    assert text_page.json()["detail"][0]["loc"][-1] == "page"
    assert bad_category.status_code == 422
    assert bad_category.json()["detail"]["code"] == "invalid_category"


@pytest.mark.integration
def test_rankings_use_latest_published_run_stable_pagination_and_category_deduplication(
    api_database_url: str,
    client: TestClient,
) -> None:
    with psycopg.connect(api_database_url) as connection:
        old_repository = _insert_repository(connection, 999)
        _insert_published_run(
            connection,
            [(old_repository, 999, 9.0, 900)],
            published_at=NOW - timedelta(hours=6),
        )
        current: list[tuple[int, int, float, int]] = []
        for github_id in range(41, 0, -1):
            topics = ("ai-agent", "ai-agents") if github_id == 1 else ("ai-agent",)
            repository_id = _insert_repository(
                connection,
                github_id,
                topic_names=topics,
            )
            current.append((repository_id, github_id, 0.5, 10))
        latest_run_id = _insert_published_run(connection, current)

    first = client.get("/rankings", params={"period": "7d", "category": "ai-agents"})
    middle = client.get(
        "/rankings",
        params={"period": "7d", "category": "ai-agents", "page": 2},
    )
    last = client.get(
        "/rankings",
        params={"period": "7d", "category": "ai-agents", "page": 3},
    )
    outside = client.get(
        "/rankings",
        params={"period": "7d", "category": "ai-agents", "page": 4},
    )

    assert first.status_code == 200
    assert first.json()["tracking_run_id"] == latest_run_id
    assert [item["github_id"] for item in first.json()["items"]] == list(range(1, 21))
    assert len(first.json()["items"][0]["categories"]) == 1
    assert first.json()["pagination"] == {
        "page": 1,
        "page_size": 20,
        "total_items": 41,
        "total_pages": 3,
    }
    assert [item["github_id"] for item in middle.json()["items"]] == list(range(21, 41))
    assert [item["github_id"] for item in last.json()["items"]] == [41]
    assert outside.json()["items"] == []


@pytest.mark.integration
def test_categories_include_active_zero_result_categories_in_display_order(
    client: TestClient,
) -> None:
    response = client.get("/categories")

    assert response.status_code == 200
    assert [category["slug"] for category in response.json()] == [
        "ai-agents",
        "skills",
        "mcp-servers",
        "dev-tools",
        "rag",
        "observability-eval",
    ]


@pytest.mark.integration
def test_repository_detail_uses_current_renamed_identity_and_shared_not_found_contract(
    api_database_url: str,
    client: TestClient,
) -> None:
    with psycopg.connect(api_database_url) as connection:
        _insert_repository(
            connection,
            501,
            owner="new-owner",
            name="new-name",
            topic_names=("rag",),
        )

    current = client.get("/repositories/NEW-OWNER/NEW-NAME")
    old = client.get("/repositories/old-owner/old-name")
    missing_history = client.get("/repositories/old-owner/old-name/star-history")

    assert current.status_code == 200
    assert current.json()["owner"] == "new-owner"
    assert current.json()["name"] == "new-name"
    assert current.json()["github_url"] == "https://github.com/new-owner/new-name"
    assert [category["slug"] for category in current.json()["categories"]] == ["rag"]
    assert old.status_code == missing_history.status_code == 404
    assert old.json() == missing_history.json() == {
        "detail": {
            "code": "repository_not_found",
            "message": "Repository not found",
        }
    }


@pytest.mark.integration
def test_star_history_enforces_window_marks_estimates_and_prefers_actual_points(
    api_database_url: str,
    client: TestClient,
) -> None:
    with psycopg.connect(api_database_url) as connection:
        repository_id = _insert_repository(connection, 601, name="history")
        _insert_snapshot(connection, repository_id, NOW - timedelta(days=31), 50)
        _insert_snapshot(connection, repository_id, NOW - timedelta(days=30), 70)
        _insert_snapshot(connection, repository_id, NOW - timedelta(days=1, hours=-1), 99)
        _insert_snapshot(connection, repository_id, NOW, 100)
        for offset in range(3):
            bucket_date = NOW.date() - timedelta(days=offset)
            connection.execute(
                """
                INSERT INTO bootstrap_star_history (
                    repository_id, date, stars_created, fetched_at
                ) VALUES (%s, %s, 1, %s)
                """,
                (repository_id, bucket_date, NOW),
            )

    response = client.get("/repositories/owner/history/star-history")

    assert response.status_code == 200
    points = response.json()["points"]
    assert all(
        datetime.fromisoformat(point["captured_at"]) >= NOW - timedelta(days=30)
        for point in points
    )
    assert [(point["star_count"], point["is_estimated"]) for point in points] == [
        (70, False),
        (98, True),
        (99, False),
        (100, False),
    ]
    actual_dates = {
        datetime.fromisoformat(point["captured_at"]).date()
        for point in points
        if not point["is_estimated"]
    }
    estimated_dates = {
        datetime.fromisoformat(point["captured_at"]).date()
        for point in points
        if point["is_estimated"]
    }
    assert actual_dates.isdisjoint(estimated_dates)


@pytest.mark.integration
def test_repository_with_no_recent_history_returns_empty_points(
    api_database_url: str,
    client: TestClient,
) -> None:
    with psycopg.connect(api_database_url) as connection:
        _insert_repository(connection, 701, name="empty-history")

    response = client.get("/repositories/owner/empty-history/star-history")

    assert response.status_code == 200
    assert response.json()["points"] == []
