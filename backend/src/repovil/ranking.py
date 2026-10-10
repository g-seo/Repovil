"""Momentum ranking calculation and atomic tracking-run publication."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal, cast

from psycopg import Connection

from repovil.bootstrap import calculate_bootstrap_baseline

RankingPeriod = Literal["24h", "7d", "30d"]
RANKING_PERIODS: tuple[RankingPeriod, ...] = ("24h", "7d", "30d")
BASELINE_TOLERANCE = timedelta(hours=6)
PUBLICATION_PERCENT = 95

_PERIOD_DURATION: dict[RankingPeriod, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


class RankingPublicationError(RuntimeError):
    """Raised when a finished run cannot be published as one complete unit."""


@dataclass(frozen=True, slots=True)
class StarSnapshot:
    """One actual star measurement used for baseline selection."""

    captured_at: datetime
    star_count: int


@dataclass(frozen=True, slots=True)
class Baseline:
    """Selected baseline for one period."""

    star_count: int
    captured_at: datetime
    is_estimated: bool


@dataclass(frozen=True, slots=True)
class RankingRecord:
    """One calculated ranking row before persistence."""

    repository_id: int
    github_id: int
    period: RankingPeriod
    score: float
    star_gain: int
    current_stars: int
    is_estimated: bool
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class StoredRanking:
    """A persisted ranking in the canonical display order."""

    repository_id: int
    github_id: int
    period: RankingPeriod
    score: float
    star_gain: int
    current_stars: int
    is_estimated: bool
    calculated_at: datetime


@dataclass(frozen=True, slots=True)
class PublicationResult:
    """Outcome of applying the publication policy to one tracking run."""

    run_id: int
    eligible: bool
    newly_published: bool
    published_at: datetime | None
    ranking_count: int


def _as_utc(value: datetime, *, label: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def publication_eligible(success_count: int, failed_count: int) -> bool:
    """Apply the 95% policy exactly, excluding skipped targets from the denominator."""
    if success_count < 0 or failed_count < 0:
        raise ValueError("publication counts must be non-negative")
    denominator = success_count + failed_count
    return denominator > 0 and success_count * 100 >= denominator * PUBLICATION_PERCENT


def select_actual_baseline(
    snapshots: Sequence[StarSnapshot],
    current_captured_at: datetime,
    period: RankingPeriod,
) -> Baseline | None:
    """Select the closest actual snapshot at/before target within six hours."""
    current_captured_at = _as_utc(current_captured_at, label="current captured_at")
    target_time = current_captured_at - _PERIOD_DURATION[period]
    earliest = target_time - BASELINE_TOLERANCE
    valid: list[StarSnapshot] = []
    for snapshot in snapshots:
        captured_at = _as_utc(snapshot.captured_at, label="snapshot captured_at")
        if earliest <= captured_at <= target_time:
            valid.append(StarSnapshot(captured_at, snapshot.star_count))
    if not valid:
        return None
    selected = max(valid, key=lambda snapshot: snapshot.captured_at)
    return Baseline(
        star_count=selected.star_count,
        captured_at=selected.captured_at,
        is_estimated=False,
    )


def calculate_repository_rankings(
    *,
    repository_id: int,
    github_id: int,
    current: StarSnapshot,
    previous_snapshots: Sequence[StarSnapshot],
    bootstrap_history: Mapping[date, int],
    calculated_at: datetime,
) -> tuple[RankingRecord, ...]:
    """Calculate all valid periods, preferring actual history over bootstrap data."""
    current_captured_at = _as_utc(current.captured_at, label="current captured_at")
    calculated_at = _as_utc(calculated_at, label="calculated_at")
    if current.star_count < 0:
        raise ValueError("current star count must be non-negative")

    rankings: list[RankingRecord] = []
    for period in RANKING_PERIODS:
        baseline = select_actual_baseline(previous_snapshots, current_captured_at, period)
        if baseline is None and period != "24h":
            estimated = calculate_bootstrap_baseline(
                current.star_count,
                current_captured_at,
                bootstrap_history,
                period,
            )
            if estimated is not None:
                baseline = Baseline(
                    star_count=estimated.star_count,
                    captured_at=estimated.target_time,
                    is_estimated=True,
                )
        if baseline is None:
            continue

        star_gain = current.star_count - baseline.star_count
        if star_gain <= 0:
            continue
        score = math.log((current.star_count + 1) / (baseline.star_count + 1))
        rankings.append(
            RankingRecord(
                repository_id=repository_id,
                github_id=github_id,
                period=period,
                score=score,
                star_gain=star_gain,
                current_stars=current.star_count,
                is_estimated=baseline.is_estimated,
                calculated_at=calculated_at,
            )
        )
    return tuple(rankings)


def sort_rankings(rankings: Sequence[RankingRecord]) -> tuple[RankingRecord, ...]:
    """Return rankings in the PRD's stable display order."""
    return tuple(
        sorted(
            rankings,
            key=lambda ranking: (-ranking.score, -ranking.star_gain, ranking.github_id),
        )
    )


