"""Application settings loaded from environment variables."""

from functools import lru_cache

from pydantic import NonNegativeInt, PositiveFloat, PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Configuration shared by API and worker entry points."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
    )

    database_url: PostgresDsn = PostgresDsn(
        "postgresql://repovil:repovil-local@localhost:5432/repovil"
    )
    github_token: SecretStr | None = None
    github_api_version: str = "2026-03-10"
    github_api_timeout_seconds: PositiveFloat = 10.0
    github_api_max_retries: NonNegativeInt = 3


@lru_cache
def get_settings() -> Settings:
    """Return one immutable-by-convention settings instance per process."""
    return Settings()

