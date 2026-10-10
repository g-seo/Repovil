"""Read-only FastAPI application backed exclusively by PostgreSQL."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Annotated, Literal, cast

import psycopg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from psycopg import Connection
from pydantic import BaseModel, ConfigDict

from repovil.db import check_connection, connect_database
from repovil.settings import Settings, get_settings

PAGE_SIZE = 20
HISTORY_WINDOW = timedelta(days=30)
RankingPeriod = Literal["24h", "7d", "30d"]
REPOSITORY_NOT_FOUND = {
    "code": "repository_not_found",
    "message": "Repository not found",
}


class ApiModel(BaseModel):
    """Base wire model with stable JSON serialization rules."""

    model_config = ConfigDict(extra="forbid")


class CategoryResponse(ApiModel):
    """One active category exposed to filters and repository views."""

    name: str
    slug: str
    display_order: int


class PaginationResponse(ApiModel):
    """Fixed-size, one-based ranking pagination metadata."""

    page: int
    page_size: int = PAGE_SIZE
    total_items: int
    total_pages: int


class RankingItemResponse(ApiModel):
    """One repository's immutable values from a published ranking run."""

    github_id: int
    owner: str
    name: str
    description: str | None
    github_url: str
    language: str | None
    current_stars: int
    score: float
    star_gain: int
    is_estimated: bool
    categories: list[CategoryResponse]


class RankingsResponse(ApiModel):
    """Published ranking collection or the explicit pre-publication state."""

    state: Literal["preparing", "ready"]
    tracking_run_id: int | None
    calculated_at: datetime | None
    period: RankingPeriod
    category: str | None
    items: list[RankingItemResponse]
    pagination: PaginationResponse


class RepositoryResponse(ApiModel):
    """Current stored repository metadata."""

    github_id: int
    owner: str
    name: str
    description: str | None
    github_url: str
    language: str | None
    current_stars: int
    status: Literal["bootstrap_pending", "active", "inactive"]
    discovered_at: datetime
    tracking_started_at: datetime | None
    categories: list[CategoryResponse]


class StarHistoryPointResponse(ApiModel):
    """An actual snapshot or a reconstructable bootstrap estimate."""

    captured_at: datetime
    star_count: int
    is_estimated: bool


class StarHistoryResponse(ApiModel):
    """Recent star history for one current repository identity."""

    github_id: int
    owner: str
    name: str
    points: list[StarHistoryPointResponse]


class HealthResponse(ApiModel):
    status: Literal["ok", "ready", "not_ready"]


def _database_connection(request: Request) -> Iterator[Connection[tuple[object, ...]]]:
    settings = cast(Settings, request.app.state.settings)
    with connect_database(str(settings.database_url)) as connection:
        yield connection


DatabaseConnection = Annotated[
    Connection[tuple[object, ...]],
    Depends(_database_connection),
]


def _active_categories(
    connection: Connection[tuple[object, ...]],
    repository_ids: Sequence[int],
) -> dict[int, list[CategoryResponse]]:
    if not repository_ids:
        return {}
    rows = connection.execute(
        """
        SELECT DISTINCT repository_topics.repository_id,
               categories.name, categories.slug, categories.display_order
        FROM repository_topics
        JOIN topics ON topics.id = repository_topics.topic_id
        JOIN category_topics ON category_topics.topic_id = topics.id
        JOIN categories ON categories.id = category_topics.category_id
        WHERE repository_topics.repository_id = ANY(%s)
          AND repository_topics.active
          AND topics.active
          AND category_topics.active
          AND categories.active
        ORDER BY repository_topics.repository_id, categories.display_order, categories.slug
        """,
        (list(repository_ids),),
    ).fetchall()
    categories_by_repository: dict[int, list[CategoryResponse]] = {
        repository_id: [] for repository_id in repository_ids
    }
    for repository_id_value, name, slug, display_order in rows:
        repository_id = cast(int, repository_id_value)
        categories_by_repository[repository_id].append(
            CategoryResponse(
                name=cast(str, name),
                slug=cast(str, slug),
                display_order=cast(int, display_order),
            )
        )
    return categories_by_repository


def _repository_row(
    connection: Connection[tuple[object, ...]],
    owner: str,
    name: str,
) -> tuple[object, ...]:
    row = connection.execute(
        """
        SELECT id, github_id, owner, name, description, github_url, language,
               current_stars, status, discovered_at, tracking_started_at,
               bootstrap_completed_at
        FROM repositories
        WHERE lower(owner) = lower(%s) AND lower(name) = lower(%s)
        ORDER BY id
        LIMIT 1
        """,
        (owner, name),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=REPOSITORY_NOT_FOUND)
    return row


