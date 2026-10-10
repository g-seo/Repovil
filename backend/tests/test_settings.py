import pytest
from pydantic import ValidationError
from pytest import MonkeyPatch

from repovil.settings import Settings


def test_database_url_can_be_injected_from_environment(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL", "postgresql://configured:user@database.example:5432/repovil"
    )

    settings = Settings()

    assert str(settings.database_url) == (
        "postgresql://configured:user@database.example:5432/repovil"
    )


def test_database_url_must_be_postgresql(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///repovil.db")

    with pytest.raises(ValidationError):
        Settings()

