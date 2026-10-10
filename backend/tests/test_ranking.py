from __future__ import annotations

import math
from datetime import UTC, date, datetime, timedelta
from typing import cast

import psycopg
import pytest
from test_category_sync import DEFAULT_CONFIG
from test_migrations import _alembic_config

from alembic import command
from repovil.category_sync import sync_categories
from repovil.ranking import (
    RankingRecord,
    StarSnapshot,
    calculate_repository_rankings,
    publication_eligible,
    publish_rankings,
    rankings_for_category,
    select_actual_baseline,
    sort_rankings,
)

NOW = datetime(2026, 10, 11, 12, tzinfo=UTC)


@pytest.fixture
def ranking_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    sync_categories(postgres_schema_url, DEFAULT_CONFIG)
    return postgres_schema_url


def _daily_counts(*, count: int = 1) -> dict[date, int]:
    return {NOW.date() - timedelta(days=offset): count for offset in range(30)}


@pytest.mark.parametrize(
    ("offset", "expected"),
    [
        (timedelta(0), True),
        (timedelta(microseconds=1), True),
        (timedelta(hours=6), True),
        (timedelta(hours=6, microseconds=1), False),
    ],
)
def test_actual_baseline_target_and_six_hour_boundaries(
    offset: timedelta,
    expected: bool,
) -> None:
    target = NOW - timedelta(hours=24)
    baseline = select_actual_baseline(
        [StarSnapshot(target - offset, 900)],
        NOW,
        "24h",
    )

    assert (baseline is not None) is expected


def test_actual_baseline_uses_closest_snapshot_at_or_before_target() -> None:
    target = NOW - timedelta(days=7)
    baseline = select_actual_baseline(
        [
            StarSnapshot(target - timedelta(hours=4), 890),
            StarSnapshot(target + timedelta(microseconds=1), 999),
            StarSnapshot(target - timedelta(minutes=1), 900),
        ],
        NOW,
        "7d",
    )

    assert baseline is not None
    assert (baseline.captured_at, baseline.star_count) == (
        target - timedelta(minutes=1),
        900,
    )
    assert baseline.is_estimated is False


def test_bootstrap_is_only_used_for_7d_and_30d_and_invalid_estimates_are_excluded() -> None:
    rankings = calculate_repository_rankings(
        repository_id=1,
        github_id=101,
        current=StarSnapshot(NOW, 1_000),
        previous_snapshots=(),
        bootstrap_history=_daily_counts(),
        calculated_at=NOW,
    )

    assert [(ranking.period, ranking.star_gain, ranking.is_estimated) for ranking in rankings] == [
        ("7d", 7, True),
        ("30d", 30, True),
    ]

    invalid = calculate_repository_rankings(
        repository_id=1,
        github_id=101,
        current=StarSnapshot(NOW, 5),
        previous_snapshots=(),
        bootstrap_history=_daily_counts(),
        calculated_at=NOW,
    )
    assert invalid == ()


def test_actual_baseline_wins_over_bootstrap_and_nonpositive_gain_is_not_replaced() -> None:
    target = NOW - timedelta(days=7)
    rankings = calculate_repository_rankings(
        repository_id=1,
        github_id=101,
        current=StarSnapshot(NOW, 1_000),
        previous_snapshots=[StarSnapshot(target, 990)],
        bootstrap_history=_daily_counts(),
        calculated_at=NOW,
    )

    by_period = {ranking.period: ranking for ranking in rankings}
    assert "24h" not in by_period
    assert by_period["7d"].star_gain == 10
    assert by_period["7d"].is_estimated is False
    assert by_period["30d"].is_estimated is True

    zero_actual = calculate_repository_rankings(
        repository_id=1,
        github_id=101,
        current=StarSnapshot(NOW, 1_000),
        previous_snapshots=[StarSnapshot(target, 1_000)],
        bootstrap_history=_daily_counts(),
        calculated_at=NOW,
    )
    assert "7d" not in {ranking.period for ranking in zero_actual}


@pytest.mark.parametrize(
    ("baseline_stars", "expected_gain"),
    [(1_001, None), (1_000, None), (900, 100)],
)
def test_star_gain_filter_and_score(
    baseline_stars: int,
    expected_gain: int | None,
) -> None:
    rankings = calculate_repository_rankings(
        repository_id=1,
        github_id=101,
        current=StarSnapshot(NOW, 1_000),
        previous_snapshots=[
            StarSnapshot(NOW - timedelta(hours=24), baseline_stars),
        ],
        bootstrap_history={},
        calculated_at=NOW,
    )

    if expected_gain is None:
        assert rankings == ()
    else:
        assert len(rankings) == 1
        assert rankings[0].star_gain == expected_gain
        assert rankings[0].score == pytest.approx(math.log(1001 / 901))


