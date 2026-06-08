"""Story 2.3 — flush lifecycle unit tests (BE-4).

Unit-level coverage of the ``tracking/flush.py`` runtime hooks (the qs-07
runtime *scenario matrix* lives in ``tests/integration/test_queue_lifecycle.py``):

* ``flush()`` delegates to the flushable's single release path.
* ``setup_periodic_flush(None)`` is disabled (explicit-flush-only default) and
  returns ``None``; a positive interval starts a DAEMONIC timer that fires.
* The periodic timer thread is daemonic so it never blocks process exit
  (F-058/F-059).
* ``register_atexit_flush`` registers a best-effort callback that swallows
  delivery errors so shutdown never crashes (NFR18).
"""

import atexit
import time

from convert_sdk.tracking.flush import (
    PeriodicFlusher,
    flush,
    register_atexit_flush,
    setup_periodic_flush,
)


class _Spy:
    def __init__(self, fail=False):
        self.count = 0
        self.fail = fail

    def flush(self):
        self.count += 1
        if self.fail:
            raise RuntimeError("delivery boom")


def test_flush_delegates_to_flushable():
    spy = _Spy()
    flush(spy)
    assert spy.count == 1


def test_setup_periodic_flush_none_is_disabled():
    spy = _Spy()
    assert setup_periodic_flush(spy, None) is None
    assert spy.count == 0


def test_setup_periodic_flush_starts_daemonic_timer_that_fires():
    spy = _Spy()
    flusher = setup_periodic_flush(spy, interval_ms=20)
    assert isinstance(flusher, PeriodicFlusher)
    try:
        # Wait for at least one tick.
        deadline = time.time() + 2.0
        while spy.count < 1 and time.time() < deadline:
            time.sleep(0.01)
        assert spy.count >= 1
    finally:
        flusher.cancel()


def test_periodic_timer_thread_is_daemonic():
    spy = _Spy()
    flusher = PeriodicFlusher(spy.flush, interval_ms=10_000)
    flusher.start()
    try:
        # The scheduled timer thread must be daemonic so it never blocks exit.
        assert flusher._timer is not None
        assert flusher._timer.daemon is True
    finally:
        flusher.cancel()


def test_periodic_flush_swallows_errors_and_keeps_ticking():
    spy = _Spy(fail=True)
    flusher = setup_periodic_flush(spy, interval_ms=15)
    try:
        deadline = time.time() + 2.0
        while spy.count < 2 and time.time() < deadline:
            time.sleep(0.01)
        # Despite each flush raising, the timer kept rescheduling.
        assert spy.count >= 2
    finally:
        flusher.cancel()


def test_cancel_stops_further_flushes():
    spy = _Spy()
    flusher = setup_periodic_flush(spy, interval_ms=15)
    time.sleep(0.05)
    flusher.cancel()
    count_at_cancel = spy.count
    time.sleep(0.1)
    # No additional ticks after cancel (allow the in-flight tick to settle).
    assert spy.count <= count_at_cancel + 1


def test_register_atexit_flush_returns_callback_and_swallows_errors():
    spy = _Spy(fail=True)
    cb = register_atexit_flush(spy)
    try:
        # The callback must not raise even though the underlying flush fails.
        cb()
        assert spy.count == 1
    finally:
        atexit.unregister(cb)


def test_register_atexit_flush_delivers_on_clean_shutdown():
    spy = _Spy()
    cb = register_atexit_flush(spy)
    try:
        cb()
        assert spy.count == 1
    finally:
        atexit.unregister(cb)
