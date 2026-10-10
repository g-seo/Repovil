"""FastAPI application entry point."""

import uvicorn
from fastapi import FastAPI

from repovil.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create the API application with its environment-backed settings."""
    application = FastAPI(title="Repovil", version="0.1.0")
    application.state.settings = settings or get_settings()
    return application


app = create_app()


def main() -> None:
    """Run the API server for local development."""
    uvicorn.run("repovil.api:app", host="0.0.0.0", port=8000)

