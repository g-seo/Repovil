"""Small JSON logging setup for Railway and local worker processes."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Final

_STRUCTURED_FIELDS: Final = (
    "run_id",
    "repository_id",
    "github_id",
    "status",
    "response_status",
    "retry_count",
    "duration_ms",
    "error_type",
    "reason_type",
    "topic",
    "min_stars",
    "max_stars",
    "page",
    "github_endpoint",
    "rate_limit_limit",
    "rate_limit_remaining",
    "rate_limit_reset_at",
    "rate_limit_resource",
    "sleep_seconds",
    "captured_at",
    "discovered_count",
    "added_count",
    "failed_range_count",
    "total_count",
    "success_count",
    "failed_count",
    "skipped_count",
    "stored_day_count",
    "baseline_periods",
    "missing_variables",
    "service",
)


class JsonFormatter(logging.Formatter):
    """Render only approved operational fields, keeping secrets out of logs."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }
        for field in _STRUCTURED_FIELDS:
            if hasattr(record, field):
                payload[field] = getattr(record, field)
        if record.exc_info is not None and "error_type" not in payload:
            exception_type = record.exc_info[0]
            if exception_type is not None:
                payload["error_type"] = exception_type.__name__
        return json.dumps(payload, separators=(",", ":"), default=str)


def configure_logging(level: int = logging.INFO) -> None:
    """Install one process-wide JSON stderr handler without duplicating it."""
    logging.disable(logging.NOTSET)
    for name, configured_logger in logging.Logger.manager.loggerDict.items():
        if (name == "repovil" or name.startswith("repovil.")) and isinstance(
            configured_logger, logging.Logger
        ):
            configured_logger.disabled = False
    root = logging.getLogger()
    root.setLevel(level)
    for handler in root.handlers:
        if isinstance(handler.formatter, JsonFormatter):
            handler.setLevel(level)
            return

    handler = logging.StreamHandler()
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
