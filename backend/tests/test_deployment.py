import logging

from pytest import LogCaptureFixture, MonkeyPatch

from repovil.deployment import main, missing_environment_variables


def test_deployment_environment_validation_is_service_specific() -> None:
    assert missing_environment_variables("api", {}) == ("DATABASE_URL",)
    assert missing_environment_variables(
        "worker",
        {
            "DATABASE_URL": "postgresql://example",
            "GITHUB_TOKEN": " ",
            "GITHUB_API_VERSION": "2026-03-10",
        },
    ) == ("GITHUB_TOKEN",)


def test_deployment_check_fails_without_printing_variable_values(
    monkeypatch: MonkeyPatch,
    caplog: LogCaptureFixture,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("GITHUB_TOKEN", "secret-token")
    monkeypatch.setenv("GITHUB_API_VERSION", "2026-03-10")

    with caplog.at_level(logging.ERROR, logger="repovil.deployment"):
        assert main(["worker"]) == 1

    assert caplog.records[-1].__dict__["missing_variables"] == ("DATABASE_URL",)
    assert "secret-token" not in caplog.text
