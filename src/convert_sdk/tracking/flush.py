"""Queue-flush lifecycle hooks for the Convert Python SDK (Story 2.3 / qs-07).

Exposes the three frozen flush function names that Stories 2.3 and 2.4 depend
on (qs-07 #Code-Map), each delegating to a flushable's single shared release
path so there is never a second release implementation (Critical Warning #4):

* :func:`flush` — release the queue now (explicit flush).
* :func:`setup_periodic_flush` — opt-in periodic release via a **daemonic**
  ``threading.Timer`` driven by ``auto_flush_interval_ms``. Default behavior
  (interval ``None``) is explicit-flush-only.
* :func:`register_atexit_flush` — best-effort final release on interpreter
  shutdown via ``atexit.register``.

A "flushable" is anything exposing a zero-arg ``flush()`` (e.g.
:class:`~convert_sdk.core.Core` or :class:`~convert_sdk.tracking.tracker.Tracker`),
so these helpers stay decoupled from Core's full surface.

Runtime-lifecycle decisions (architecture #Queue-Lifecycle-and-Python-Runtime-Matrix):

* The default lifecycle is **explicit-flush-only** — safe in every runtime.
  Periodic flush is NEVER the default because a timed flush silently loses
  events in short-lived runtimes (Lambda/CLI).
* The periodic timer thread is **daemonic** so it never blocks interpreter
  shutdown. ``threading.Timer.__init__`` does NOT accept a ``daemon`` argument,
  so ``timer.daemon = True`` is set explicitly AFTER construction and BEFORE
  ``start()`` (F-058/F-059). A daemonic timer is silently skipped if the
  process exits before it fires — the correct, documented behavior for
  Lambda/Cloud Run/CLI where non-daemonic background threads hang process exit.
* ``atexit`` is best-effort — it does NOT fire under ``SIGKILL`` or in some
  serverless runtimes. Never rely on it as the sole delivery path.

SIGTERM handling is intentionally NOT auto-registered (Critical Warning #6); the
recommended pattern is documented as a code comment below and in
``docs/runtime-integration.md`` so containerized deployments can opt in
explicitly without the SDK installing surprising process-level signal handlers.
"""

from __future__ import annotations

import atexit
import threading
from typing import Callable, Optional, Protocol


class Flushable(Protocol):
    """Anything with a zero-arg ``flush()`` release entry point."""

    def flush(self) -> None: ...


def flush(flushable: Flushable) -> None:
    """Release the queue now by delegating to the flushable's ``flush()``.

    The frozen explicit-flush entry point (qs-07). Routes through the
    flushable's single shared release path; an empty queue is a safe no-op.
    """
    flushable.flush()


def setup_periodic_flush(
    flushable: Flushable,
    interval_ms: Optional[int],
) -> Optional["PeriodicFlusher"]:
    """Opt into periodic background flushes via a daemonic ``threading.Timer``.

    When ``interval_ms`` is ``None`` (the default lifecycle), periodic flush is
    disabled and this returns ``None`` — the queue is released only on explicit
    :func:`flush` (or batch-size release). When a positive interval is given,
    starts a daemonic, self-rescheduling timer that calls the flushable's
    ``flush()`` every ``interval_ms`` milliseconds and returns a
    :class:`PeriodicFlusher` the caller can :meth:`PeriodicFlusher.cancel`.

    The timer thread is daemonic so it never blocks interpreter shutdown; if the
    process exits before the timer fires the flush is silently skipped (the
    documented, correct behavior for short-lived runtimes).
    """
    if interval_ms is None:
        return None
    # Prefer a trigger-specific timeout release entry point when the flushable
    # exposes one (Story 2.4: so the periodic release reports
    # ``ReleaseReason.TIMEOUT`` on its ``API_QUEUE_RELEASED`` event). Fall back
    # to the generic ``flush()`` for any plain :class:`Flushable`.
    callback = getattr(flushable, "flush_timeout", flushable.flush)
    flusher = PeriodicFlusher(callback, interval_ms)
    flusher.start()
    return flusher


def register_atexit_flush(flushable: Flushable) -> Callable[[], None]:
    """Register a best-effort final flush on interpreter shutdown (``atexit``).

    Returns the registered callback so a caller can ``atexit.unregister`` it.
    Best-effort only: ``atexit`` does NOT fire under ``SIGKILL`` or in some
    serverless runtimes, and any exception during the final flush is swallowed
    so shutdown never crashes (a never-flushed process must exit cleanly even if
    it silently drops events — NFR18).
    """

    def _final_flush() -> None:
        # contextlib.suppress would drop the `# pragma: no cover` that keeps this
        # unreachable-at-test-time shutdown path out of the coverage floor, so the
        # explicit try/except is retained deliberately (SIM105 waived here only).
        try:  # noqa: SIM105
            flushable.flush()
        except Exception:  # pragma: no cover - shutdown best-effort
            # Never let a shutdown-time delivery failure crash the interpreter.
            pass

    atexit.register(_final_flush)
    return _final_flush


# ---------------------------------------------------------------------------
# SIGTERM pattern — DOCUMENTED ONLY, never auto-registered (Critical Warning #6).
#
# Containers (Cloud Run, ECS, k8s) receive SIGTERM before shutdown. To flush on
# SIGTERM, register a handler explicitly in YOUR process — the SDK will not do
# this for you, to avoid installing surprising process-level signal handlers:
#
#     import signal
#     def _handle_sigterm(signum, frame):
#         core.flush()          # best-effort final delivery
#         raise SystemExit(0)
#     signal.signal(signal.SIGTERM, _handle_sigterm)
#
# See docs/runtime-integration.md for per-runtime guidance.
# ---------------------------------------------------------------------------


class PeriodicFlusher:
    """A daemonic, self-rescheduling periodic flush driver.

    Wraps a ``threading.Timer`` chain: each fire calls ``callback`` then
    reschedules itself until :meth:`cancel` is called. The underlying timer
    threads are daemonic (``timer.daemon = True`` set explicitly after
    construction, before ``start()`` — F-058/F-059) so they never block
    interpreter shutdown.
    """

    def __init__(self, callback: Callable[[], None], interval_ms: int) -> None:
        self._callback = callback
        self._interval_s = interval_ms / 1000.0
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._cancelled = False

    def start(self) -> None:
        """Schedule the first flush tick."""
        self._schedule()

    def _schedule(self) -> None:
        with self._lock:
            if self._cancelled:
                return
            timer = threading.Timer(self._interval_s, self._fire)
            # threading.Timer.__init__ does NOT accept daemon=; set it on the
            # underlying thread explicitly AFTER construction, BEFORE start()
            # (F-058/F-059) so the timer never blocks process exit.
            timer.daemon = True
            self._timer = timer
            timer.start()

    def _fire(self) -> None:
        try:
            self._callback()
        except Exception:  # pragma: no cover - periodic best-effort
            # A periodic-flush delivery failure must not kill the timer thread
            # or crash the process; the queue is left intact for the next tick
            # or an explicit flush.
            pass
        finally:
            self._schedule()

    def cancel(self) -> None:
        """Stop further periodic flushes (does not flush a final time)."""
        with self._lock:
            self._cancelled = True
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
