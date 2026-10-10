from pathlib import Path
from typing import cast

import psycopg
import pytest
from psycopg.errors import UniqueViolation
from test_migrations import PROJECT_ROOT, _alembic_config

from alembic import command
from repovil.category_config import CategoryConfigError
from repovil.category_sync import sync_categories

DEFAULT_CONFIG = PROJECT_ROOT / "config" / "categories.yaml"


@pytest.fixture
def migrated_database_url(postgres_schema_url: str) -> str:
    command.upgrade(_alembic_config(postgres_schema_url), "head")
    return postgres_schema_url


def _configuration_rows(database_url: str) -> tuple[list[tuple[object, ...]], ...]:
    with psycopg.connect(database_url) as connection:
        categories = connection.execute(
            "SELECT id, name, slug, active, display_order, updated_at FROM categories ORDER BY id"
        ).fetchall()
        topics = connection.execute(
            "SELECT id, name, active, updated_at FROM topics ORDER BY id"
        ).fetchall()
        mappings = connection.execute(
            """
            SELECT category_id, topic_id, active, updated_at
            FROM category_topics
            ORDER BY category_id, topic_id
            """
        ).fetchall()
    return categories, topics, mappings


@pytest.mark.integration
def test_category_sync_is_idempotent_and_never_creates_all(
    migrated_database_url: str,
) -> None:
    first_result = sync_categories(migrated_database_url, DEFAULT_CONFIG)
    first_rows = _configuration_rows(migrated_database_url)

    second_result = sync_categories(migrated_database_url, DEFAULT_CONFIG)
    second_rows = _configuration_rows(migrated_database_url)

    assert first_result == second_result
    assert first_result.category_count == 6
    assert first_result.topic_count == 21
    assert first_result.active_mapping_count == 21
    assert second_rows == first_rows
    assert all(str(row[1]).casefold() != "all" for row in second_rows[0])
    assert all(str(row[1]).casefold() != "all" for row in second_rows[1])


@pytest.mark.integration
def test_category_sync_soft_deactivates_and_reactivates_history(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    sync_categories(migrated_database_url, DEFAULT_CONFIG)
    with psycopg.connect(migrated_database_url) as connection:
        category_ids: dict[str, int] = {
            cast(str, row[0]): cast(int, row[1])
            for row in connection.execute("SELECT slug, id FROM categories").fetchall()
        }
        topic_ids: dict[str, int] = {
            cast(str, row[0]): cast(int, row[1])
            for row in connection.execute("SELECT name, id FROM topics").fetchall()
        }
        repository_id = connection.execute(
            """
            INSERT INTO repositories (
                github_id, owner, name, github_url, current_stars, status, discovered_at
            ) VALUES (505, 'owner', 'repo', 'https://github.com/owner/repo',
                      200, 'active', CURRENT_TIMESTAMP)
            RETURNING id
            """
        ).fetchone()
        assert repository_id is not None
        connection.execute(
            """
            INSERT INTO repository_topics (repository_id, topic_id)
            VALUES (%s, %s)
            """,
            (repository_id[0], topic_ids["mcp-server"]),
        )

    reduced_config = tmp_path / "categories.yaml"
    reduced_config.write_text(
        """
categories:
  - name: AI Agents
    slug: ai-agents
    active: true
    display_order: 1
    topics:
      - ai-agent
""".lstrip(),
        encoding="utf-8",
    )
    sync_categories(migrated_database_url, reduced_config)

    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute("SELECT count(*) FROM categories").fetchone() == (6,)
        assert connection.execute("SELECT count(*) FROM categories WHERE active").fetchone() == (
            1,
        )
        assert connection.execute("SELECT count(*) FROM topics").fetchone() == (21,)
        assert connection.execute("SELECT count(*) FROM topics WHERE active").fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM category_topics").fetchone() == (21,)
        assert connection.execute(
            "SELECT count(*) FROM category_topics WHERE active"
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM repository_topics").fetchone() == (1,)

    sync_categories(migrated_database_url, DEFAULT_CONFIG)
    with psycopg.connect(migrated_database_url) as connection:
        current_category_ids: dict[str, int] = {
            cast(str, row[0]): cast(int, row[1])
            for row in connection.execute("SELECT slug, id FROM categories").fetchall()
        }
        assert current_category_ids == category_ids
        assert dict(connection.execute("SELECT name, id FROM topics").fetchall()) == topic_ids
        assert connection.execute("SELECT count(*) FROM categories WHERE active").fetchone() == (
            6,
        )
        assert connection.execute("SELECT count(*) FROM topics WHERE active").fetchone() == (21,)
        assert connection.execute(
            "SELECT count(*) FROM category_topics WHERE active"
        ).fetchone() == (21,)


@pytest.mark.integration
def test_category_sync_rolls_back_all_changes_on_database_error(
    migrated_database_url: str,
    tmp_path: Path,
) -> None:
    sync_categories(migrated_database_url, DEFAULT_CONFIG)
    with psycopg.connect(migrated_database_url) as connection:
        connection.execute(
            """
            INSERT INTO categories (name, slug, active, display_order)
            VALUES ('Reserved Name', 'old-slug', true, 99)
            """
        )

    conflicting_config = tmp_path / "categories.yaml"
    conflicting_config.write_text(
        """
categories:
  - name: Reserved Name
    slug: new-slug
    active: true
    display_order: 1
    topics:
      - new-topic
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(UniqueViolation):
        sync_categories(migrated_database_url, conflicting_config)

    with psycopg.connect(migrated_database_url) as connection:
        assert connection.execute(
            "SELECT active FROM categories WHERE slug = 'old-slug'"
        ).fetchone() == (True,)
        assert connection.execute("SELECT count(*) FROM categories WHERE active").fetchone() == (
            7,
        )
        assert connection.execute(
            "SELECT count(*) FROM categories WHERE slug = 'new-slug'"
        ).fetchone() == (0,)


def test_category_sync_validates_before_opening_database(tmp_path: Path) -> None:
    invalid_config = tmp_path / "invalid.yaml"
    invalid_config.write_text("categories: []\n", encoding="utf-8")

    with pytest.raises(CategoryConfigError):
        sync_categories("postgresql://invalid:invalid@does-not-exist.invalid/db", invalid_config)