def _calculate_run_rankings(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    success_count: int,
    calculated_at: datetime,
) -> tuple[RankingRecord, ...]:
    current_rows = connection.execute(
        """
        SELECT snapshots.repository_id, repositories.github_id,
               snapshots.captured_at, snapshots.star_count
        FROM star_snapshots AS snapshots
        JOIN tracking_run_items AS items
          ON items.tracking_run_id = snapshots.tracking_run_id
         AND items.repository_id = snapshots.repository_id
        JOIN repositories ON repositories.id = snapshots.repository_id
        WHERE snapshots.tracking_run_id = %s
          AND items.status = 'success'
        ORDER BY snapshots.repository_id
        """,
        (run_id,),
    ).fetchall()
    if len(current_rows) != success_count:
        raise RankingPublicationError(
            f"tracking run {run_id} has {success_count} successful items but "
            f"{len(current_rows)} current snapshots"
        )

    rankings: list[RankingRecord] = []
    for repository_id_value, github_id_value, captured_at_value, star_count_value in current_rows:
        repository_id = cast(int, repository_id_value)
        captured_at = cast(datetime, captured_at_value).astimezone(UTC)
        previous_rows = connection.execute(
            """
            SELECT captured_at, star_count
            FROM star_snapshots
            WHERE repository_id = %s
              AND tracking_run_id <> %s
              AND captured_at BETWEEN %s AND %s
            ORDER BY captured_at DESC
            """,
            (
                repository_id,
                run_id,
                captured_at - timedelta(days=30) - BASELINE_TOLERANCE,
                captured_at - timedelta(hours=24),
            ),
        ).fetchall()
        previous = tuple(
            StarSnapshot(cast(datetime, row[0]).astimezone(UTC), cast(int, row[1]))
            for row in previous_rows
        )
        bootstrap_rows = connection.execute(
            """
            SELECT date, stars_created
            FROM bootstrap_star_history
            WHERE repository_id = %s
            """,
            (repository_id,),
        ).fetchall()
        bootstrap_history = {
            cast(date, row[0]): cast(int, row[1]) for row in bootstrap_rows
        }
        rankings.extend(
            calculate_repository_rankings(
                repository_id=repository_id,
                github_id=cast(int, github_id_value),
                current=StarSnapshot(captured_at, cast(int, star_count_value)),
                previous_snapshots=previous,
                bootstrap_history=bootstrap_history,
                calculated_at=calculated_at,
            )
        )
    return sort_rankings(rankings)