def _ranking(github_id: int, score: float, gain: int) -> RankingRecord:
    return RankingRecord(
        repository_id=github_id,
        github_id=github_id,
        period="24h",
        score=score,
        star_gain=gain,
        current_stars=1_000,
        is_estimated=False,
        calculated_at=NOW,
    )


def test_ranking_order_uses_score_then_gain_then_github_id() -> None:
    rankings = [
        _ranking(300, 0.5, 10),
        _ranking(200, 0.5, 20),
        _ranking(100, 0.5, 20),
        _ranking(400, 0.6, 1),
    ]

    assert [ranking.github_id for ranking in sort_rankings(rankings)] == [400, 100, 200, 300]


@pytest.mark.parametrize(
    ("success", "failed", "expected"),
    [
        (9_499, 501, False),
        (19, 1, True),
        (1, 0, True),
        (0, 0, False),
        (0, 5, False),
    ],
)
def test_publication_threshold_boundaries(
    success: int,
    failed: int,
    expected: bool,
) -> None:
    assert publication_eligible(success, failed) is expected


def _insert_repository(
    connection: psycopg.Connection[tuple[object, ...]],
    github_id: int = 101,
) -> int:
    row = connection.execute(
        """
        INSERT INTO repositories (
            github_id, owner, name, github_url, current_stars, status,
            discovered_at, tracking_started_at
        )
        VALUES (%s, 'owner', %s, %s, 1000, 'active', %s, %s)
        RETURNING id
        """,
        (
            github_id,
            f"repo-{github_id}",
            f"https://github.com/owner/repo-{github_id}",
            NOW - timedelta(days=31),
            NOW - timedelta(days=30),
        ),
    ).fetchone()
    assert row is not None
    return cast(int, row[0])


