"""Background automatic config refresh (Story 5.2, FR31 — post-MVP, opt-in).

``ConfigRefresher`` is a sync-first daemon-thread worker that periodically
re-fetches remote config through the **same** :class:`~convert_sdk.ports.transport.Transport`
Protocol used at initialization (Story 1.2 — no parallel transport) and the
**same** :func:`~convert_sdk.config_loader.loader.load_snapshot` pipeline
(validation + normalization + immutable snapshot construction). A successfully
loaded snapshot is handed to the ``on_snapshot`` callback, which performs the
atomic swap on :class:`~convert_sdk.core.Core` (see ADR 0001).

Design (see ``docs/adr/0001-config-refresh-concurrency-and-backoff.md``):

* **Opt-in only.** Nothing here runs unless ``SDKConfig.refresh`` is a
  :class:`~convert_sdk.config.RefreshConfig`. ``refresh=None`` constructs no
  worker (Critical Warning #1).
* **Deterministic test seam — no wall-clock dependency.** The scheduled wait is
  an interruptible :class:`threading.Event` wait. Tests drive the worker with
  :meth:`trigger_now` (fire an immediate cycle) and
  :meth:`wait_for_next_refresh` (block until the next cycle finishes), so the
  suite never sleeps on real time. The ``ports/clock.py`` Protocol mentioned in
  the story is intentionally not introduced — this event-driven seam achieves
  the same determinism without a speculative port (recorded in the readiness
  assessment).
* **Sync-first daemon thread.** Async surfaces are Story 5.3's concern
  (Critical Warning #5).
* **Process-local.** No cross-process coordination (NFR9 / Critical Warning #6).

Failure handling, backoff, diagnostic events, and ``CONFIG_UPDATED`` emission
(Story 5.2 Tasks 3) layer on top of this worker; this module owns the worker
loop, the swap-callback dispatch, and the direct-config guard.
"""

from __future__ import annotations

import logging
import random
import threading
from typing import TYPE_CHECKING, Callable, Optional

from convert_sdk.config_loader.loader import load_snapshot
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.errors import InvalidConfigError
from convert_sdk.events import LifecycleEvent
from convert_sdk.logging import log_safe

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.config import RefreshConfig, SDKConfig
    from convert_sdk.ports.transport import Transport

#: Callback invoked with each successfully loaded refreshed snapshot. The
#: implementation (``Core._apply_refreshed_snapshot``) performs the atomic swap.
SnapshotCallback = Callable[[ConfigSnapshot], None]
#: Callback invoked once per failure after the backoff cap is reached so the
#: host can surface the typed error. Never raises into the worker loop.
TerminalFailureCallback = Callable[[BaseException], None]


