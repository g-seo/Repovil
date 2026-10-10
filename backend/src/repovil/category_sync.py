"""Synchronize the validated category/topic configuration into PostgreSQL."""

from dataclasses import dataclass
from pathlib import Path
from typing import cast

from repovil.category_config import (
    DEFAULT_CATEGORY_CONFIG_PATH,
    CategoryConfiguration,
    load_category_config,
)
from repovil.db import connect_database
from repovil.settings import get_settings


@dataclass(frozen=True)
class CategorySyncResult:
    """Summary of the desired configuration committed by a sync."""

    category_count: int
    topic_count: int
    active_mapping_count: int


def _sync_configuration(
    database_url: str,
    configuration: CategoryConfiguration,
) -> CategorySyncResult:
    configured_slugs = [category.slug for category in configuration.categories]
    active_topic_names = {
        topic
        for category in configuration.categories
        if category.active
        for topic in category.topics
    }
    desired_active_mappings = {
        (category.slug, topic)
        for category in configuration.categories
        if category.active
        for topic in category.topics
    }

    with connect_database(database_url) as connection, connection.cursor() as cursor:
        category_ids: dict[str, int] = {}
        topic_ids: dict[str, int] = {}

        for category in configuration.categories:
            cursor.execute(
                """
                    INSERT INTO categories (name, slug, active, display_order)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (slug) DO UPDATE
                    SET name = EXCLUDED.name,
                        active = EXCLUDED.active,
                        display_order = EXCLUDED.display_order,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE (categories.name, categories.active, categories.display_order)
                          IS DISTINCT FROM
                          (EXCLUDED.name, EXCLUDED.active, EXCLUDED.display_order)
                    RETURNING id
                    """,
                (category.name, category.slug, category.active, category.display_order),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute("SELECT id FROM categories WHERE slug = %s", (category.slug,))
                row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"category upsert did not return an id: {category.slug}")
            category_ids[category.slug] = cast(int, row[0])

        cursor.execute(
            """
                UPDATE categories
                SET active = false, updated_at = CURRENT_TIMESTAMP
                WHERE active AND NOT (slug = ANY(%s))
                """,
            (configured_slugs,),
        )

        all_topic_names = {
            topic for category in configuration.categories for topic in category.topics
        }
        for topic_name in sorted(all_topic_names):
            topic_active = topic_name in active_topic_names
            cursor.execute(
                """
                    INSERT INTO topics (name, active)
                    VALUES (%s, %s)
                    ON CONFLICT (name) DO UPDATE
                    SET active = EXCLUDED.active, updated_at = CURRENT_TIMESTAMP
                    WHERE topics.active IS DISTINCT FROM EXCLUDED.active
                    RETURNING id
                    """,
                (topic_name, topic_active),
            )
            row = cursor.fetchone()
            if row is None:
                cursor.execute("SELECT id FROM topics WHERE name = %s", (topic_name,))
                row = cursor.fetchone()
            if row is None:
                raise RuntimeError(f"topic upsert did not return an id: {topic_name}")
            topic_ids[topic_name] = cast(int, row[0])

        cursor.execute(
            """
                UPDATE topics
                SET active = false, updated_at = CURRENT_TIMESTAMP
                WHERE active AND NOT (name = ANY(%s))
                """,
            (sorted(active_topic_names),),
        )

        for category in configuration.categories:
            for topic_name in category.topics:
                mapping_active = (category.slug, topic_name) in desired_active_mappings
                cursor.execute(
                    """
                        INSERT INTO category_topics (category_id, topic_id, active)
                        VALUES (%s, %s, %s)
                        ON CONFLICT (category_id, topic_id) DO UPDATE
                        SET active = EXCLUDED.active, updated_at = CURRENT_TIMESTAMP
                        WHERE category_topics.active IS DISTINCT FROM EXCLUDED.active
                        """,
                    (
                        category_ids[category.slug],
                        topic_ids[topic_name],
                        mapping_active,
                    ),
                )

        cursor.execute(
            """
                SELECT category_topics.category_id,
                       category_topics.topic_id,
                       categories.slug,
                       topics.name
                FROM category_topics
                JOIN categories ON categories.id = category_topics.category_id
                JOIN topics ON topics.id = category_topics.topic_id
                WHERE category_topics.active
                """
        )
        for category_id, topic_id, stored_slug, stored_topic_name in cursor.fetchall():
            if (str(stored_slug), str(stored_topic_name)) not in desired_active_mappings:
                cursor.execute(
                    """
                        UPDATE category_topics
                        SET active = false, updated_at = CURRENT_TIMESTAMP
                        WHERE category_id = %s AND topic_id = %s
                        """,
                    (category_id, topic_id),
                )

    return CategorySyncResult(
        category_count=len(configuration.categories),
        topic_count=len(all_topic_names),
        active_mapping_count=len(desired_active_mappings),
    )


def sync_categories(
    database_url: str,
    config_path: str | Path = DEFAULT_CATEGORY_CONFIG_PATH,
) -> CategorySyncResult:
    """Validate the complete YAML document, then apply it in one transaction."""
    configuration = load_category_config(config_path)
    return _sync_configuration(database_url, configuration)


def main() -> None:
    """Synchronize the default category configuration into the configured database."""
    result = sync_categories(str(get_settings().database_url))
    print(
        f"Synchronized {result.category_count} categories, {result.topic_count} topics, "
        f"and {result.active_mapping_count} active mappings"
    )
