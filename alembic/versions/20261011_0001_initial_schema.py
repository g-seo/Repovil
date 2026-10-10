"""Create the MVP persistence schema.

Revision ID: 20261011_0001
Revises:
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20261011_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> tuple[sa.Column[sa.DateTime], sa.Column[sa.DateTime]]:
    return (
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )


def upgrade() -> None:
    op.create_table(
        "categories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("display_order", sa.Integer(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint("length(name) > 0", name="ck_categories_name_not_empty"),
        sa.CheckConstraint("length(slug) > 0", name="ck_categories_slug_not_empty"),
        sa.CheckConstraint("display_order > 0", name="ck_categories_display_order_positive"),
        sa.UniqueConstraint("name", name="uq_categories_name"),
        sa.UniqueConstraint("slug", name="uq_categories_slug"),
    )
    op.create_index(
        "ix_categories_active_display_order",
        "categories",
        ["active", "display_order"],
    )

    op.create_table(
        "topics",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
        sa.CheckConstraint("length(name) > 0", name="ck_topics_name_not_empty"),
        sa.UniqueConstraint("name", name="uq_topics_name"),
    )

    op.create_table(
        "category_topics",
        sa.Column(
            "category_id",
            sa.BigInteger(),
            sa.ForeignKey("categories.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            sa.BigInteger(),
            sa.ForeignKey("topics.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index(
        "ix_category_topics_topic_id",
        "category_topics",
        ["topic_id", "category_id"],
    )

    op.create_table(
        "repositories",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("github_id", sa.BigInteger(), nullable=False),
        sa.Column("owner", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("github_url", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=True),
        sa.Column("current_stars", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'bootstrap_pending'"),
        ),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("tracking_started_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("github_id > 0", name="ck_repositories_github_id_positive"),
        sa.CheckConstraint("length(owner) > 0", name="ck_repositories_owner_not_empty"),
        sa.CheckConstraint("length(name) > 0", name="ck_repositories_name_not_empty"),
        sa.CheckConstraint("length(github_url) > 0", name="ck_repositories_url_not_empty"),
        sa.CheckConstraint("current_stars >= 0", name="ck_repositories_stars_nonnegative"),
        sa.CheckConstraint(
            "status IN ('bootstrap_pending', 'active', 'inactive')",
            name="ck_repositories_status",
        ),
        sa.UniqueConstraint("github_id", name="uq_repositories_github_id"),
    )
    op.create_index("ix_repositories_owner_name", "repositories", ["owner", "name"])
    op.create_index("ix_repositories_status", "repositories", ["status"])

    op.create_table(
        "repository_topics",
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "topic_id",
            sa.BigInteger(),
            sa.ForeignKey("topics.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        *_timestamps(),
    )
    op.create_index(
        "ix_repository_topics_topic_id",
        "repository_topics",
        ["topic_id", "repository_id"],
    )

    op.create_table(
        "discovery_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("added_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "failed_ranges",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        *_timestamps(),
        sa.CheckConstraint(
            "discovered_count >= 0", name="ck_discovery_runs_discovered_nonnegative"
        ),
        sa.CheckConstraint("added_count >= 0", name="ck_discovery_runs_added_nonnegative"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_discovery_runs_status",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(failed_ranges) = 'array'",
            name="ck_discovery_runs_failed_ranges_array",
        ),
    )

    op.create_table(
        "tracking_runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("total_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("total_count >= 0", name="ck_tracking_runs_total_nonnegative"),
        sa.CheckConstraint("success_count >= 0", name="ck_tracking_runs_success_nonnegative"),
        sa.CheckConstraint("failed_count >= 0", name="ck_tracking_runs_failed_nonnegative"),
        sa.CheckConstraint("skipped_count >= 0", name="ck_tracking_runs_skipped_nonnegative"),
        sa.CheckConstraint(
            "status IN ('RUNNING', 'COMPLETED', 'PARTIAL', 'FAILED')",
            name="ck_tracking_runs_status",
        ),
        sa.UniqueConstraint("scheduled_at", name="uq_tracking_runs_scheduled_at"),
    )
    op.create_index(
        "ix_tracking_runs_published_at",
        "tracking_runs",
        [sa.text("published_at DESC")],
    )

    op.create_table(
        "tracking_run_items",
        sa.Column(
            "tracking_run_id",
            sa.BigInteger(),
            sa.ForeignKey("tracking_runs.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column("error_type", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IS NULL OR status IN ('success', 'failed', 'skipped')",
            name="ck_tracking_run_items_status",
        ),
        sa.CheckConstraint("retry_count >= 0", name="ck_tracking_run_items_retry_nonnegative"),
        sa.CheckConstraint(
            "duration_ms IS NULL OR duration_ms >= 0",
            name="ck_tracking_run_items_duration_nonnegative",
        ),
        sa.CheckConstraint(
            "response_status IS NULL OR response_status BETWEEN 100 AND 599",
            name="ck_tracking_run_items_response_status",
        ),
    )
    op.create_index(
        "ix_tracking_run_items_repository_id",
        "tracking_run_items",
        ["repository_id", "tracking_run_id"],
    )

    op.create_table(
        "star_snapshots",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tracking_run_id", sa.BigInteger(), nullable=False),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("star_count", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracking_run_id", "repository_id"],
            ["tracking_run_items.tracking_run_id", "tracking_run_items.repository_id"],
            name="fk_star_snapshots_run_item",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tracking_run_id",
            "repository_id",
            name="uq_star_snapshots_run_repository",
        ),
        sa.CheckConstraint("star_count >= 0", name="ck_star_snapshots_count_nonnegative"),
    )
    op.create_index(
        "ix_star_snapshots_repository_captured_at",
        "star_snapshots",
        ["repository_id", sa.text("captured_at DESC")],
    )

    op.create_table(
        "bootstrap_star_history",
        sa.Column(
            "repository_id",
            sa.BigInteger(),
            sa.ForeignKey("repositories.id", ondelete="RESTRICT"),
            primary_key=True,
        ),
        sa.Column("date", sa.Date(), primary_key=True),
        sa.Column("stars_created", sa.Integer(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "stars_created >= 0", name="ck_bootstrap_star_history_stars_nonnegative"
        ),
    )

    op.create_table(
        "rankings",
        sa.Column("tracking_run_id", sa.BigInteger(), primary_key=True),
        sa.Column("repository_id", sa.BigInteger(), primary_key=True),
        sa.Column("period", sa.Text(), primary_key=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("star_gain", sa.Integer(), nullable=False),
        sa.Column("current_stars", sa.Integer(), nullable=False),
        sa.Column("is_estimated", sa.Boolean(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tracking_run_id", "repository_id"],
            ["star_snapshots.tracking_run_id", "star_snapshots.repository_id"],
            name="fk_rankings_snapshot",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("period IN ('24h', '7d', '30d')", name="ck_rankings_period"),
        sa.CheckConstraint("star_gain > 0", name="ck_rankings_star_gain_positive"),
        sa.CheckConstraint("current_stars >= 0", name="ck_rankings_stars_nonnegative"),
    )


def downgrade() -> None:
    op.drop_table("rankings")
    op.drop_table("bootstrap_star_history")
    op.drop_index("ix_star_snapshots_repository_captured_at", table_name="star_snapshots")
    op.drop_table("star_snapshots")
    op.drop_index("ix_tracking_run_items_repository_id", table_name="tracking_run_items")
    op.drop_table("tracking_run_items")
    op.drop_index("ix_tracking_runs_published_at", table_name="tracking_runs")
    op.drop_table("tracking_runs")
    op.drop_table("discovery_runs")
    op.drop_index("ix_repository_topics_topic_id", table_name="repository_topics")
    op.drop_table("repository_topics")
    op.drop_index("ix_repositories_status", table_name="repositories")
    op.drop_index("ix_repositories_owner_name", table_name="repositories")
    op.drop_table("repositories")
    op.drop_index("ix_category_topics_topic_id", table_name="category_topics")
    op.drop_table("category_topics")
    op.drop_table("topics")
    op.drop_index("ix_categories_active_display_order", table_name="categories")
    op.drop_table("categories")
