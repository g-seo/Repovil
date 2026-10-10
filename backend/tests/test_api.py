from pydantic import PostgresDsn

from repovil.api import create_app
from repovil.settings import Settings


def test_fastapi_application_starts() -> None:
    settings = Settings(database_url=PostgresDsn("postgresql://test:test@localhost:5432/test"))

    application = create_app(settings)
    openapi_schema = application.openapi()

    assert openapi_schema["info"] == {"title": "Repovil", "version": "0.1.0"}
    assert application.state.settings is settings

