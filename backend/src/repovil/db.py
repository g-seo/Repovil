"""PostgreSQL connection helpers shared by API and worker entry points."""

import psycopg
from psycopg import Connection

from repovil.settings import get_settings


def connect_database(database_url: str) -> Connection[tuple[object, ...]]:
    """Open a PostgreSQL connection whose timestamp results are rendered in UTC."""
    connection = psycopg.connect(database_url, connect_timeout=5)
    connection.execute("SET TIME ZONE 'UTC'")
    return connection


def check_connection(database_url: str) -> None:
    """Raise when PostgreSQL cannot execute a trivial query."""
    with (
        connect_database(database_url) as connection,
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

