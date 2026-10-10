"""Background worker entry point.

Discovery and tracking commands are added in their dedicated implementation phases.
"""

from repovil.github_client import GitHubClient
from repovil.settings import Settings, get_settings


def create_github_client(settings: Settings) -> GitHubClient:
    """Create the network adapter only from the background-worker boundary."""
    token = settings.github_token.get_secret_value() if settings.github_token else None
    return GitHubClient(
        token=token,
        api_version=settings.github_api_version,
        timeout=float(settings.github_api_timeout_seconds),
        max_retries=int(settings.github_api_max_retries),
    )


def main() -> None:
    """Load shared configuration and prove the worker entry point is runnable."""
    get_settings()
    print("Repovil worker is ready")

