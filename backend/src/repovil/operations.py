"""Railway cron orchestration for the daily discovery/bootstrap pipeline."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Sequence

from repovil.bootstrap import main as bootstrap_main
from repovil.discovery import main as discovery_main
from repovil.observability import configure_logging

logger = logging.getLogger(__name__)


def run_daily(
    *,
    discovery: Callable[[Sequence[str] | None], int] = discovery_main,
    bootstrap: Callable[[Sequence[str] | None], int] = bootstrap_main,
) -> int:
    """Run discovery then refresh bootstrap source history, retaining failure state."""
    discovery_exit = discovery(())
    bootstrap_exit = bootstrap(("--refresh-active",))
    exit_code = int(discovery_exit != 0 or bootstrap_exit != 0)
    logger.info(
        "daily_pipeline_finished",
        extra={
            "status": "COMPLETED" if exit_code == 0 else "FAILED",
        },
    )
    return exit_code


def main(argv: Sequence[str] | None = None) -> int:
    """Run discovery followed by bootstrap for the Railway daily cron."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Run daily discovery and bootstrap")
    parser.parse_args(argv)
    return run_daily()
