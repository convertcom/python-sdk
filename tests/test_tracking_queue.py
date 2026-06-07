"""Story 2.3 — tracking queue unit tests (BE-1).

Proves the thread-safe in-process tracking queue (``tracking/queue.py``):

* Lightweight, synchronous enqueue (no network I/O, no wire serialization) —
  the queue holds snake_case domain items only (NFR5).
* Per-visitor grouping that mirrors the JS ``enqueue(visitorId, event,
  segments)`` item shape (``api-manager.ts``).
* Batch-size-triggered release through the single shared release path.
* Thread-safe concurrent enqueue (``threading.Lock``).
* The typed ``ReleaseReason`` enum (``size``/``explicit``/``timeout``/
  ``atexit``) — a Pythonic improvement over the JS free-form release strings
  (F-031).
"""

import threading

import pytest

from convert_sdk.domain.results import ConversionEvent
from convert_sdk.tracking.queue import ReleaseReason, TrackingQueue


def _event(visitor_id="v1", goal_id="g1", goal_key="purchase"):
    return ConversionEvent(visitor_id=visitor_id, goal_id=goal_id, goal_key=goal_key)


# --- ReleaseReason enum ---------------------------------------------------


def test_release_reason_enum_values():
    assert ReleaseReason.SIZE.value == "size"
    assert ReleaseReason.EXPLICIT.value == "explicit"
    assert ReleaseReason.TIMEOUT.value == "timeout"
    assert ReleaseReason.ATEXIT.value == "atexit"


# --- enqueue & grouping ---------------------------------------------------


def test_enqueue_increments_length():
    q = TrackingQueue(batch_size=10)
    assert q.length == 0
    q.enqueue(_event())
    assert q.length == 1


def test_enqueue_groups_by_visitor():
    q = TrackingQueue(batch_size=100)
    q.enqueue(_event(visitor_id="a", goal_id="g1"))
    q.enqueue(_event(visitor_id="a", goal_id="g2"))
    q.enqueue(_event(visitor_id="b", goal_id="g3"))
    items = q.items()
    by_visitor = {item.visitor_id: item for item in items}
    assert set(by_visitor) == {"a", "b"}
    assert len(by_visitor["a"].events) == 2
    assert len(by_visitor["b"].events) == 1


def test_enqueue_carries_segments_on_item():
    q = TrackingQueue(batch_size=100)
    q.enqueue(_event(visitor_id="a"), segments={"country": "US"})
    item = q.items()[0]
    assert item.segments == {"country": "US"}


def test_enqueue_does_no_network_io():
    # The queue must not hold or call any transport — enqueue is purely local.
    q = TrackingQueue(batch_size=100)
    q.enqueue(_event())
    # No transport attribute exists on the queue at all.
    assert not hasattr(q, "_transport")
    assert not hasattr(q, "transport")


# --- batch-size release ---------------------------------------------------


def test_reaching_batch_size_marks_ready_for_release():
    q = TrackingQueue(batch_size=3)
    assert q.enqueue(_event(goal_id="g1")) is False
    assert q.enqueue(_event(goal_id="g2")) is False
    # Third enqueue reaches batch_size -> signals a size-triggered release.
    assert q.enqueue(_event(goal_id="g3")) is True


def test_drain_returns_items_and_empties_queue():
    q = TrackingQueue(batch_size=10)
    q.enqueue(_event(goal_id="g1"))
    q.enqueue(_event(goal_id="g2"))
    drained = q.drain()
    assert len(drained) >= 1
    assert q.length == 0


def test_drain_empty_queue_returns_empty():
    q = TrackingQueue(batch_size=10)
    assert q.drain() == []
    assert q.length == 0


# --- thread safety --------------------------------------------------------


def test_concurrent_enqueue_is_thread_safe():
    q = TrackingQueue(batch_size=100000)
    n_threads = 8
    per_thread = 200

    def worker(tid):
        for i in range(per_thread):
            q.enqueue(_event(visitor_id=f"v{tid}", goal_id=f"g{i}"))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No lost updates: total event count equals every enqueue.
    total_events = sum(len(item.events) for item in q.items())
    assert total_events == n_threads * per_thread
    # One grouped item per distinct visitor.
    assert len(q.items()) == n_threads
