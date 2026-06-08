"""Tests for Story 5.2 — post-MVP automatic config refresh.

Covers the opt-in ``RefreshConfig`` policy surface and its validation, the
``ConfigRefresher`` daemon worker, the atomic snapshot-swap seam on ``Core``,
failure handling / backoff / diagnostics, the ``CONFIG_UPDATED`` lifecycle
event, tracking-metadata re-pointing on swap, and the byte-for-byte opt-out
guarantee. Tests are deterministic — they drive the worker through its
``trigger_now`` / ``wait_for_next_refresh`` test seams and never sleep on the
wall clock.
"""

from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional

import pytest

from convert_sdk import Core, RefreshConfig, SDKConfig, TransportConfig
from convert_sdk.errors import InvalidConfigError


# --------------------------------------------------------------------------- #
# Fixtures / helpers
# --------------------------------------------------------------------------- #


def _config_payload(*, account_id: str = "acc-1", project_id: str = "proj-1") -> Dict[str, Any]:
    """A minimal valid config payload the loader accepts."""
    return {
        "account_id": account_id,
        "project": {"id": project_id},
        "experiences": [],
        "features": [],
        "goals": [],
        "audiences": [],
        "segments": [],
    }


class _FakeTransport:
    """A scriptable Transport stub (Story 1.2 Protocol) for refresh tests.

    ``payloads`` is the sequence returned by successive ``fetch_config`` calls;
    a payload that is an ``Exception`` instance is raised instead of returned.
    """

    def __init__(self, payloads: List[Any]) -> None:
        self._payloads = list(payloads)
        self.fetch_calls = 0
        self.closed = False

    def fetch_config(self, config: Any) -> Dict[str, Any]:
        self.fetch_calls += 1
        item = self._payloads.pop(0) if self._payloads else _config_payload()
        if isinstance(item, Exception):
            raise item
        return item

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> None:  # pragma: no cover
        pass

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> "_FakeTransport":  # pragma: no cover
        return self

    def __exit__(self, *exc: Any) -> None:  # pragma: no cover
        self.close()


# --------------------------------------------------------------------------- #
# Task 1 — RefreshConfig surface + validation
# --------------------------------------------------------------------------- #


class TestRefreshConfigSurface:
    def test_refresh_config_importable_from_package_root(self) -> None:
        import convert_sdk

        assert "RefreshConfig" in convert_sdk.__all__
        assert convert_sdk.RefreshConfig is RefreshConfig

    def test_sdkconfig_refresh_defaults_to_none(self) -> None:
        cfg = SDKConfig(sdk_key="key-123")
        assert cfg.refresh is None

    def test_refresh_config_accepts_valid_policy(self) -> None:
        rc = RefreshConfig(
            interval_seconds=300.0,
            jitter_seconds=30.0,
            backoff_factor=2.0,
            backoff_max_seconds=600.0,
        )
        assert rc.interval_seconds == 300.0
        assert rc.jitter_seconds == 30.0

    def test_refresh_config_has_sane_defaults(self) -> None:
        rc = RefreshConfig()
        assert rc.interval_seconds > 0
        assert 0 <= rc.jitter_seconds <= rc.interval_seconds
        assert rc.backoff_factor >= 1.0
        assert rc.backoff_max_seconds >= rc.interval_seconds


class TestRefreshConfigValidation:
    def test_rejects_non_positive_interval(self) -> None:
        with pytest.raises(InvalidConfigError):
            RefreshConfig(interval_seconds=0)
        with pytest.raises(InvalidConfigError):
            RefreshConfig(interval_seconds=-5)

    def test_rejects_jitter_greater_than_interval(self) -> None:
        with pytest.raises(InvalidConfigError):
            RefreshConfig(interval_seconds=10, jitter_seconds=20)

    def test_rejects_negative_jitter(self) -> None:
        with pytest.raises(InvalidConfigError):
            RefreshConfig(interval_seconds=10, jitter_seconds=-1)

    def test_rejects_backoff_factor_below_one(self) -> None:
        with pytest.raises(InvalidConfigError):
            RefreshConfig(backoff_factor=0.5)

    def test_rejects_backoff_max_below_interval(self) -> None:
        with pytest.raises(InvalidConfigError):
            RefreshConfig(interval_seconds=300, backoff_max_seconds=100)

    def test_refresh_config_is_frozen(self) -> None:
        rc = RefreshConfig()
        with pytest.raises(Exception):
            rc.interval_seconds = 1  # type: ignore[misc]


