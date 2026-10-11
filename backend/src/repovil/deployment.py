"""Deployment-time validation that reports variable names, never values."""

from __future__ import annotations

import argparse
import logging
import os
from collections.abc import Mapping, Sequence
from typing import Literal

from repovil.observability import configure_logging

logger = logging.getLogger(__name__)
ServiceKind = Literal["api", "worker"]

_REQUIRED_VARIABLES: dict[ServiceKind, tuple[str, ...]] = {
    "api": ("DATABASE_URL",),
    "worker": ("DATABASE_URL", "GITHUB_TOKEN", "GITHUB_API_VERSION"),
}


def missing_environment_variables(
    service: ServiceKind,
    environment: Mapping[str, str],
) -> tuple[str, ...]:
    """Return required variables that are absent or blank for one service kind."""
    return tuple(
        variable
        for variable in _REQUIRED_VARIABLES[service]
        if not environment.get(variable, "").strip()
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Validate the environment before migrations or a production process starts."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Validate Railway service variables")
    parser.add_argument("service", choices=("api", "worker"))
    arguments = parser.parse_args(argv)
    service: ServiceKind = arguments.service
    missing = missing_environment_variables(service, os.environ)
    if missing:
        logger.error(
            "deployment_environment_invalid",
            extra={"service": service, "missing_variables": missing},
        )
        return 1
    logger.info("deployment_environment_valid", extra={"service": service})
    return 0
