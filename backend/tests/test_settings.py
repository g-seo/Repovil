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


def test_github_client_settings_can_be_injected_without_exposing_token(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_TOKEN", "example-secret")
    monkeypatch.setenv("GITHUB_API_VERSION", "2026-03-10")
    monkeypatch.setenv("GITHUB_API_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("GITHUB_API_MAX_RETRIES", "2")

    settings = Settings()

    assert settings.github_token is not None
    assert settings.github_token.get_secret_value() == "example-secret"
    assert "example-secret" not in repr(settings)
    assert settings.github_api_timeout_seconds == 12.5
    assert settings.github_api_max_retries == 2