def _validate_category(
    connection: Connection[tuple[object, ...]], category: str | None
) -> None:
    if category is None:
        return
    row = connection.execute(
        "SELECT 1 FROM categories WHERE slug = %s AND active",
        (category,),
    ).fetchone()
    if row is None:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "invalid_category",
                "message": f"Unknown active category: {category}",
            },
        )


def _bootstrap_points(
    rows: Sequence[tuple[object, ...]],
    *,
    anchor_at: datetime,
    anchor_stars: int,
    cutoff: datetime,
    actual_dates: set[date],
) -> list[StarHistoryPointResponse]:
    """Reverse contiguous daily creations from an actual measurement anchor."""
    daily = {cast(date, row[0]): cast(int, row[1]) for row in rows}
    anchor_date = anchor_at.date()
    points: list[StarHistoryPointResponse] = []
    for point_date in sorted(daily):
        captured_at = datetime.combine(point_date, time.min, tzinfo=UTC)
        if captured_at < cutoff or point_date > anchor_date or point_date in actual_dates:
            continue
        required_dates = (
            point_date + timedelta(days=offset)
            for offset in range(1, (anchor_date - point_date).days + 1)
        )
        counts: list[int] = []
        valid = True
        for required_date in required_dates:
            if required_date not in daily:
                valid = False
                break
            counts.append(daily[required_date])
        if not valid:
            continue
        star_count = anchor_stars - sum(counts)
        if star_count < 0:
            continue
        points.append(
            StarHistoryPointResponse(
                captured_at=captured_at,
                star_count=star_count,
                is_estimated=True,
            )
        )
    return points


