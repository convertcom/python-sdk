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

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> int:  # pragma: no cover
        return 200

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
            # First triggered cycle fetches the first scripted payload.
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
            assert applied[-1].project_id == "proj-1"
            # A second triggered cycle fetches the next scripted payload.
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
            assert applied[-1].project_id == "proj-2"
        finally:
            refresher.stop()

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
            # Deterministic wait on the worker's cycle-done seam (no wall clock).
            assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
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


# --------------------------------------------------------------------------- #
# Task 3 — failure handling, backoff, diagnostics, CONFIG_UPDATED, tracking
# --------------------------------------------------------------------------- #


class TestRefreshFailureHandling:
    def test_transient_failure_keeps_prior_snapshot(self) -> None:
        from convert_sdk.config_loader.refresh import ConfigRefresher
        from convert_sdk.errors import ConfigLoadError

        transport = _FakeTransport([ConfigLoadError("boom")])
        applied: List[Any] = []
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
        # The failed fetch produced no snapshot; the worker survived (cycle done).
        assert applied == []

    def test_terminal_failure_callback_fires_at_backoff_cap(self) -> None:
        from convert_sdk.config_loader.refresh import ConfigRefresher
        from convert_sdk.errors import ConfigLoadError

        # backoff_max == interval so the cap is reached after a single failure.
        policy = RefreshConfig(
            interval_seconds=300, backoff_factor=2.0, backoff_max_seconds=300
        )
        transport = _FakeTransport([ConfigLoadError("boom"), ConfigLoadError("boom")])
        seen: List[BaseException] = []
        refresher = ConfigRefresher(
            config=_remote_config(policy),
            transport=transport,
            on_snapshot=lambda _s: None,
            on_terminal_failure=seen.append,
        )
        refresher.start()
        try:
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
        finally:
            refresher.stop()
        assert seen, "terminal-failure callback should have fired at the cap"
        assert isinstance(seen[-1], ConfigLoadError)

    def test_terminal_callback_that_raises_is_swallowed(self) -> None:
        from convert_sdk.config_loader.refresh import ConfigRefresher
        from convert_sdk.errors import ConfigLoadError

        policy = RefreshConfig(interval_seconds=300, backoff_max_seconds=300)

        def _boom(_exc: BaseException) -> None:
            raise RuntimeError("handler blew up")

        transport = _FakeTransport([ConfigLoadError("boom")])
        refresher = ConfigRefresher(
            config=_remote_config(policy),
            transport=transport,
            on_snapshot=lambda _s: None,
            on_terminal_failure=_boom,
        )
        refresher.start()
        try:
            refresher.trigger_now()
            # A raising callback must not crash the worker.
            assert refresher.wait_for_next_refresh(timeout=5.0)
            assert refresher.is_alive()
        finally:
            refresher.stop()

    def test_failure_does_not_crash_core_host(self) -> None:
        from convert_sdk.errors import ConfigLoadError

        transport = _FakeTransport(
            [_config_payload(project_id="proj-1"), ConfigLoadError("boom")]
        )
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        try:
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
            # Background failure: prior good snapshot still served, host alive.
            assert core.current_config is not None
            assert core.current_config.project_id == "proj-1"
        finally:
            core.close()


class TestWorkerResilience:
    def test_swap_callback_exception_does_not_kill_worker(self) -> None:
        """An error escaping _do_refresh (e.g. swap callback) is caught and the
        worker survives (refresh.worker_crashed guard)."""
        from convert_sdk.config_loader.refresh import ConfigRefresher

        def _boom(_snapshot: Any) -> None:
            raise RuntimeError("swap blew up")

        transport = _FakeTransport([_config_payload(), _config_payload()])
        refresher = ConfigRefresher(
            config=_remote_config(RefreshConfig(interval_seconds=300)),
            transport=transport,
            on_snapshot=_boom,
        )
        refresher.start()
        try:
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
            # Worker absorbed the callback failure and is still running.
            assert refresher.is_alive()
            # And it can still complete a subsequent cycle.
            refresher.trigger_now()
            assert refresher.wait_for_next_refresh(timeout=5.0)
        finally:
            refresher.stop()

    def test_stop_is_safe_from_worker_thread(self) -> None:
        """Calling stop() re-entrantly from the worker thread must not deadlock."""
        from convert_sdk.config_loader.refresh import ConfigRefresher
        from convert_sdk.errors import ConfigLoadError

        policy = RefreshConfig(interval_seconds=300, backoff_max_seconds=300)
        holder: Dict[str, Any] = {}

        def _terminal(_exc: BaseException) -> None:
            # Re-entrant stop from inside the worker thread.
            holder["refresher"].stop()

        transport = _FakeTransport([ConfigLoadError("boom")])
        refresher = ConfigRefresher(
            config=_remote_config(policy),
            transport=transport,
            on_snapshot=lambda _s: None,
            on_terminal_failure=_terminal,
        )
        holder["refresher"] = refresher
        refresher.start()
        refresher.trigger_now()
        # If self-join were attempted this would hang; the seam must resolve.
        assert refresher.wait_for_next_refresh(timeout=5.0)
        refresher.stop()
        assert not refresher.is_alive()


