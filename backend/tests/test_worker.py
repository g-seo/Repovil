from pydantic import PostgresDsn, SecretStr
from pytest import CaptureFixture

from repovil.settings import Settings
from repovil.worker import create_github_client, main


def test_worker_entry_point_starts(capsys: CaptureFixture[str]) -> None:
    main()

    output = capsys.readouterr()
    assert output.out == "Repovil worker is ready\n"


def test_worker_owns_github_client_construction() -> None:
    settings = Settings(
        database_url=PostgresDsn("postgresql://test:test@localhost:5432/test"),
        github_token=SecretStr("worker-secret"),
        github_api_timeout_seconds=8,
        github_api_max_retries=2,
    )

    client = create_github_client(settings)

    assert client.__class__.__name__ == "GitHubClient"

