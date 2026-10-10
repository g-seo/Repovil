"""Record historical bootstrap retry and completion state.

Revision ID: 20261011_0002
Revises: 20261011_0001
Create Date: 2026-10-11
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20261011_0002"
down_revision: str | None = "20261011_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "repositories",
        sa.Column(
            "bootstrap_attempt_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_last_attempted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_error_type", sa.Text(), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_error_message", sa.Text(), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_response_status", sa.Integer(), nullable=True),
    )
    op.add_column(
        "repositories",
        sa.Column(
            "bootstrap_retry_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "repositories",
        sa.Column("bootstrap_duration_ms", sa.Integer(), nullable=True),
    )
    op.create_check_constraint(
        "ck_repositories_bootstrap_attempt_count_nonnegative",
        "repositories",
        "bootstrap_attempt_count >= 0",
    )
    op.create_check_constraint(
        "ck_repositories_bootstrap_retry_count_nonnegative",
        "repositories",
        "bootstrap_retry_count >= 0",
    )
    op.create_check_constraint(
        "ck_repositories_bootstrap_response_status",
        "repositories",
        "bootstrap_response_status IS NULL "
        "OR bootstrap_response_status BETWEEN 100 AND 599",
    )
    op.create_check_constraint(
        "ck_repositories_bootstrap_duration_nonnegative",
        "repositories",
        "bootstrap_duration_ms IS NULL OR bootstrap_duration_ms >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_repositories_bootstrap_duration_nonnegative",
        "repositories",
        type_="check",
    )
    op.drop_constraint(
        "ck_repositories_bootstrap_response_status",
        "repositories",
        type_="check",
    )
    op.drop_constraint(
        "ck_repositories_bootstrap_retry_count_nonnegative",
        "repositories",
        type_="check",
    )
    op.drop_constraint(
        "ck_repositories_bootstrap_attempt_count_nonnegative",
        "repositories",
        type_="check",
    )
    op.drop_column("repositories", "bootstrap_duration_ms")
    op.drop_column("repositories", "bootstrap_retry_count")
    op.drop_column("repositories", "bootstrap_response_status")
    op.drop_column("repositories", "bootstrap_error_message")
    op.drop_column("repositories", "bootstrap_error_type")
    op.drop_column("repositories", "bootstrap_completed_at")
    op.drop_column("repositories", "bootstrap_last_attempted_at")
    op.drop_column("repositories", "bootstrap_attempt_count")
