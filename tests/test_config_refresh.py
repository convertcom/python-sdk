"""Story 5.2 — auto config refresh: opt-in, threading, failure handling."""

from __future__ import annotations

import logging
import random
import threading
import time
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import pytest

from convert_sdk import Core, SDKConfig
from convert_sdk.config import RefreshConfig
from convert_sdk.config_loader.refresh import ConfigRefresher
from convert_sdk.ports.transport import ConfigRequest, Transport, TrackingRequest


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _base_config_payload() -> dict[str, Any]:
    return {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "experiences": [],
        "features": [],
        "audiences": [],
        "segments": [],
        "goals": [],
    }


def _config_with_experience(experience_key: str = "checkout") -> dict[str, Any]:
    payload = _base_config_payload()
    payload["experiences"] = [
        {
            "id": "e1",
            "key": experience_key,
            "status": "active",
            "variations": [
                {
                    "id": "v1",
                    "key": "control",
                    "status": "active",
                    "traffic_allocation": 100.0,
                }
            ],
        }
    ]
    return payload


@dataclass
class RecordingTransport:
    """Fake Transport that returns configurable payloads and counts calls.

    ``error_starts_at_call`` controls when ``fetch_error`` begins firing.
    The default of ``1`` raises immediately on the very first call (used
    by tests that need init itself to fail). Setting ``2`` lets the
    initial Core fetch succeed and subsequent refresh attempts fail.
    """

    payloads: list[Mapping[str, Any]] = field(default_factory=list)
    fetch_calls: int = 0
    fetch_error: Optional[Exception] = None
    error_starts_at_call: int = 1
    last_request: Optional[ConfigRequest] = None
    closed: bool = False

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        self.fetch_calls += 1
        self.last_request = request
        if self.fetch_error is not None and self.fetch_calls >= self.error_starts_at_call:
            raise self.fetch_error
        if not self.payloads:
            return _base_config_payload()
        index = min(self.fetch_calls - 1, len(self.payloads) - 1)
        return deepcopy(dict(self.payloads[index]))

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        return {"status": 200}

    def close(self) -> None:
        self.closed = True


def _make_core(
    *,
    transport: Transport,
    refresh: Optional[RefreshConfig] = None,
    sdk_key: Optional[str] = "sdk-key",
) -> Core:
    return Core(
        SDKConfig(
            sdk_key=sdk_key,
            sdk_key_secret="secret",
            environment="production",
            refresh=refresh,
        ),
        transport=transport,
    )


# ---------------------------------------------------------------------------
# Opt-in / opt-out semantics (AC #2)
# ---------------------------------------------------------------------------


