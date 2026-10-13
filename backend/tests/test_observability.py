import json
import logging
import sys

from repovil.observability import JsonFormatter


def test_json_formatter_includes_operational_fields_and_excludes_unknown_secrets() -> None:
    record = logging.LogRecord(
        name="repovil.tracking",
        level=logging.INFO,
        pathname=__file__,
        lineno=12,
        msg="tracking_repository_succeeded",
        args=(),
        exc_info=None,
    )
    record.__dict__.update(
        {
            "run_id": 41,
            "repository_id": 72,
            "response_status": 200,
            "retry_count": 1,
            "duration_ms": 53,
            "rate_limit_limit": 5_000,
            "rate_limit_remaining": 0,
            "rate_limit_reset_at": 1_800_000_000,
            "rate_limit_resource": "core",
            "sleep_seconds": 2.0,
            "github_token": "must-not-appear",
        }
    )

    payload = json.loads(JsonFormatter().format(record))

    assert payload["event"] == "tracking_repository_succeeded"
    assert payload["run_id"] == 41
    assert payload["repository_id"] == 72
    assert payload["response_status"] == 200
    assert payload["retry_count"] == 1
    assert payload["duration_ms"] == 53
    assert payload["rate_limit_resource"] == "core"
    assert payload["rate_limit_reset_at"] == 1_800_000_000
    assert payload["sleep_seconds"] == 2.0
    assert payload["timestamp"].endswith("Z")
    assert "must-not-appear" not in json.dumps(payload)
    assert "github_token" not in payload


def test_json_formatter_does_not_render_exception_messages() -> None:
    try:
        raise RuntimeError("secret-value-must-not-appear")
    except RuntimeError:
        exception = sys.exc_info()

    record = logging.LogRecord(
        name="repovil.tracking",
        level=logging.ERROR,
        pathname=__file__,
        lineno=40,
        msg="tracking_job_failed",
        args=(),
        exc_info=exception,
    )

    rendered = JsonFormatter().format(record)
    payload = json.loads(rendered)

    assert payload["error_type"] == "RuntimeError"
    assert "secret-value-must-not-appear" not in rendered