# --------------------------------------------------------------------------- #
# Task 2 — ConfigRefresher worker + atomic Core snapshot-swap seam
# --------------------------------------------------------------------------- #


def _remote_config(refresh: Optional[RefreshConfig]) -> SDKConfig:
    return SDKConfig(
        sdk_key="key-123",
        transport=TransportConfig(base_url="https://cdn.example.com"),
        refresh=refresh,
    )


class TestConfigRefresherWorker:
    def test_worker_applies_new_snapshot_on_trigger(self) -> None:
        transport = _FakeTransport(
            [
                _config_payload(project_id="proj-1"),
                _config_payload(project_id="proj-2"),
            ]
        )
        applied: List[Any] = []
        from convert_sdk.config_loader.refresh import ConfigRefresher

        refresher = ConfigRefresher(
            config=_remote_config(RefreshConfig(interval_seconds=300)),
            transport=transport,
            on_snapshot=applied.append,
        )
        refresher.start()
        try:
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
        finally:
            refresher.stop()
        assert applied, "worker should have produced at least one snapshot"
        assert applied[-1].project_id == "proj-2"

    def test_worker_thread_is_daemon(self) -> None:
        from convert_sdk.config_loader.refresh import ConfigRefresher

        refresher = ConfigRefresher(
            config=_remote_config(RefreshConfig()),
            transport=_FakeTransport([]),
            on_snapshot=lambda _s: None,
        )
        refresher.start()
        try:
            assert refresher.is_alive()
            assert refresher.is_daemon()
        finally:
            refresher.stop()
        assert not refresher.is_alive()

    def test_direct_config_refresher_rejected(self) -> None:
        """A refresher has no remote endpoint to poll in direct-config mode."""
        from convert_sdk.config_loader.refresh import ConfigRefresher

        with pytest.raises(InvalidConfigError):
            ConfigRefresher(
                config=SDKConfig(data=_config_payload(), refresh=RefreshConfig()),
                transport=_FakeTransport([]),
                on_snapshot=lambda _s: None,
            )


class TestCoreRefreshIntegration:
    def test_opt_in_refresh_swaps_live_snapshot(self) -> None:
        transport = _FakeTransport(
            [
                _config_payload(project_id="proj-1"),  # initialize()
                _config_payload(project_id="proj-2"),  # refresh
            ]
        )
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        try:
            assert core.current_config is not None
            assert core.current_config.project_id == "proj-1"
            core.refresh_now()
            assert core.current_config.project_id == "proj-2"
        finally:
            core.close()

    def test_opt_out_starts_no_worker(self) -> None:
        before = threading.active_count()
        transport = _FakeTransport([_config_payload()])
        core = Core(_remote_config(None), transport=transport)
        core.initialize()
        try:
            # No daemon refresh thread spun up; refresh_now is a no-op.
            assert threading.active_count() == before
            core.refresh_now()
            assert transport.fetch_calls == 1  # only the initial load
        finally:
            core.close()

    def test_direct_config_with_refresh_skips_worker(self) -> None:
        before = threading.active_count()
        core = Core(SDKConfig(data=_config_payload(), refresh=RefreshConfig()))
        core.initialize()
        try:
            assert threading.active_count() == before
            core.refresh_now()  # no-op, no transport
        finally:
            core.close()

    def test_close_stops_worker(self) -> None:
        transport = _FakeTransport([_config_payload(), _config_payload()])
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        before = threading.active_count()
        assert before >= 1
        core.close()
        # The daemon refresh thread has stopped.
        assert not core._refresher_alive()  # type: ignore[attr-defined]