def publish_rankings(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    calculated_at: datetime,
) -> PublicationResult:
    """Atomically store every ranking and mark one eligible run as published."""
    calculated_at = _as_utc(calculated_at, label="calculated_at")
    with connection.transaction():
        run_row = connection.execute(
            """
            SELECT status, success_count, failed_count, published_at
            FROM tracking_runs
            WHERE id = %s
            FOR UPDATE
            """,
            (run_id,),
        ).fetchone()
        if run_row is None:
            raise RankingPublicationError(f"tracking run {run_id} does not exist")
        status = cast(str, run_row[0])
        success_count = cast(int, run_row[1])
        failed_count = cast(int, run_row[2])
        published_at_value = cast(datetime | None, run_row[3])
        if status == "RUNNING":
            raise RankingPublicationError(f"tracking run {run_id} is still running")
        if published_at_value is not None:
            ranking_count_row = connection.execute(
                "SELECT count(*) FROM rankings WHERE tracking_run_id = %s",
                (run_id,),
            ).fetchone()
            ranking_count = cast(int, ranking_count_row[0]) if ranking_count_row else 0
            return PublicationResult(
                run_id,
                eligible=True,
                newly_published=False,
                published_at=published_at_value.astimezone(UTC),
                ranking_count=ranking_count,
            )

        eligible = status != "FAILED" and publication_eligible(success_count, failed_count)
        if not eligible:
            return PublicationResult(run_id, False, False, None, 0)

        rankings = _calculate_run_rankings(
            connection,
            run_id,
            success_count,
            calculated_at,
        )
        for ranking in rankings:
            connection.execute(
                """
                INSERT INTO rankings (
                    tracking_run_id, repository_id, period, score, star_gain,
                    current_stars, is_estimated, calculated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    run_id,
                    ranking.repository_id,
                    ranking.period,
                    ranking.score,
                    ranking.star_gain,
                    ranking.current_stars,
                    ranking.is_estimated,
                    ranking.calculated_at,
                ),
            )
        connection.execute(
            """
            UPDATE tracking_runs
            SET published_at = %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND published_at IS NULL
            """,
            (calculated_at, run_id),
        )
        return PublicationResult(
            run_id,
            eligible=True,
            newly_published=True,
            published_at=calculated_at,
            ranking_count=len(rankings),
        )


def rankings_for_category(
    connection: Connection[tuple[object, ...]],
    run_id: int,
    period: RankingPeriod,
    category_slug: str | None = None,
) -> tuple[StoredRanking, ...]:
    """Read one run in stable order, using EXISTS to avoid multi-topic duplicates."""
    rows = connection.execute(
        """
        SELECT rankings.repository_id, repositories.github_id, rankings.period,
               rankings.score, rankings.star_gain, rankings.current_stars,
               rankings.is_estimated, rankings.calculated_at
        FROM rankings
        JOIN repositories ON repositories.id = rankings.repository_id
        WHERE rankings.tracking_run_id = %s
          AND rankings.period = %s
          AND (
              CAST(%s AS text) IS NULL
              OR EXISTS (
                  SELECT 1
                  FROM repository_topics
                  JOIN category_topics
                    ON category_topics.topic_id = repository_topics.topic_id
                  JOIN categories ON categories.id = category_topics.category_id
                  JOIN topics ON topics.id = repository_topics.topic_id
                  WHERE repository_topics.repository_id = rankings.repository_id
                    AND categories.slug = %s
                    AND repository_topics.active
                    AND category_topics.active
                    AND categories.active
                    AND topics.active
              )
          )
        ORDER BY rankings.score DESC, rankings.star_gain DESC, repositories.github_id ASC
        """,
        (run_id, period, category_slug, category_slug),
    ).fetchall()
    return tuple(
        StoredRanking(
            repository_id=cast(int, row[0]),
            github_id=cast(int, row[1]),
            period=cast(RankingPeriod, row[2]),
            score=cast(float, row[3]),
            star_gain=cast(int, row[4]),
            current_stars=cast(int, row[5]),
            is_estimated=cast(bool, row[6]),
            calculated_at=cast(datetime, row[7]).astimezone(UTC),
        )
        for row in rows
    )