class ConfigRefresher:
    """Daemon-thread worker that periodically refreshes the config snapshot.

    Args:
        config: The SDK config. Must be in remote (``sdk_key``) mode with a
            non-``None`` :attr:`~convert_sdk.config.SDKConfig.refresh` policy —
            direct-config mode is rejected (there is no endpoint to poll).
        transport: The configured transport (Story 4.4 adapter substitution is
            honored — Core passes whatever transport it resolved at init).
        on_snapshot: Callback applied to each successfully refreshed snapshot.
        on_terminal_failure: Optional callback fired once per failure after the
            backoff cap is reached (Story 5.2 Task 3 wires AC-3's typed-error
            surface here). Defaults to a no-op.
        logger: Optional logger for diagnostic events (defaults to the package
            logger via :func:`log_safe`).
    """

    def __init__(
        self,
        *,
        config: "SDKConfig",
        transport: "Transport",
        on_snapshot: SnapshotCallback,
        on_terminal_failure: Optional[TerminalFailureCallback] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        if config.is_direct_config:
            # No remote endpoint to poll — refusing to spin up a useless worker.
            raise InvalidConfigError(
                "ConfigRefresher requires remote (sdk_key) config; direct-config "
                "mode has no endpoint to refresh from"
            )
        if config.refresh is None:
            raise InvalidConfigError(
                "ConfigRefresher requires a non-None SDKConfig.refresh policy"
            )
        self._config = config
        self._policy: "RefreshConfig" = config.refresh
        self._transport = transport
        self._on_snapshot = on_snapshot
        self._on_terminal_failure = on_terminal_failure
        self._logger = logger if logger is not None else config.logger

        # Interruptible-wait seam: the worker waits on ``_wake`` for the
        # scheduled interval; ``trigger_now``/``stop`` set it to break the wait.
        self._wake = threading.Event()
        self._stopping = threading.Event()
        # Signalled after each completed cycle (success OR handled failure) so
        # ``wait_for_next_refresh`` is deterministic without a wall-clock sleep.
        self._cycle_done = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._consecutive_failures = 0
        self._rng = random.Random()

    # --- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Start the daemon refresh thread (idempotent)."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stopping.clear()
        thread = threading.Thread(
            target=self._run,
            name="convert-sdk-config-refresh",
            daemon=True,
        )
        self._thread = thread
        thread.start()

    def stop(self, *, timeout: float = 5.0) -> None:
        """Signal the worker to stop and join the thread (idempotent)."""
        self._stopping.set()
        self._wake.set()
        thread = self._thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
        self._thread = None

    def is_alive(self) -> bool:
        """True while the daemon refresh thread is running."""
        return self._thread is not None and self._thread.is_alive()

    def is_daemon(self) -> bool:
        """True if the worker thread is a daemon (does not block interpreter exit)."""
        return self._thread is not None and self._thread.daemon

    # --- test / control seams ---------------------------------------------

    def trigger_now(self) -> None:
        """Wake the worker to perform a refresh cycle immediately.

        Also the seam ``Core.refresh_now`` uses to force an out-of-band refresh.
        """
        self._cycle_done.clear()
        self._wake.set()

    def wait_for_next_refresh(self, *, timeout: float = 5.0) -> bool:
        """Block until the next refresh cycle completes (deterministic test seam).

        Returns ``True`` if a cycle completed within ``timeout``, else ``False``.
        """
        return self._cycle_done.wait(timeout=timeout)

    # --- worker loop -------------------------------------------------------

    def _run(self) -> None:
        """The daemon loop: wait, (maybe) refresh, repeat until stopped.

        Wrapped in an outer guard (Story 5.2 hardening) so an unexpected error
        escaping :meth:`_do_refresh` emits ``refresh.worker_crashed`` and unblocks
        any waiter rather than silently killing the daemon thread.
        """
        while not self._stopping.is_set():
            wait_seconds = self._next_wait_seconds()
            # Interruptible wait: returns early when ``trigger_now``/``stop`` set
            # the event; otherwise times out after the scheduled interval.
            self._wake.wait(timeout=wait_seconds)
            self._wake.clear()
            if self._stopping.is_set():
                break
            try:
                self._do_refresh()
            except Exception:  # pragma: no cover - defended; see Task 3 guard
                # Outer resilience guard. _do_refresh handles its own transport
                # failures (Task 3); reaching here means a logging/clock/callback
                # subsystem failure escaped. Emit and keep the worker alive.
                log_safe(
                    LifecycleEvent.CONFIG_UPDATED,
                    level=logging.ERROR,
                    target=self._logger,
                    refresh_phase="worker_crashed",
                )
            finally:
                # Unblock any deterministic waiter regardless of outcome.
                self._cycle_done.set()

    def _do_refresh(self) -> None:
        """Fetch + load + swap one refreshed snapshot.

        Story 5.2 Task 3 extends this with diagnostic events, backoff, and the
        terminal-failure callback. Task 2 establishes the happy path and the
        callback dispatch; failure handling here keeps the prior snapshot intact
        by simply re-raising to the worker's per-cycle boundary (Task 3 replaces
        the bare propagation with backoff + diagnostics).
        """
        raw = self._transport.fetch_config(self._config)
        snapshot = load_snapshot(raw)
        self._consecutive_failures = 0
        self._on_snapshot(snapshot)

    def _next_wait_seconds(self) -> float:
        """Compute the next interruptible-wait duration (interval + jitter).

        Backoff on consecutive failures is layered in by Task 3; with no
        failures this is ``interval_seconds + U(0, jitter_seconds)``.
        """
        base = self._policy.interval_seconds
        if self._consecutive_failures > 0:
            backed_off = base * (self._policy.backoff_factor ** self._consecutive_failures)
            base = min(backed_off, self._policy.backoff_max_seconds)
        jitter = (
            self._rng.uniform(0.0, self._policy.jitter_seconds)
            if self._policy.jitter_seconds > 0
            else 0.0
        )
        return base + jitter
