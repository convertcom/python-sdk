"""Background config refresh worker (Story 5.2 — opt-in, post-MVP).

The worker runs on a daemon thread and pulls fresh config through the same
``Transport`` Protocol used at initialisation. New snapshots are applied
through a single attribute swap on ``Core`` so any in-flight evaluation
sees either the old or the new ``ConfigSnapshot``, never a partial state.

Refresh is opt-in: ``Core`` only spins up a refresher when the caller
passes ``SDKConfig.refresh=RefreshConfig(...)``. With the default
``refresh=None``, MVP behaviour is preserved.

Failure handling follows a small set of frozen rules:

- Exceptions inside the worker are caught and logged through the SDK's
  diagnostic logger; they never bubble out of the daemon thread.
- Transient failures back off exponentially up to ``backoff_max_seconds``;
  the worker keeps retrying because silently freezing on stale config is
  worse than periodic retries.
- ``ConfigValidationError`` (the upstream returned a structurally bad
  payload) is treated as terminal: the callback fires once, the worker
  stops, and ``RefresherStatus.is_running`` flips to False so the host
  can detect the condition. Retrying the same broken payload is futile.
- ``RefreshConfig.on_terminal_failure`` is called once per failure once
  the consecutive-failure count reaches the backoff cap, and once on a
  ``ConfigValidationError``. An unhandled exception inside the callback
  is caught and never crashes the worker.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import weakref
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional

from ..config import RefreshConfig, SDKConfig
from ..diagnostics import config_source, log_diagnostic_event, snapshot_entity_counts
from ..domain.config_snapshot import ConfigSnapshot
from ..errors import ConfigValidationError
from ..ports.transport import Transport
from .loader import load_config_snapshot


SnapshotApplier = Callable[[ConfigSnapshot], None]
SnapshotProvider = Callable[[], Optional[ConfigSnapshot]]


REFRESH_LOGGER_NAME = "convert_sdk.refresh"
_logger = logging.getLogger(REFRESH_LOGGER_NAME)


@dataclass(frozen=True)
class RefresherStatus:
    """Read-only snapshot of refresh-worker state for host observability.

    Timestamps are timezone-aware ``datetime`` instances (UTC) to align
    with the rest of the public API (``LifecycleEventPayload.occurred_at``).
    """

    enabled: bool
    is_running: bool
    consecutive_failures: int
    last_refresh_at: Optional[datetime]
    last_success_at: Optional[datetime]
    last_error_type: Optional[str]
    last_error_at: Optional[datetime]
    forked_in_child: bool
    terminal_failure: bool


class ConfigRefresher:
    """Daemon-thread-backed config refresher for long-running services.

    The refresher reuses the SDK's existing config-loading pipeline:
    ``load_config_snapshot`` performs validation and snapshot construction,
    then the supplied ``apply_snapshot`` callback installs the result on
    ``Core``. The refresher has no opinion about *how* the swap is done;
    that lives in ``Core``.
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

        self._last_refresh_at: Optional[datetime] = None
        self._last_success_at: Optional[datetime] = None
        self._last_error_type: Optional[str] = None
        self._last_error_at: Optional[datetime] = None
        self._forked_in_child = False
        self._terminal_failure = False

        self._fork_hook_registered = False

    @property
    def is_running(self) -> bool:
        """Return whether the refresher daemon thread is alive."""

        thread = self._thread
        return thread is not None and thread.is_alive()

    def status(self) -> RefresherStatus:
        """Return a read-only snapshot of the worker state."""

        return RefresherStatus(
            enabled=True,
            is_running=self.is_running,
            consecutive_failures=self._consecutive_failures,
            last_refresh_at=self._last_refresh_at,
            last_success_at=self._last_success_at,
            last_error_type=self._last_error_type,
            last_error_at=self._last_error_at,
            forked_in_child=self._forked_in_child,
            terminal_failure=self._terminal_failure,
        )

    def start(self) -> None:
        """Spin up the daemon thread. Idempotent."""

        if self._started:
            return
        self._started = True
        self._register_fork_hook()
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
        """Block until the next refresh attempt completes."""

        return self._refresh_completed.wait(timeout)

    # ------------------------------------------------------------------
    # internal loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        # The worker iterates: sleep for the next interval, attempt a
        # refresh, then loop. Sleeps are interruptible so stop() and
        # trigger_now() get sub-second response latency.
        #
        # The outer guard catches anything _do_refresh's own try/except
        # cannot reach — a logging filter that raises, a clock subsystem
        # error, an exhausted RNG. Without it the daemon thread would
        # silently die and is_running would quietly flip to False; the
        # service would then sit on stale config indefinitely (exactly
        # the failure mode 5.2 promises to prevent). We surface a clean
        # diagnostic and exit instead of pretending nothing happened.
        try:
            while not self._stop_event.is_set():
                sleep_seconds = self._compute_sleep_seconds()
                self._wake_event.wait(sleep_seconds)
                self._wake_event.clear()
                if self._stop_event.is_set():
                    return
                self._do_refresh()
        except BaseException as exc:
            # Catch ``BaseException`` (not just ``Exception``) so a
            # logging filter that calls ``sys.exit``, a worker-thread
            # ``KeyboardInterrupt``, or any other non-Exception escape
            # cannot kill the daemon thread silently — exactly the
            # failure mode the comment above promises to prevent.
            log_diagnostic_event(
                "refresh.worker_crashed",
                level=logging.ERROR,
                error_type=type(exc).__name__,
                error_code=getattr(exc, "code", None),
            )
            _logger.exception(
                "Refresh worker thread exiting due to unexpected %s; refresh is now stopped.",
                type(exc).__name__,
            )
            # Unblock anyone awaiting wait_for_next_refresh so they don't
            # hang forever on a worker that has just exited. Do not
            # re-raise: a daemon thread crashing should not bring down
            # the host process.
            self._refresh_completed.set()

    def _do_refresh(self) -> None:
        # Clear at the start of every attempt so wait_for_next_refresh()
        # always reflects "the next refresh that has not yet finished" —
        # not a stale set from a prior healthy tick.
        self._refresh_completed.clear()
        source = config_source(self._config.config_data, self._config.sdk_key)
        log_diagnostic_event(
            "refresh.start",
            source=source,
            consecutive_failures=self._consecutive_failures,
        )
        self._last_refresh_at = datetime.now(timezone.utc)
        try:
            new_snapshot = load_config_snapshot(self._config, transport=self._transport)
        except ConfigValidationError as exc:
            # Bad upstream payload: retrying the same broken response is
            # futile and the worker should stop so the host detects the
            # terminal condition. Fire the callback once, mark the worker
            # terminated, and exit the loop.
            self._handle_terminal_failure(exc, source=source, phase="validate")
            return
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
            self._last_success_at = datetime.now(timezone.utc)
            self._refresh_completed.set()
            return

        try:
            self._apply_snapshot(new_snapshot)
        except Exception as exc:
            # Apply callbacks should never fail in practice. If a host
            # supplies a Core subclass that does break here, treat it as
            # terminal: it indicates a programmer bug, not a transient
            # condition, and silent retry would mask the bug.
            self._handle_terminal_failure(exc, source=source, phase="apply")
            return

        self._consecutive_failures = 0
        self._last_success_at = datetime.now(timezone.utc)
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
        self._last_error_type = type(exc).__name__
        self._last_error_at = datetime.now(timezone.utc)
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

    def _handle_terminal_failure(
        self,
        exc: Exception,
        *,
        source: str,
        phase: str,
    ) -> None:
        # Record the failure, fire the terminal callback once, stop the
        # loop. The worker exits cleanly via the _stop_event so any
        # waiter on wait_for_next_refresh sees _refresh_completed set.
        self._consecutive_failures += 1
        self._last_error_type = type(exc).__name__
        self._last_error_at = datetime.now(timezone.utc)
        self._terminal_failure = True
        log_diagnostic_event(
            "refresh.terminal_failure",
            level=logging.ERROR,
            source=source,
            phase=phase,
            error_type=type(exc).__name__,
            error_code=getattr(exc, "code", None),
            consecutive_failures=self._consecutive_failures,
        )
        self._invoke_terminal_callback(exc)
        self._stop_event.set()
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

    # ------------------------------------------------------------------
    # fork detection
    # ------------------------------------------------------------------

    def _register_fork_hook(self) -> None:
        # Daemon threads do not survive os.fork() in the child. A forked
        # worker (Gunicorn, uWSGI prefork) silently inherits a dead
        # thread; without detection, is_running flips to False with no
        # diagnostic and the service runs on stale config indefinitely.
        # Hook into os.register_at_fork via a weakref so the callback is
        # a no-op once this refresher is GC'd.
        if self._fork_hook_registered:
            return
        register = getattr(os, "register_at_fork", None)
        if register is None:
            # Windows / runtimes without fork support — there is nothing
            # to detect here.
            return
        ref = weakref.ref(self)

        def _after_fork_in_child() -> None:
            instance = ref()
            if instance is None:
                return
            instance._on_fork_in_child()

        try:
            register(after_in_child=_after_fork_in_child)
            self._fork_hook_registered = True
        except (RuntimeError, ValueError):
            # Some restricted runtimes refuse register_at_fork. Failing
            # silently is safe — fork detection is best-effort.
            pass

    def _on_fork_in_child(self) -> None:
        # The daemon thread is dead in the child. Reflect that in the
        # state, surface a diagnostic, and unblock anyone waiting on
        # wait_for_next_refresh so they don't hang on a defunct worker.
        self._thread = None
        self._forked_in_child = True
        log_diagnostic_event(
            "refresh.fork_detected",
            level=logging.WARNING,
            pid=os.getpid(),
        )
        self._refresh_completed.set()


def _snapshots_equal(previous: ConfigSnapshot, candidate: ConfigSnapshot) -> bool:
    """Return whether two snapshots carry equivalent raw config data."""

    # raw_data is a frozen MappingProxy of the validated config payload.
    # Comparing the raw payload covers everything user-observable; the
    # per-entity indexes are derived state.
    return previous.raw_data == candidate.raw_data