def create_app(
    settings: Settings | None = None,
    *,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Create the API application with environment-backed settings."""
    application = FastAPI(title="Repovil", version="0.1.0")
    application.state.settings = settings or get_settings()
    application.state.clock = clock

    @application.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @application.get("/ready", response_model=HealthResponse)
    def ready(request: Request) -> HealthResponse | JSONResponse:
        configured = cast(Settings, request.app.state.settings)
        try:
            check_connection(str(configured.database_url))
        except (OSError, psycopg.Error):
            return JSONResponse(status_code=503, content={"status": "not_ready"})
        return HealthResponse(status="ready")

    @application.get("/categories", response_model=list[CategoryResponse])
    def categories(connection: DatabaseConnection) -> list[CategoryResponse]:
        rows = connection.execute(
            """
            SELECT name, slug, display_order
            FROM categories
            WHERE active
            ORDER BY display_order, slug
            """
        ).fetchall()
        return [
            CategoryResponse(
                name=cast(str, row[0]),
                slug=cast(str, row[1]),
                display_order=cast(int, row[2]),
            )
            for row in rows
        ]

    @application.get("/rankings", response_model=RankingsResponse)
    def rankings(
        connection: DatabaseConnection,
        period: RankingPeriod = "7d",
        category: str | None = None,
        page: Annotated[int, Query(ge=1)] = 1,
    ) -> RankingsResponse:
        _validate_category(connection, category)
        run_row = connection.execute(
            """
            SELECT id, published_at
            FROM tracking_runs
            WHERE published_at IS NOT NULL
            ORDER BY published_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if run_row is None:
            return RankingsResponse(
                state="preparing",
                tracking_run_id=None,
                calculated_at=None,
                period=period,
                category=category,
                items=[],
                pagination=PaginationResponse(page=page, total_items=0, total_pages=0),
            )

        run_id = cast(int, run_row[0])
        calculated_at = cast(datetime, run_row[1]).astimezone(UTC)
        category_clause = """
            AND EXISTS (
                SELECT 1
                FROM repository_topics
                JOIN topics ON topics.id = repository_topics.topic_id
                JOIN category_topics ON category_topics.topic_id = topics.id
                JOIN categories ON categories.id = category_topics.category_id
                WHERE repository_topics.repository_id = rankings.repository_id
                  AND categories.slug = %s
                  AND repository_topics.active
                  AND topics.active
                  AND category_topics.active
                  AND categories.active
            )
        """
        parameters: list[object] = [run_id, period]
        if category is not None:
            parameters.append(category)
        filter_sql = category_clause if category is not None else ""
        total_row = connection.execute(
            f"""
            SELECT count(*)
            FROM rankings
            WHERE tracking_run_id = %s AND period = %s
            {filter_sql}
            """,
            parameters,
        ).fetchone()
        total_items = cast(int, total_row[0]) if total_row is not None else 0
        rows = connection.execute(
            f"""
            SELECT rankings.repository_id, repositories.github_id,
                   repositories.owner, repositories.name, repositories.description,
                   repositories.github_url, repositories.language,
                   rankings.current_stars, rankings.score, rankings.star_gain,
                   rankings.is_estimated
            FROM rankings
            JOIN repositories ON repositories.id = rankings.repository_id
            WHERE rankings.tracking_run_id = %s AND rankings.period = %s
            {filter_sql}
            ORDER BY rankings.score DESC, rankings.star_gain DESC,
                     repositories.github_id ASC
            LIMIT %s OFFSET %s
            """,
            [*parameters, PAGE_SIZE, (page - 1) * PAGE_SIZE],
        ).fetchall()
        repository_ids = [cast(int, row[0]) for row in rows]
        categories_by_repository = _active_categories(connection, repository_ids)
        items = [
            RankingItemResponse(
                github_id=cast(int, row[1]),
                owner=cast(str, row[2]),
                name=cast(str, row[3]),
                description=cast(str | None, row[4]),
                github_url=cast(str, row[5]),
                language=cast(str | None, row[6]),
                current_stars=cast(int, row[7]),
                score=cast(float, row[8]),
                star_gain=cast(int, row[9]),
                is_estimated=cast(bool, row[10]),
                categories=categories_by_repository[cast(int, row[0])],
            )
            for row in rows
        ]
        return RankingsResponse(
            state="ready",
            tracking_run_id=run_id,
            calculated_at=calculated_at,
            period=period,
            category=category,
            items=items,
            pagination=PaginationResponse(
                page=page,
                total_items=total_items,
                total_pages=math.ceil(total_items / PAGE_SIZE),
            ),
        )

    @application.get(
        "/repositories/{owner}/{name}",
        response_model=RepositoryResponse,
    )
    def repository(
        owner: str,
        name: str,
        connection: DatabaseConnection,
    ) -> RepositoryResponse:
        row = _repository_row(connection, owner, name)
        repository_id = cast(int, row[0])
        return RepositoryResponse(
            github_id=cast(int, row[1]),
            owner=cast(str, row[2]),
            name=cast(str, row[3]),
            description=cast(str | None, row[4]),
            github_url=cast(str, row[5]),
            language=cast(str | None, row[6]),
            current_stars=cast(int, row[7]),
            status=cast(Literal["bootstrap_pending", "active", "inactive"], row[8]),
            discovered_at=cast(datetime, row[9]).astimezone(UTC),
            tracking_started_at=(
                cast(datetime, row[10]).astimezone(UTC) if row[10] is not None else None
            ),
            categories=_active_categories(connection, [repository_id])[repository_id],
        )

    @application.get(
        "/repositories/{owner}/{name}/star-history",
        response_model=StarHistoryResponse,
    )
    def star_history(
        owner: str,
        name: str,
        request: Request,
        connection: DatabaseConnection,
    ) -> StarHistoryResponse:
        row = _repository_row(connection, owner, name)
        repository_id = cast(int, row[0])
        now = cast(Callable[[], datetime], request.app.state.clock)()
        if now.tzinfo is None or now.utcoffset() is None:
            raise RuntimeError("API clock must return a timezone-aware datetime")
        now = now.astimezone(UTC)
        cutoff = now - HISTORY_WINDOW
        actual_rows = connection.execute(
            """
            SELECT captured_at, star_count
            FROM star_snapshots
            WHERE repository_id = %s AND captured_at >= %s AND captured_at <= %s
            ORDER BY captured_at, id
            """,
            (repository_id, cutoff, now),
        ).fetchall()
        actual_points = [
            StarHistoryPointResponse(
                captured_at=cast(datetime, actual[0]).astimezone(UTC),
                star_count=cast(int, actual[1]),
                is_estimated=False,
            )
            for actual in actual_rows
        ]
        bootstrap_rows = connection.execute(
            """
            SELECT date, stars_created
            FROM bootstrap_star_history
            WHERE repository_id = %s AND date >= %s AND date <= %s
            ORDER BY date
            """,
            (repository_id, cutoff.date(), now.date()),
        ).fetchall()

        if actual_points:
            anchor_at = actual_points[-1].captured_at
            anchor_stars = actual_points[-1].star_count
        else:
            completed_at = cast(datetime | None, row[11])
            anchor_at = completed_at.astimezone(UTC) if completed_at is not None else now
            anchor_stars = cast(int, row[7])
        estimated_points = _bootstrap_points(
            bootstrap_rows,
            anchor_at=anchor_at,
            anchor_stars=anchor_stars,
            cutoff=cutoff,
            actual_dates={point.captured_at.date() for point in actual_points},
        )
        points = sorted(
            [*estimated_points, *actual_points],
            key=lambda point: point.captured_at,
        )
        return StarHistoryResponse(
            github_id=cast(int, row[1]),
            owner=cast(str, row[2]),
            name=cast(str, row[3]),
            points=points,
        )

    return application


app = create_app()


def main() -> None:
    """Run the API server for local development."""
    uvicorn.run("repovil.api:app", host="0.0.0.0", port=8000)

