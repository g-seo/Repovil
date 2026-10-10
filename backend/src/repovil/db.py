"""Minimal PostgreSQL connectivity check used by local development and CI."""

import psycopg

from repovil.settings import get_settings


def check_connection(database_url: str) -> None:
    """Raise when PostgreSQL cannot execute a trivial query."""
    with (
        psycopg.connect(database_url, connect_timeout=5) as connection,
        connection.cursor() as cursor,
    ):
        cursor.execute("SELECT 1")
        result = cursor.fetchone()

    if result != (1,):
        raise RuntimeError("PostgreSQL connection check returned an unexpected result")


def main() -> None:
    """Check the configured database connection."""
    check_connection(str(get_settings().database_url))
    print("PostgreSQL connection OK")