class TestOptInOptOut:
    def test_refresh_none_does_not_start_worker(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        with _make_core(transport=transport, refresh=None) as core:
            assert core._refresher is None
            # Behaviour is byte-for-byte MVP: transport called once, that's it.
            assert transport.fetch_calls == 1

    def test_refresh_starts_daemon_thread(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=10.0, jitter_seconds=0.0)
        with _make_core(transport=transport, refresh=policy) as core:
            refresher = core._refresher
            assert refresher is not None
            assert refresher.is_running
            assert refresher._thread is not None
            assert refresher._thread.daemon is True

    def test_direct_config_does_not_start_refresher(self) -> None:
        transport = RecordingTransport()
        policy = RefreshConfig(interval_seconds=10.0)
        config = SDKConfig(
            config_data=_base_config_payload(),
            refresh=policy,
            environment="production",
        )
        with Core(config, transport=transport) as core:
            # Direct-config mode has no remote endpoint; the refresher
            # is intentionally not spun up even with a refresh policy
            # supplied. Diagnostic event records the skip.
            assert core._refresher is None
            assert transport.fetch_calls == 0


# ---------------------------------------------------------------------------
# Refresh applies new snapshots (AC #1)
# ---------------------------------------------------------------------------


class TestRefreshAppliesSnapshots:
    def test_trigger_now_swaps_snapshot(self) -> None:
        first = _base_config_payload()
        second = _config_with_experience("checkout")
        transport = RecordingTransport(payloads=[first, second])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)
        with _make_core(transport=transport, refresh=policy) as core:
            # Initial snapshot from the first transport response.
            assert core.snapshot.experiences_by_key == {}

            core.refresh_now()
            assert core._refresher is not None
            assert core._refresher.wait_for_next_refresh(timeout=2.0)

            assert "checkout" in core.snapshot.experiences_by_key
            assert transport.fetch_calls == 2

    def test_refresh_emits_success_diagnostic(self, caplog: pytest.LogCaptureFixture) -> None:
        first = _base_config_payload()
        second = _config_with_experience()
        transport = RecordingTransport(payloads=[first, second])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        caplog.set_level(logging.DEBUG, logger="convert_sdk.diagnostics")
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)

        events = [record.__dict__.get("sdk_event") for record in caplog.records]
        assert "refresh.start" in events
        assert "refresh.success" in events

    def test_unchanged_snapshot_emits_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        payload = _base_config_payload()
        # Both responses are byte-identical, so the second pass should
        # detect equivalence and skip the apply.
        transport = RecordingTransport(payloads=[payload, payload])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        caplog.set_level(logging.DEBUG, logger="convert_sdk.diagnostics")
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)

        events = [record.__dict__.get("sdk_event") for record in caplog.records]
        assert "refresh.skipped" in events
        assert "refresh.success" not in events[1:]  # only init events count


# ---------------------------------------------------------------------------
# Failure handling (AC #3)
# ---------------------------------------------------------------------------