class TestConfigUpdatedEvent:
    def test_config_updated_emitted_on_successful_swap(self) -> None:
        from convert_sdk import LifecycleEvent

        transport = _FakeTransport(
            [_config_payload(project_id="proj-1"), _config_payload(project_id="proj-2")]
        )
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        payloads: List[Any] = []
        core.on(LifecycleEvent.CONFIG_UPDATED, lambda payload, _err: payloads.append(payload))
        core.initialize()
        try:
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
        finally:
            core.close()
        assert payloads, "CONFIG_UPDATED should fire on the refresh swap"


class TestTrackingMetadataRepoint:
    def test_queue_update_snapshot_metadata(self) -> None:
        from convert_sdk.tracking.queue import TrackingQueue

        queue = TrackingQueue(batch_size=10)
        queue.update_snapshot_metadata(account_id="acc-2", project_id="proj-2")
        assert queue.account_id == "acc-2"
        assert queue.project_id == "proj-2"

    def test_refresh_repoints_tracking_to_new_project(self) -> None:
        transport = _FakeTransport(
            [
                _config_payload(account_id="acc-1", project_id="proj-1"),
                _config_payload(account_id="acc-1", project_id="proj-2"),
            ]
        )
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        try:
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
            # The shared tracker now serializes against the new project id.
            assert core._tracker._snapshot.project_id == "proj-2"  # type: ignore[attr-defined]
        finally:
            core.close()


# --------------------------------------------------------------------------- #
# Task 4 — MVP-stability + thread-safety regression
# --------------------------------------------------------------------------- #


class TestMVPStability:
    def test_refresh_none_spins_up_no_daemon_thread(self) -> None:
        before = threading.active_count()
        transport = _FakeTransport([_config_payload()])
        core = Core(_remote_config(None), transport=transport)
        core.initialize()
        try:
            assert threading.active_count() == before
            assert core._refresher is None  # type: ignore[attr-defined]
        finally:
            core.close()

    def test_refresh_none_does_not_emit_config_updated_event(self) -> None:
        from convert_sdk import LifecycleEvent

        transport = _FakeTransport([_config_payload()])
        core = Core(_remote_config(None), transport=transport)
        seen: List[Any] = []
        core.on(LifecycleEvent.CONFIG_UPDATED, lambda p, _e: seen.append(p))
        core.initialize()
        try:
            core.refresh_now()  # no-op
        finally:
            core.close()
        # No background refresh => no event-bus CONFIG_UPDATED emission.
        assert seen == []

    def test_existing_context_retains_prior_snapshot_after_swap(self) -> None:
        transport = _FakeTransport(
            [_config_payload(project_id="proj-1"), _config_payload(project_id="proj-2")]
        )
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        try:
            ctx = core.create_context("visitor-1")
            ctx_snapshot = ctx._snapshot  # type: ignore[attr-defined]
            assert ctx_snapshot.project_id == "proj-1"
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
            # The live snapshot advanced...
            assert core.current_config.project_id == "proj-2"
            # ...but the already-created context keeps its creation-time view.
            assert ctx._snapshot.project_id == "proj-1"  # type: ignore[attr-defined]
        finally:
            core.close()


class TestThreadSafetySwap:
    def test_concurrent_create_context_during_swap_is_coherent(self) -> None:
        """Hammer create_context from many threads while a swap fires repeatedly.

        Every context observed must be internally coherent: its snapshot is one
        of the whole scripted snapshots (proj-1 or proj-2), never a torn hybrid,
        and the snapshot's project_id matches its account_id binding.
        """
        payloads = [_config_payload(project_id="proj-1")]
        # Provide many alternating payloads so the worker can swap repeatedly.
        for i in range(200):
            payloads.append(
                _config_payload(project_id="proj-2" if i % 2 else "proj-1")
            )
        transport = _FakeTransport(payloads)
        core = Core(_remote_config(RefreshConfig(interval_seconds=300)), transport=transport)
        core.initialize()
        observed: List[str] = []
        errors: List[BaseException] = []
        stop = threading.Event()

        def _reader() -> None:
            try:
                while not stop.is_set():
                    ctx = core.create_context("visitor-x")
                    snap = ctx._snapshot  # type: ignore[attr-defined]
                    # Coherence: a real snapshot with a known project + account.
                    assert snap.account_id == "acc-1"
                    assert snap.project_id in {"proj-1", "proj-2"}
                    observed.append(snap.project_id)
            except BaseException as exc:  # pragma: no cover - failure path
                errors.append(exc)

        readers = [threading.Thread(target=_reader) for _ in range(4)]
        for t in readers:
            t.start()
        try:
            for _ in range(50):
                core.refresh_now()
                core._refresher.wait_for_next_refresh(timeout=5.0)  # type: ignore[attr-defined]
        finally:
            stop.set()
            for t in readers:
                t.join(timeout=5.0)
            core.close()
        assert not errors, f"reader saw an incoherent snapshot: {errors}"
        assert observed, "readers should have created contexts"
