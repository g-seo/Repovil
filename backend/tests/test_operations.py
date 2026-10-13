from collections.abc import Sequence
from datetime import UTC, datetime

from pytest import MonkeyPatch

import repovil.bootstrap as bootstrap_module
import repovil.discovery as discovery_module
import repovil.tracking as tracking_module
from repovil.bootstrap import BootstrapRunResult
from repovil.discovery import DiscoveryRunResult
from repovil.operations import run_daily
from repovil.tracking import TrackingRunResult


def test_daily_pipeline_runs_bootstrap_after_successful_discovery() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []

    def discovery(argv: Sequence[str] | None) -> int:
        calls.append(("discovery", tuple(argv or ())))
        return 0

    def bootstrap(argv: Sequence[str] | None) -> int:
        calls.append(("bootstrap", tuple(argv or ())))
        return 0

    assert run_daily(discovery=discovery, bootstrap=bootstrap) == 0
    assert calls == [("discovery", ()), ("bootstrap", ("--refresh-active",))]


def test_daily_pipeline_attempts_bootstrap_but_retains_discovery_failure() -> None:
    calls: list[str] = []

    def discovery(argv: Sequence[str] | None) -> int:
        calls.append("discovery")
        return 1

    def bootstrap(argv: Sequence[str] | None) -> int:
        calls.append("bootstrap")
        return 0

    assert run_daily(discovery=discovery, bootstrap=bootstrap) == 1
    assert calls == ["discovery", "bootstrap"]


def test_daily_pipeline_reports_bootstrap_failure() -> None:
    def success(argv: Sequence[str] | None) -> int:
        return 0

    def failure(argv: Sequence[str] | None) -> int:
        return 1

    assert run_daily(discovery=success, bootstrap=failure) == 1


def test_worker_entry_points_return_nonzero_for_partial_results(
    monkeypatch: MonkeyPatch,
) -> None:
    def partial_discovery(*args: object, **kwargs: object) -> DiscoveryRunResult:
        return DiscoveryRunResult(11, "PARTIAL", 4, 2, ())

    def partial_bootstrap(*args: object, **kwargs: object) -> BootstrapRunResult:
        return BootstrapRunResult(2, 1, 1, (), ())

    def partial_tracking(*args: object, **kwargs: object) -> TrackingRunResult:
        return TrackingRunResult(
            run_id=12,
            scheduled_at=datetime(2026, 10, 11, tzinfo=UTC),
            status="PARTIAL",
            total_count=20,
            success_count=19,
            failed_count=1,
            skipped_count=0,
            published_at=datetime(2026, 10, 11, 0, 5, tzinfo=UTC),
            ranking_count=30,
        )

    monkeypatch.setattr(discovery_module, "run_discovery", partial_discovery)
    monkeypatch.setattr(bootstrap_module, "run_bootstrap", partial_bootstrap)
    monkeypatch.setattr(tracking_module, "run_tracking", partial_tracking)

    assert discovery_module.main([]) == 1
    assert bootstrap_module.main([]) == 1
    assert tracking_module.main([]) == 1


def test_worker_entry_point_returns_nonzero_for_fatal_error(monkeypatch: MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> DiscoveryRunResult:
        raise RuntimeError("expected test failure")

    monkeypatch.setattr(discovery_module, "run_discovery", fail)

    assert discovery_module.main([]) == 1
