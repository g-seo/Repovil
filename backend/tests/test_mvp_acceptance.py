"""End-to-end acceptance coverage for the MVP's controlled data pipeline."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient
from pydantic import PostgresDsn
from test_migrations import _alembic_config

from alembic import command
from repovil.api import create_app
from repovil.bootstrap import run_bootstrap
from repovil.category_sync import sync_categories
from repovil.discovery import run_discovery
from repovil.github_client import (
    RateLimit,
    Repository,
    RepositoryResult,
    RepositoryStats,
    RequestMetadata,
    SearchRepositoriesPage,
    StarHistoryPage,
    StarHistoryWeek,
)
from repovil.settings import Settings
from repovil.tracking import run_tracking

BOOTSTRAP_AT = datetime(2026, 10, 12, tzinfo=UTC)
SECOND_TRACKING_AT = BOOTSTRAP_AT + timedelta(days=1)
REQUEST = RequestMetadata(
    status_code=200,
    retry_count=0,
    duration_ms=1,
    rate_limit=RateLimit(limit=5_000, remaining=4_999, reset_at=2_000, resource="core"),
)


def _history_weeks() -> tuple[StarHistoryWeek, ...]:
    first_sunday = BOOTSTRAP_AT.date() - timedelta(
        days=(BOOTSTRAP_AT.date().weekday() + 1) % 7
    )
    return tuple(
        StarHistoryWeek(
            week=int(
                datetime.combine(
                    first_sunday - timedelta(days=7 * offset), time.min, tzinfo=UTC
                ).timestamp()
            ),
            total=7,
            days=(1, 1, 1, 1, 1, 1, 1),
        )
        for offset in range(6)
    )


class PipelineClient:
    """Deterministic GitHubClient-compatible fixture for the full worker sequence."""

    repository = Repository(
        github_id=4242,
        owner="acme",
        name="momentum",
        full_name="acme/momentum",
        github_url="https://github.com/acme/momentum",
        description="An eligible AI agent project",
        language="Python",
        stars=300,
        topics=("ai-agent",),
        visibility="public",
        fork=False,
        archived=False,
    )

    def __init__(self) -> None:
        # Bootstrap, first actual measurement, then a measurement 24 hours later.
        self._star_counts = iter((300, 300, 305))
        self.search_topics: list[str] = []

    def search_repositories(
        self,
        topic: str,
        *,
        min_stars: int = 200,
        max_stars: int | None = None,
        page: int = 1,
        per_page: int = 100,
    ) -> SearchRepositoriesPage:
        assert min_stars == 200
        assert max_stars is None
        assert page == 1
        assert per_page == 100
        self.search_topics.append(topic)
        repositories = (self.repository,) if topic == "ai-agent" else ()
        return SearchRepositoriesPage(
            total_count=len(repositories),
            incomplete_results=False,
            repositories=repositories,
            page=page,
            per_page=per_page,
            request=REQUEST,
        )

    def get_repository_stats(self, owner: str, name: str) -> RepositoryStats:
        assert (owner, name) == ("acme", "momentum")
        return RepositoryStats(star_count=next(self._star_counts), request=REQUEST)

    def get_star_history(
        self,
        owner: str,
        name: str,
        *,
        page: int = 1,
        per_page: int = 30,
    ) -> StarHistoryPage:
        assert (owner, name) == ("acme", "momentum")
        assert (page, per_page) == (1, 30)
        return StarHistoryPage(
            weeks=_history_weeks(),
            page=page,
            per_page=per_page,
            request=REQUEST,
        )

    def get_repository(self, owner: str, name: str) -> RepositoryResult:
        assert (owner, name) == ("acme", "momentum")
        return RepositoryResult(repository=self.repository, request=REQUEST)


@pytest.fixture
def acceptance_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    return postgres_schema_url


@pytest.mark.integration
def test_empty_database_pipeline_publishes_actual_and_estimated_rankings(
    acceptance_database_url: str,
) -> None:
    """Exercise the MVP workflow without a live GitHub request or stale data."""
    sync = sync_categories(acceptance_database_url)
    client = PipelineClient()

    first_discovery = run_discovery(
        acceptance_database_url,
        client,
        clock=lambda: BOOTSTRAP_AT,
    )
    repeated_discovery = run_discovery(
        acceptance_database_url,
        client,
        clock=lambda: BOOTSTRAP_AT,
    )
    bootstrap = run_bootstrap(
        acceptance_database_url,
        client,
        clock=lambda: BOOTSTRAP_AT,
    )
    first_tracking = run_tracking(
        acceptance_database_url,
        client,
        scheduled_at=BOOTSTRAP_AT,
        clock=lambda: BOOTSTRAP_AT,
    )
    refresh = run_bootstrap(
        acceptance_database_url,
        client,
        clock=lambda: SECOND_TRACKING_AT,
        refresh_active=True,
    )
    second_tracking = run_tracking(
        acceptance_database_url,
        client,
        scheduled_at=SECOND_TRACKING_AT,
        clock=lambda: SECOND_TRACKING_AT,
    )

    assert (sync.category_count, sync.topic_count) == (6, 21)
    assert first_discovery.status == repeated_discovery.status == "COMPLETED"
    assert (first_discovery.discovered_count, first_discovery.added_count) == (1, 1)
    assert (repeated_discovery.discovered_count, repeated_discovery.added_count) == (1, 0)
    assert len(client.search_topics) == 42
    assert (bootstrap.processed_count, bootstrap.success_count, bootstrap.failed_count) == (1, 1, 0)
    assert (refresh.processed_count, refresh.success_count, refresh.failed_count) == (1, 1, 0)
    assert first_tracking.published_at == BOOTSTRAP_AT
    assert second_tracking.published_at == SECOND_TRACKING_AT
    assert second_tracking.ranking_count == 3

    with psycopg.connect(acceptance_database_url) as connection:
        previous_source = connection.execute(
            """
            SELECT stars_created, fetched_at
            FROM bootstrap_star_history
            WHERE date = %s
            """,
            (BOOTSTRAP_AT.date(),),
        ).fetchone()
        refreshed_source = connection.execute(
            """
            SELECT stars_created, fetched_at
            FROM bootstrap_star_history
            WHERE date = %s
            """,
            (SECOND_TRACKING_AT.date(),),
        ).fetchone()
        repository_stars = connection.execute(
            "SELECT current_stars FROM repositories WHERE github_id = 4242"
        ).fetchone()
    assert previous_source == (1, BOOTSTRAP_AT)
    assert refreshed_source == (1, SECOND_TRACKING_AT)
    assert repository_stars == (305,)

    settings = Settings(database_url=PostgresDsn(acceptance_database_url))
    with TestClient(create_app(settings, clock=lambda: SECOND_TRACKING_AT)) as api:
        assert api.get("/health").json() == {"status": "ok"}
        assert api.get("/ready").json() == {"status": "ready"}
        assert len(api.get("/categories").json()) == 6

        ranking_24h = api.get("/rankings?period=24h&category=ai-agents")
        ranking_7d = api.get("/rankings?period=7d")
        ranking_30d = api.get("/rankings?period=30d")
        assert ranking_24h.status_code == ranking_7d.status_code == ranking_30d.status_code == 200
        assert ranking_24h.json()["state"] == "ready"
        assert ranking_24h.json()["tracking_run_id"] == second_tracking.run_id
        assert ranking_24h.json()["items"][0]["star_gain"] == 5
        assert ranking_24h.json()["items"][0]["is_estimated"] is False
        assert ranking_7d.json()["items"][0]["is_estimated"] is True
        assert ranking_30d.json()["items"][0]["is_estimated"] is True

        detail = api.get("/repositories/acme/momentum")
        history = api.get("/repositories/acme/momentum/star-history")
        assert detail.status_code == history.status_code == 200
        assert detail.json()["current_stars"] == 305
        points = history.json()["points"]
        assert any(point["is_estimated"] for point in points)
        actual_points = [point for point in points if not point["is_estimated"]]
        assert [point["star_count"] for point in actual_points] == [300, 305]
