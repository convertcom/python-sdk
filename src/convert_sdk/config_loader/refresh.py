"""Background config refresh worker (Story 5.2 — opt-in, post-MVP).

The worker runs on a daemon thread and pulls fresh config through the same
``Transport`` Protocol used at initialisation. New snapshots are applied
through a single attribute swap on ``Core`` so any in-flight evaluation
sees either the old or the new ``ConfigSnapshot``, never a partial state.

Refresh is opt-in: ``Core`` only spins up a refresher when the caller
passes ``SDKConfig.refresh=RefreshConfig(...)``. With the default
``refresh=None``, MVP behaviour is preserved byte-for-byte.

Failure handling follows a small set of frozen rules:

- Exceptions inside the worker are caught and logged through the SDK's
  diagnostic logger; they never bubble out of the daemon thread.
- Transient failures back off exponentially up to ``backoff_max_seconds``
  but the worker never gives up — there is no "stop after N failures"
  switch because that would silently freeze a long-running service on
  stale config.
- ``RefreshConfig.on_terminal_failure`` is called once per failure once
  the consecutive-failure count crosses the backoff cap. It exists so
  hosts can surface a typed alert through their own logger or metrics
  pipeline; an unhandled exception inside the callback is itself caught
  and never crashes the worker.
"""

from __future__ import annotations

import logging
import random
import threading
from typing import Callable, Optional

from ..config import RefreshConfig, SDKConfig
from ..diagnostics import config_source, log_diagnostic_event, snapshot_entity_counts
from ..domain.config_snapshot import ConfigSnapshot
from ..ports.transport import Transport
from .loader import load_config_snapshot


SnapshotApplier = Callable[[ConfigSnapshot], None]
SnapshotProvider = Callable[[], Optional[ConfigSnapshot]]


REFRESH_LOGGER_NAME = "convert_sdk.refresh"
_logger = logging.getLogger(REFRESH_LOGGER_NAME)


