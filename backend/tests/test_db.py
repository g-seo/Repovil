import os

import pytest

from repovil.db import check_connection


@pytest.mark.integration
def test_postgresql_connection() -> None:
    database_url = os.environ.get("TEST_DATABASE_URL")
    if database_url is None:
        pytest.skip("TEST_DATABASE_URL is required for the PostgreSQL smoke test")

    check_connection(database_url)

