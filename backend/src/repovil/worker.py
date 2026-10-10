"""Background worker entry point.

Discovery and tracking commands are added in their dedicated implementation phases.
"""

from repovil.settings import get_settings


def main() -> None:
    """Load shared configuration and prove the worker entry point is runnable."""
    get_settings()
    print("Repovil worker is ready")

