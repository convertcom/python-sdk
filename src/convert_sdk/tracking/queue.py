"""Thread-safe in-process tracking queue for the Convert Python SDK (Story 2.3).

The queue batches conversion events per visitor before delivery, mirroring the
JS SDK ``ApiManager`` request queue (``api-manager.ts`` ``enqueue`` /
``releaseQueue``). It is the lightweight, synchronous enqueue side of tracking:

* :meth:`TrackingQueue.enqueue` only appends a typed snake_case
  :class:`~convert_sdk.domain.results.ConversionEvent` (plus the visitor's
  active segments) under a :class:`threading.Lock`. It performs **no network
  I/O and no wire serialization** so it stays under the NFR5 10 ms budget. Wire
  mapping happens later, at flush time, in ``tracking/payloads.py`` (the queue
  holds snake_case domain items only — Critical Warning #8).
* Items are grouped per ``visitor_id`` so one visitor accumulates multiple
  events in a single ``visitors[]`` entry, matching the JS per-visitor queue
  shape.
* Reaching the configured ``batch_size`` signals a size-triggered release;
  :meth:`enqueue` returns ``True`` so the caller funnels the release through the
  ONE shared release path (Critical Warning #4) — the queue itself never calls a
  transport.
* :class:`ReleaseReason` is a typed enum (``size`` / ``explicit`` / ``timeout``
  / ``atexit``) rather than the JS free-form release strings — a deliberate
  Pythonic improvement (F-031).

The queue is thread-safe (``threading.Lock``) so it does not need replacing when
async transport is added later (architecture Async-Readiness guardrail).
"""

from __future__ import annotations

import enum
import threading
from dataclasses import dataclass, field
from typing import Any, List, Mapping, Optional

from convert_sdk.domain.results import ConversionEvent


class ReleaseReason(str, enum.Enum):
    """Why the queue was released (typed; never a free-form string — F-031).

    Mirrors the JS ``releaseQueue(reason)`` call sites with typed values:

    * ``SIZE`` — the queue reached the configured ``batch_size``.
    * ``EXPLICIT`` — a caller invoked ``Core.flush()``.
    * ``TIMEOUT`` — the opt-in periodic ``threading.Timer`` fired.
    * ``ATEXIT`` — the best-effort interpreter-shutdown hook fired.
    """

    SIZE = "size"
    EXPLICIT = "explicit"
    TIMEOUT = "timeout"
    ATEXIT = "atexit"


@dataclass
class VisitorQueueItem:
    """One per-visitor queue entry: ``(visitor_id, events, segments)``.

    Mirrors the JS ``enqueue(visitorId, event, segments)`` item shape. ``events``
    accumulates every conversion event tracked for the visitor in this batch;
    ``segments`` carries the visitor's active segments (latest write wins) for
    the eventual wire ``visitors[].segments``. All values stay snake_case
    domain objects — no wire mapping happens here.
    """

    visitor_id: str
    events: List[ConversionEvent] = field(default_factory=list)
    segments: Optional[Mapping[str, Any]] = None


class TrackingQueue:
    """A thread-safe, per-visitor batching queue of conversion events.

    Args:
        batch_size: The number of enqueued events that triggers a size-based
            release. Mirrors the JS ``DEFAULT_BATCH_SIZE`` (10) when defaulted
            via ``SDKConfig``.
    """

    def __init__(self, batch_size: int = 10) -> None:
        self._batch_size = batch_size
        self._lock = threading.Lock()
        # Insertion-ordered per-visitor grouping (dict preserves order).
        self._items: "dict[str, VisitorQueueItem]" = {}
        self._event_count = 0

    @property
    def length(self) -> int:
        """The total number of queued events across all visitors."""
        with self._lock:
            return self._event_count

    def enqueue(
        self,
        event: ConversionEvent,
        *,
        segments: Optional[Mapping[str, Any]] = None,
    ) -> bool:
        """Append a conversion event for its visitor; lightweight and synchronous.

        Groups the event under its ``visitor_id`` and records the visitor's
        active ``segments`` (latest write wins). Performs no network I/O and no
        wire serialization (NFR5). Returns ``True`` when this enqueue brings the
        total event count to the configured ``batch_size`` — the signal that the
        caller should release the queue via the shared release path with
        :attr:`ReleaseReason.SIZE`. Returns ``False`` otherwise.
        """
        with self._lock:
            item = self._items.get(event.visitor_id)
            if item is None:
                item = VisitorQueueItem(visitor_id=event.visitor_id)
                self._items[event.visitor_id] = item
            item.events.append(event)
            if segments is not None:
                item.segments = segments
            self._event_count += 1
            return self._event_count >= self._batch_size

    def items(self) -> List[VisitorQueueItem]:
        """A snapshot list of the current per-visitor items (does not drain)."""
        with self._lock:
            return list(self._items.values())

    def drain(self) -> List[VisitorQueueItem]:
        """Atomically remove and return all queued per-visitor items.

        Used by the single shared release path: the caller drains, serializes,
        and delivers. On a successful delivery the queue is already empty; on a
        failed delivery the caller re-enqueues or restores the drained items
        (this story leaves the queue intact by draining only inside the release
        path that owns delivery — see the tracker).
        """
        with self._lock:
            drained = list(self._items.values())
            self._items = {}
            self._event_count = 0
            return drained

    def restore(self, items: List[VisitorQueueItem]) -> None:
        """Put drained items back (used when delivery fails, to avoid loss).

        Merges restored items ahead of any events enqueued since the drain so
        ordering stays stable per visitor.
        """
        if not items:
            return
        with self._lock:
            merged: "dict[str, VisitorQueueItem]" = {}
            for item in items:
                merged[item.visitor_id] = item
            # Append any events enqueued after the drain.
            for visitor_id, current in self._items.items():
                if visitor_id in merged:
                    merged[visitor_id].events.extend(current.events)
                    if current.segments is not None:
                        merged[visitor_id].segments = current.segments
                else:
                    merged[visitor_id] = current
            self._items = merged
            self._event_count = sum(len(i.events) for i in merged.values())