class ConfigRefresher:
    """Daemon-thread-backed config refresher for long-running services.

    The refresher reuses the SDK's existing config-loading pipeline:
    ``load_config_snapshot`` performs validation and snapshot construction,
    then the supplied ``apply_snapshot`` callback installs the result on
    ``Core``. The refresher has no opinion about *how* the swap is done;
    that lives in ``Core`` and is a single attribute assignment today.
    """

    def __init__(
        self,
        config: SDKConfig,
        *,
        transport: Transport,
        apply_snapshot: SnapshotApplier,
        current_snapshot: SnapshotProvider,
        rng: Optional[random.Random] = None,
    ) -> None:
        if config.refresh is None:
            raise ValueError(
                "ConfigRefresher requires SDKConfig.refresh to be set; refusing to start."
            )
        if config.config_data is not None:
            raise ValueError(
                "ConfigRefresher cannot run when SDKConfig.config_data is provided; "
                "direct config has no remote endpoint to refresh from.",
            )
        self._config = config
        self._policy: RefreshConfig = config.refresh
        self._transport = transport
        self._apply_snapshot = apply_snapshot
        self._current_snapshot = current_snapshot
        self._rng = rng or random.Random()

        self._stop_event = threading.Event()
        self._wake_event = threading.Event()
        self._refresh_completed = threading.Event()
        self._consecutive_failures = 0
        self._thread: Optional[threading.Thread] = None
        self._started = False

    @property
    def is_running(self) -> bool:
        """Return whether the refresher daemon thread is alive."""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def start(self) -> None:
        """Spin up the daemon thread. Idempotent."""

        if self._started:
            return
        self._started = True
        self._thread = threading.Thread(
            target=self._run,
            name="convert-sdk-config-refresh",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: Optional[float] = 2.0) -> None:
        """Signal the worker to exit and wait briefly for it to finish."""

        self._stop_event.set()
        self._wake_event.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout)

    def trigger_now(self) -> None:
        """Wake the worker immediately to perform a refresh attempt."""

        self._refresh_completed.clear()
        self._wake_event.set()

    def wait_for_next_refresh(self, timeout: float = 5.0) -> bool:
        """Block until the next refresh attempt completes (test seam)."""

        return self._refresh_completed.wait(timeout)

    # ------------------------------------------------------------------
    # internal loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # The worker iterates: sleep for the next interval, attempt a
        # refresh, then loop. Sleeps are interruptible so stop() and
        # trigger_now() get sub-second response latency.
        while not self._stop_event.is_set():
            sleep_seconds = self._compute_sleep_seconds()
            self._wake_event.wait(sleep_seconds)
            self._wake_event.clear()
            if self._stop_event.is_set():
                return
            self._do_refresh()

    def _do_refresh(self) -> None:
        source = config_source(self._config.config_data, self._config.sdk_key)
        log_diagnostic_event(
            "refresh.start",
            source=source,
            consecutive_failures=self._consecutive_failures,
        )
        try:
            new_snapshot = load_config_snapshot(self._config, transport=self._transport)
        except Exception as exc:
            self._handle_failure(exc, source=source)
            return

        previous = self._current_snapshot()
        if previous is not None and _snapshots_equal(previous, new_snapshot):
            log_diagnostic_event(
                "refresh.skipped",
                source=source,
                reason="snapshot_unchanged",
                consecutive_failures=self._consecutive_failures,
            )
            self._consecutive_failures = 0
            self._refresh_completed.set()
            return

        try:
            self._apply_snapshot(new_snapshot)
        except Exception as exc:
            # Apply callbacks should never fail in practice, but if a host
            # supplies an exotic Core subclass that breaks here we still
            # need to keep the worker alive.
            self._handle_failure(exc, source=source, phase="apply")
            return

        self._consecutive_failures = 0
        log_diagnostic_event(
            "refresh.success",
            source=source,
            entity_counts=snapshot_entity_counts(new_snapshot),
        )
        self._refresh_completed.set()

    def _handle_failure(
        self,
        exc: Exception,
        *,
        source: str,
        phase: str = "fetch",
    ) -> None:
        self._consecutive_failures += 1
        at_terminal_backoff = (
            self._compute_backoff_seconds() >= self._policy.backoff_max_seconds
        )
        log_diagnostic_event(
            "refresh.fail",
            level=logging.WARNING,
            source=source,
            phase=phase,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None),
            consecutive_failures=self._consecutive_failures,
            at_terminal_backoff=at_terminal_backoff,
        )
        if at_terminal_backoff:
            self._invoke_terminal_callback(exc)
        self._refresh_completed.set()

    def _invoke_terminal_callback(self, exc: Exception) -> None:
        callback = self._policy.on_terminal_failure
        if callback is None:
            return
        try:
            callback(exc)
        except Exception as callback_exc:
            # Belt-and-braces: a misbehaving callback must never crash the
            # worker thread or surface an exception to the host process.
            _logger.exception(
                "Refresh terminal-failure callback raised %s; suppressing to keep refresh worker alive.",
                type(callback_exc).__name__,
            )

    def _compute_sleep_seconds(self) -> float:
        if self._consecutive_failures > 0:
            return self._compute_backoff_seconds()
        # Healthy steady-state cadence: interval ± jitter.
        jitter = self._policy.jitter_seconds
        if jitter > 0:
            offset = self._rng.uniform(-jitter, jitter)
        else:
            offset = 0.0
        return max(0.0, self._policy.interval_seconds + offset)

    def _compute_backoff_seconds(self) -> float:
        # Exponential backoff: initial * factor^(failures-1), capped at max.
        # Failures < 1 short-circuits to interval (handled by caller).
        exponent = max(0, self._consecutive_failures - 1)
        raw = self._policy.backoff_initial_seconds * (self._policy.backoff_factor**exponent)
        return min(raw, self._policy.backoff_max_seconds)


def _snapshots_equal(previous: ConfigSnapshot, candidate: ConfigSnapshot) -> bool:
    """Return whether two snapshots carry equivalent raw config data."""

    # raw_data is a frozen MappingProxy of the validated config payload.
    # Comparing it against the freshly-loaded payload is enough to decide
    # whether anything user-observable changed; the per-entity indexes
    # are derived state.
    return dict(previous.raw_data) == dict(candidate.raw_data)