class TestFailureHandling:
    def test_transient_failure_retains_prior_snapshot(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        first = _base_config_payload()
        transport = RecordingTransport(
            payloads=[first],
            fetch_error=RuntimeError("boom"),
            error_starts_at_call=2,  # initial Core fetch succeeds; refreshes fail
        )
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        caplog.set_level(logging.WARNING, logger="convert_sdk.diagnostics")
        with _make_core(transport=transport, refresh=policy) as core:
            initial_snapshot = core.snapshot
            assert core._refresher is not None
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)

            # Refresh failed; the original snapshot is still in place.
            assert core.snapshot is initial_snapshot

        events = [record.__dict__.get("sdk_event") for record in caplog.records]
        assert "refresh.fail" in events

    def test_failure_does_not_crash_host_thread(self) -> None:
        transport = RecordingTransport(
            payloads=[_base_config_payload()],
            fetch_error=RuntimeError("network down"),
            error_starts_at_call=2,
        )
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            for _ in range(3):
                core.refresh_now()
                assert core._refresher.wait_for_next_refresh(timeout=2.0)
            # Worker is still alive after multiple consecutive failures.
            assert core._refresher.is_running

    def test_terminal_callback_fires_at_backoff_cap(self) -> None:
        seen: list[Exception] = []
        transport = RecordingTransport(
            payloads=[_base_config_payload()],
            fetch_error=RuntimeError("persistent"),
            error_starts_at_call=2,
        )
        # Tight backoff math: initial=1, factor=10, max=10. After 1 failure
        # backoff = 1; after 2 failures backoff = 10 (cap reached).
        policy = RefreshConfig(
            interval_seconds=3600.0,
            jitter_seconds=0.0,
            backoff_initial_seconds=1.0,
            backoff_factor=10.0,
            backoff_max_seconds=10.0,
            on_terminal_failure=seen.append,
        )

        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            # First failure: backoff = 1 (below cap), no terminal callback.
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)
            assert seen == []

            # Second failure: backoff = 10 (= cap), terminal callback fires.
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)
            assert len(seen) == 1
            # load_config_snapshot wraps the underlying transport error
            # in the typed ConfigLoadError per Story 4.2 — the callback
            # therefore receives the typed error, not the raw RuntimeError.
            from convert_sdk.errors import ConfigLoadError

            assert isinstance(seen[0], ConfigLoadError)
            assert seen[0].code == "config.fetch_failed"

    def test_terminal_callback_exception_is_suppressed(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        def raising_callback(_exc: Exception) -> None:
            raise ValueError("callback bug")

        transport = RecordingTransport(
            payloads=[_base_config_payload()],
            fetch_error=RuntimeError("persistent"),
            error_starts_at_call=2,
        )
        policy = RefreshConfig(
            interval_seconds=3600.0,
            jitter_seconds=0.0,
            backoff_initial_seconds=10.0,  # already at cap on first failure
            backoff_max_seconds=10.0,
            on_terminal_failure=raising_callback,
        )

        caplog.set_level(logging.ERROR, logger="convert_sdk.refresh")
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)
            # Worker stayed alive despite the misbehaving callback.
            assert core._refresher.is_running

        # The callback's failure is logged on convert_sdk.refresh, not
        # raised into the host thread.
        assert any("callback" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# Lifecycle and adapter contracts
# ---------------------------------------------------------------------------


class TestLifecycle:
    def test_close_stops_refresher_cleanly(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)
        core = _make_core(transport=transport, refresh=policy)
        refresher = core._refresher
        assert refresher is not None
        assert refresher.is_running

        core.close()

        assert not refresher.is_running
        assert transport.closed is True

    def test_close_is_idempotent(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=3600.0)
        core = _make_core(transport=transport, refresh=policy)
        core.close()
        core.close()  # second call is a no-op

    def test_context_manager_closes_on_exit(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=3600.0)
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            assert core._refresher.is_running
        # After __exit__ the worker has been stopped.
        assert transport.closed is True

    def test_refresh_now_is_noop_when_disabled(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        with _make_core(transport=transport, refresh=None) as core:
            # Should not raise; refresher is None.
            core.refresh_now()
            assert transport.fetch_calls == 1  # only the initial fetch

    def test_refresher_uses_supplied_transport(self) -> None:
        # qs / Story 4.4: the refresher must share the same Transport
        # instance the rest of the SDK uses.
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=3600.0)
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            assert core._refresher._transport is transport


# ---------------------------------------------------------------------------
# Atomic snapshot swap and threading (AC #1, NFR16)
# ---------------------------------------------------------------------------


class TestAtomicSwap:
    def test_in_flight_context_creation_sees_coherent_snapshot(self) -> None:
        first = _base_config_payload()
        second = _config_with_experience("checkout")
        transport = RecordingTransport(payloads=[first, second])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            results: list[bool] = []
            stop = threading.Event()

            def worker() -> None:
                # Hammer create_context while the snapshot may be swapping.
                while not stop.is_set():
                    ctx = core.create_context(f"v-{random.random()}")
                    snapshot = ctx._snapshot  # type: ignore[attr-defined]
                    # Coherent means the snapshot's experience index is
                    # consistent with its raw_data: either both empty
                    # (first payload) or both contain "checkout".
                    raw_has = "checkout" in [
                        exp.get("key") for exp in snapshot.raw_data.get("experiences", ())
                    ]
                    index_has = "checkout" in snapshot.experiences_by_key
                    results.append(raw_has == index_has)

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()

            # Give workers a moment, then swap.
            time.sleep(0.05)
            core.refresh_now()
            core._refresher.wait_for_next_refresh(timeout=2.0)
            time.sleep(0.05)

            stop.set()
            for thread in threads:
                thread.join(timeout=2.0)

        assert results
        assert all(results), "snapshot swap exposed an incoherent state to a reader"

    def test_existing_context_retains_prior_snapshot(self) -> None:
        first = _base_config_payload()
        second = _config_with_experience("checkout")
        transport = RecordingTransport(payloads=[first, second])
        policy = RefreshConfig(interval_seconds=3600.0, jitter_seconds=0.0)

        with _make_core(transport=transport, refresh=policy) as core:
            ctx = core.create_context("visitor-1")
            assert ctx.run_experience("checkout") is None

            assert core._refresher is not None
            core.refresh_now()
            assert core._refresher.wait_for_next_refresh(timeout=2.0)

            # Existing context still uses the snapshot it was created
            # with; recreating the context picks up the refreshed config.
            assert ctx.run_experience("checkout") is None
            new_ctx = core.create_context("visitor-1")
            result = new_ctx.run_experience("checkout")
            assert result is not None
            assert result.experience_key == "checkout"


# ---------------------------------------------------------------------------
# Backoff and jitter math (unit-level, no thread)
# ---------------------------------------------------------------------------


class TestBackoffJitterMath:
    def _refresher(
        self, *, policy: RefreshConfig, rng: Optional[random.Random] = None
    ) -> ConfigRefresher:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        config = SDKConfig(sdk_key="k", refresh=policy)
        return ConfigRefresher(
            config,
            transport=transport,
            apply_snapshot=lambda _snapshot: None,
            current_snapshot=lambda: None,
            rng=rng,
        )

    def test_jitter_stays_within_declared_bounds(self) -> None:
        policy = RefreshConfig(interval_seconds=10.0, jitter_seconds=2.0)
        # Deterministic RNG so the test is reproducible.
        refresher = self._refresher(policy=policy, rng=random.Random(1234))
        for _ in range(50):
            sleep = refresher._compute_sleep_seconds()
            assert 8.0 <= sleep <= 12.0

    def test_no_jitter_returns_exact_interval(self) -> None:
        policy = RefreshConfig(interval_seconds=42.0, jitter_seconds=0.0)
        refresher = self._refresher(policy=policy)
        assert refresher._compute_sleep_seconds() == 42.0

    def test_backoff_grows_exponentially_until_cap(self) -> None:
        policy = RefreshConfig(
            interval_seconds=600.0,
            jitter_seconds=0.0,
            backoff_initial_seconds=2.0,
            backoff_factor=3.0,
            backoff_max_seconds=20.0,
        )
        refresher = self._refresher(policy=policy)
        # Failure 1: 2 * 3^0 = 2
        refresher._consecutive_failures = 1
        assert refresher._compute_sleep_seconds() == 2.0
        # Failure 2: 2 * 3^1 = 6
        refresher._consecutive_failures = 2
        assert refresher._compute_sleep_seconds() == 6.0
        # Failure 3: 2 * 3^2 = 18
        refresher._consecutive_failures = 3
        assert refresher._compute_sleep_seconds() == 18.0
        # Failure 4: 2 * 3^3 = 54 -> cap at 20
        refresher._consecutive_failures = 4
        assert refresher._compute_sleep_seconds() == 20.0


# ---------------------------------------------------------------------------
# Constructor guards
# ---------------------------------------------------------------------------


class TestConstructorGuards:
    def test_rejects_when_refresh_policy_missing(self) -> None:
        config = SDKConfig(sdk_key="k", refresh=None)
        transport = RecordingTransport(payloads=[_base_config_payload()])
        with pytest.raises(ValueError, match="SDKConfig.refresh"):
            ConfigRefresher(
                config,
                transport=transport,
                apply_snapshot=lambda _s: None,
                current_snapshot=lambda: None,
            )

    def test_rejects_when_initialised_from_direct_config(self) -> None:
        config = SDKConfig(
            config_data=_base_config_payload(),
            refresh=RefreshConfig(),
        )
        transport = RecordingTransport()
        with pytest.raises(ValueError, match="config_data"):
            ConfigRefresher(
                config,
                transport=transport,
                apply_snapshot=lambda _s: None,
                current_snapshot=lambda: None,
            )

    def test_start_is_idempotent(self) -> None:
        transport = RecordingTransport(payloads=[_base_config_payload()])
        policy = RefreshConfig(interval_seconds=3600.0)
        with _make_core(transport=transport, refresh=policy) as core:
            assert core._refresher is not None
            initial_thread = core._refresher._thread
            core._refresher.start()
            # start() does nothing on a started refresher.
            assert core._refresher._thread is initial_thread