def _insert_snapshot_run(
    connection: psycopg.Connection[tuple[object, ...]],
    repository_id: int,
    captured_at: datetime,
    star_count: int,
    *,
    published_at: datetime | None = None,
) -> int:
    run_row = connection.execute(
        """
        INSERT INTO tracking_runs (
            scheduled_at, started_at, finished_at, total_count, success_count,
            failed_count, skipped_count, status, published_at
        )
        VALUES (%s, %s, %s, 1, 1, 0, 0, 'COMPLETED', %s)
        RETURNING id
        """,
        (captured_at, captured_at, captured_at, published_at),
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
    return run_id


@pytest.mark.integration
def test_publication_persists_actual_and_bootstrap_rankings_atomically(
    ranking_database_url: str,
) -> None:
    with psycopg.connect(ranking_database_url) as connection:
        repository_id = _insert_repository(connection)
        _insert_snapshot_run(connection, repository_id, NOW - timedelta(hours=24), 980)
        current_run_id = _insert_snapshot_run(connection, repository_id, NOW, 1_000)
        for bucket_date, count in _daily_counts().items():
            connection.execute(
                """
                INSERT INTO bootstrap_star_history (
                    repository_id, date, stars_created, fetched_at
                ) VALUES (%s, %s, %s, %s)
                """,
                (repository_id, bucket_date, count, NOW),
            )
        connection.commit()

        result = publish_rankings(connection, current_run_id, NOW)

        stored = connection.execute(
            """
            SELECT period, star_gain, current_stars, is_estimated, calculated_at
            FROM rankings
            WHERE tracking_run_id = %s
            ORDER BY CASE period WHEN '24h' THEN 1 WHEN '7d' THEN 2 ELSE 3 END
            """,
            (current_run_id,),
        ).fetchall()
        published_at = connection.execute(
            "SELECT published_at FROM tracking_runs WHERE id = %s",
            (current_run_id,),
        ).fetchone()

    assert result.newly_published is True
    assert result.ranking_count == 3
    assert stored == [
        ("24h", 20, 1_000, False, NOW),
        ("7d", 7, 1_000, True, NOW),
        ("30d", 30, 1_000, True, NOW),
    ]
    assert published_at == (NOW,)


@pytest.mark.integration
def test_zero_denominator_and_below_threshold_do_not_publish(
    ranking_database_url: str,
) -> None:
    with psycopg.connect(ranking_database_url) as connection:
        empty_run = connection.execute(
            """
            INSERT INTO tracking_runs (
                scheduled_at, started_at, finished_at, status
            ) VALUES (%s, %s, %s, 'COMPLETED') RETURNING id
            """,
            (NOW, NOW, NOW),
        ).fetchone()
        below_run = connection.execute(
            """
            INSERT INTO tracking_runs (
                scheduled_at, started_at, finished_at, total_count,
                success_count, failed_count, status
            ) VALUES (%s, %s, %s, 10000, 9499, 501, 'PARTIAL') RETURNING id
            """,
            (NOW + timedelta(hours=6), NOW, NOW, ),
        ).fetchone()
        assert empty_run is not None and below_run is not None
        connection.commit()

        empty = publish_rankings(connection, cast(int, empty_run[0]), NOW)
        below = publish_rankings(connection, cast(int, below_run[0]), NOW)

        published = connection.execute(
            "SELECT count(*) FROM tracking_runs WHERE published_at IS NOT NULL"
        ).fetchone()

    assert empty.eligible is False
    assert below.eligible is False
    assert published == (0,)


@pytest.mark.integration
def test_partial_run_at_exactly_95_percent_is_published(
    ranking_database_url: str,
) -> None:
    with psycopg.connect(ranking_database_url) as connection:
        run_row = connection.execute(
            """
            INSERT INTO tracking_runs (
                scheduled_at, started_at, finished_at, total_count,
                success_count, failed_count, status
            ) VALUES (%s, %s, %s, 20, 19, 1, 'PARTIAL') RETURNING id
            """,
            (NOW, NOW, NOW),
        ).fetchone()
        assert run_row is not None
        run_id = cast(int, run_row[0])
        for github_id in range(1, 21):
            repository_id = _insert_repository(connection, github_id)
            item_status = "success" if github_id <= 19 else "failed"
            connection.execute(
                """
                INSERT INTO tracking_run_items (
                    tracking_run_id, repository_id, status
                ) VALUES (%s, %s, %s)
                """,
                (run_id, repository_id, item_status),
            )
            if item_status == "success":
                connection.execute(
                    """
                    INSERT INTO star_snapshots (
                        tracking_run_id, repository_id, captured_at, star_count
                    ) VALUES (%s, %s, %s, 1000)
                    """,
                    (run_id, repository_id, NOW),
                )
        connection.commit()

        result = publish_rankings(connection, run_id, NOW)
        published_at = connection.execute(
            "SELECT published_at FROM tracking_runs WHERE id = %s",
            (run_id,),
        ).fetchone()

    assert result.eligible is True
    assert result.newly_published is True
    assert result.ranking_count == 0
    assert published_at == (NOW,)


@pytest.mark.integration
def test_publication_failure_rolls_back_new_rankings_and_preserves_previous_run(
    ranking_database_url: str,
) -> None:
    with psycopg.connect(ranking_database_url) as connection:
        repository_id = _insert_repository(connection)
        previous_run_id = _insert_snapshot_run(
            connection,
            repository_id,
            NOW - timedelta(hours=24),
            900,
            published_at=NOW - timedelta(hours=23),
        )
        connection.execute(
            """
            INSERT INTO rankings (
                tracking_run_id, repository_id, period, score, star_gain,
                current_stars, is_estimated, calculated_at
            ) VALUES (%s, %s, '24h', 0.1, 10, 900, false, %s)
            """,
            (previous_run_id, repository_id, NOW - timedelta(hours=23)),
        )
        current_run_id = _insert_snapshot_run(connection, repository_id, NOW, 1_000)
        connection.execute(
            """
            CREATE FUNCTION reject_ranking_publication() RETURNS trigger AS $$
            BEGIN
                IF OLD.published_at IS NULL AND NEW.published_at IS NOT NULL THEN
                    RAISE EXCEPTION 'forced publication failure';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql
            """
        )
        connection.execute(
            """
            CREATE TRIGGER reject_ranking_publication
            BEFORE UPDATE ON tracking_runs
            FOR EACH ROW EXECUTE FUNCTION reject_ranking_publication()
            """
        )
        connection.commit()

        with pytest.raises(psycopg.errors.RaiseException, match="forced publication failure"):
            publish_rankings(connection, current_run_id, NOW)

        rows = connection.execute(
            """
            SELECT tracking_run_id, count(*)
            FROM rankings
            GROUP BY tracking_run_id
            ORDER BY tracking_run_id
            """
        ).fetchall()
        publication_rows = connection.execute(
            """
            SELECT id, published_at FROM tracking_runs
            WHERE id IN (%s, %s) ORDER BY id
            """,
            (previous_run_id, current_run_id),
        ).fetchall()

    assert rows == [(previous_run_id, 1)]
    assert publication_rows == [
        (previous_run_id, NOW - timedelta(hours=23)),
        (current_run_id, None),
    ]


@pytest.mark.integration
def test_category_join_deduplicates_repository_with_multiple_matching_topics(
    ranking_database_url: str,
) -> None:
    with psycopg.connect(ranking_database_url) as connection:
        repository_id = _insert_repository(connection)
        connection.execute(
            """
            INSERT INTO repository_topics (repository_id, topic_id)
            SELECT %s, id FROM topics WHERE name IN ('ai-agent', 'ai-agents')
            """,
            (repository_id,),
        )
        _insert_snapshot_run(connection, repository_id, NOW - timedelta(hours=24), 900)
        current_run_id = _insert_snapshot_run(connection, repository_id, NOW, 1_000)
        connection.commit()

        publish_rankings(connection, current_run_id, NOW)
        rankings = rankings_for_category(connection, current_run_id, "24h", "ai-agents")

    assert len(rankings) == 1
    assert rankings[0].repository_id == repository_id
    assert rankings[0].star_gain == 100
