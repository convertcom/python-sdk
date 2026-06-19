"""Tracking orchestration seam for the Convert Python SDK (Story 2.3).

:class:`Tracker` is the single orchestration point between
:class:`~convert_sdk.context.Context`, the goal-deduplication service, the
in-process :class:`~convert_sdk.tracking.queue.TrackingQueue`, and the
transport boundary. It keeps ``Context`` thin: the public surface delegates the
"dedup → enqueue → maybe release" decision and the explicit flush/delivery to
this module, so ``evaluation/`` and ``tracking/`` stay decoupled (architecture
Component-Boundaries).

Flow:

1. :meth:`track` builds the in-process event via the Story 2.1/2.2
   ``create_conversion`` service (goal resolution + revenue/conversion_data +
   attribution). An unknown goal returns the typed ``GOAL_NOT_FOUND`` result
   unchanged and never enqueues.
2. Deduplication is evaluated through the ``DataStore`` boundary
   (:func:`~convert_sdk.tracking.deduplication.evaluate_dedup`). A default-mode
   duplicate is suppressed and returns ``ConversionResult(status=DEDUPLICATED)``
   (``tracked=False, reason="deduplicated"``). The "goal tracked" marker is
   persisted unconditionally for every non-suppressed call (F-007).
3. On a non-suppressed call the event is enqueued. Reaching ``batch_size``
   triggers a size-based release through the ONE shared release path
   (:meth:`_release`) — the same path explicit :meth:`flush` uses (Critical
   Warning #4). There are no separate manual-vs-auto release implementations.
4. :meth:`flush` drains the queue, serializes each per-visitor batch through the
   Story 2.2 ``tracking/payloads.py`` builder (NO second serializer — Critical
   Warning #3), and delivers via the ``Transport`` port. An empty-queue flush is
   a safe no-op. A failed delivery restores the drained items so events are not
   silently lost; this story adds NO retry/backoff (transport-layer concern).

Out of scope here (Story 2.4): lifecycle-event emission and delivery-outcome
reporting. Layering: this module talks to transport/storage ONLY through
``ports/`` — never a concrete adapter (Critical Warning #9).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Mapping, Optional

from convert_sdk.domain.results import (
    BucketingEvent,
    ConversionEvent,
    ConversionResult,
    ConversionStatus,
)
from convert_sdk.errors import TrackingDeliveryError
from convert_sdk.events import (
    BucketingEventPayload,
    ConversionEventPayload,
    LifecycleEvent,
    QueueReleasedPayload,
)
from convert_sdk.logging import (
    log_queue_release_success,
    log_tracking_delivery_failure,
)
from convert_sdk.ports.storage import DataStore
from convert_sdk.tracking.conversions import create_conversion
from convert_sdk.tracking.deduplication import evaluate_bucketing_dedup, evaluate_dedup
from convert_sdk.tracking.payloads import (
    build_bucketing_payload,
    build_tracking_payload,
    event_has_goal_data,
)
from convert_sdk.tracking.queue import ReleaseReason, TrackingQueue, VisitorQueueItem

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.config import SDKConfig
    from convert_sdk.domain.config_snapshot import ConfigSnapshot
    from convert_sdk.ports.event_bus import EventBus
    from convert_sdk.ports.transport import Transport


class Tracker:
    """Owns the shared queue + dedup state + flush/delivery for one SDK config.

    A single :class:`Tracker` is created per :class:`~convert_sdk.core.Core` and
    shared by every :class:`~convert_sdk.context.Context` that Core creates, so
    deduplication and batching are consistent across contexts within a process.

    Args:
        snapshot: The immutable config snapshot (supplies account/project ids
            and goal resolution).
        config: The :class:`~convert_sdk.config.SDKConfig` (supplies
            ``batch_size`` and ``sdk_key``).
        data_store: The single per-:class:`~convert_sdk.core.Core`
            :class:`~convert_sdk.ports.storage.DataStore`, injected by the
            composition root. The tracker depends on the protocol only — it
            never constructs or imports the concrete adapter (layering: L2 must
            not import ``adapters/``). Story 3.1 moved dedup state behind this
            injected boundary.
        transport: The transport used for delivery. May be ``None`` until a
            flush actually needs to deliver (an empty-queue flush never touches
            it). When delivery is required and no transport is available, the
            caller is responsible for providing one (Core wires it lazily).
        transport_provider: Optional zero-arg callable returning a
            :class:`~convert_sdk.ports.transport.Transport`, used to obtain a
            transport lazily on first delivery (keeps httpx off the
            direct-config import path).
    """

    def __init__(
        self,
        *,
        snapshot: "ConfigSnapshot",
        config: "SDKConfig",
        data_store: "DataStore",
        transport: Optional["Transport"] = None,
        transport_provider: Optional[Any] = None,
        event_bus: Optional["EventBus"] = None,
    ) -> None:
        self._snapshot = snapshot
        self._config = config
        self._transport = transport
        self._transport_provider = transport_provider
        self._queue = TrackingQueue(batch_size=config.batch_size)
        # Story 3.1: the per-Core DataStore is INJECTED by the composition root.
        # The tracker depends only on the protocol — it never constructs or
        # imports the concrete InMemoryDataStore (that is core.py's job, L4).
        self._store: DataStore = data_store
        # Story 2.4: the single per-Core EventBus, injected by Core. May be None
        # for a Tracker constructed without one (e.g. a direct test) — emission
        # is then a guarded no-op so the tracking flow is unaffected.
        self._event_bus = event_bus
        # Seed the queue's identity metadata from the initial snapshot so a later
        # refresh re-point (Story 5.2) is a delta from a known baseline.
        self._queue.update_snapshot_metadata(
            account_id=snapshot.account_id, project_id=snapshot.project_id
        )

    # --- config refresh (Story 5.2) ----------------------------------------

    def update_snapshot(self, snapshot: "ConfigSnapshot") -> None:
        """Re-point the tracker (and its queue) at a refreshed snapshot.

        Called by ``Core`` on each successful background refresh swap. The
        serializer builds the wire envelope's ``accountId`` / ``projectId`` from
        this snapshot, so re-pointing it attributes conversions queued after the
        refresh to the new project (JS parity: ``ApiManager.setData()``). The
        queue's recorded identity metadata is updated in lock-step.
        """
        self._snapshot = snapshot
        self._queue.update_snapshot_metadata(
            account_id=snapshot.account_id, project_id=snapshot.project_id
        )

    # --- track -------------------------------------------------------------

    def track(
        self,
        *,
        visitor_id: str,
        goal_key: str,
        revenue: Optional[float] = None,
        conversion_data: Optional[Mapping[str, Any]] = None,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        default_segments: Optional[Mapping[str, Any]] = None,
        force_multiple: bool = False,
    ) -> ConversionResult:
        """Resolve, dedup, and (conditionally) enqueue a conversion.

        Returns the typed :class:`ConversionResult`: ``QUEUED`` on enqueue,
        ``DEDUPLICATED`` on a default-mode duplicate, or ``GOAL_NOT_FOUND`` for
        an unknown goal (preserved unchanged from Story 2.1). Programmer misuse
        in ``conversion_data`` still fails fast via ``create_conversion``.

        ``default_segments`` (Story 3.3 / FR14) are the visitor's active default
        segments at conversion time; they are passed through to the serializer's
        ``segments`` payload without changing dedup/queue/flush behavior.
        """
        result = create_conversion(
            self._snapshot,
            visitor_id=visitor_id,
            goal_key=goal_key,
            revenue=revenue,
            conversion_data=conversion_data,
            visitor_attributes=visitor_attributes,
            default_segments=default_segments,
        )
        # Unknown goal: typed NON-EXCEPTION outcome, never enqueued (FR50).
        if result.status is not ConversionStatus.QUEUED or result.event is None:
            return result

        event = result.event
        # goalData presence drives the transaction-send branch (F-006). It is
        # computed via the Story 2.2 serializer predicate so "has goalData"
        # matches exactly what would be serialized on the wire (revenue or
        # allowlisted conversion_data keys).
        has_goal_data = event_has_goal_data(event)

        decision = evaluate_dedup(
            self._store,
            visitor_id=visitor_id,
            goal_id=event.goal_id,
            force_multiple=force_multiple,
            has_goal_data=has_goal_data,
        )

        if decision.suppressed:
            return ConversionResult(
                status=ConversionStatus.DEDUPLICATED,
                goal_key=result.goal_key,
                goal_id=result.goal_id,
                visitor_id=visitor_id,
                event=None,
            )

        # F-006: enqueue the event when there is something to send — the bare
        # conversion the first time (should_send_conversion) and/or the
        # transaction (should_send_transaction). The single serialized event
        # carries goalId + (optionally) goalData, so one enqueue covers both the
        # conversion and transaction wire concerns for this call. If neither
        # send applies (forced repeat with no goalData) there is nothing to
        # deliver, but the call is still "tracked" (not suppressed).
        if decision.should_send_conversion or decision.should_send_transaction:
            reached_batch = self._queue.enqueue(
                event, segments=event.segments
            )
            # Story 2.4: emit CONVERSION only after a tracked (non-suppressed)
            # enqueue (AC #1/#4). A deduplicated suppression returned earlier and
            # a goal-not-found returned even earlier, so neither reaches here —
            # events reflect real state transitions, not no-ops. The payload is
            # built from internal snake_case domain fields only (no wire
            # serialization, Task 4.3) and emission is a no-op when no handler is
            # registered (NFR5), so it never blocks the enqueue path.
            self._emit_conversion(event)
            if reached_batch:
                self._release(ReleaseReason.SIZE)

        return result

    def _emit_conversion(self, event: ConversionEvent) -> None:
        """Emit ``LifecycleEvent.CONVERSION`` for a tracked enqueue (Story 2.4)."""
        if self._event_bus is None:
            return
        self._event_bus.emit(
            LifecycleEvent.CONVERSION,
            ConversionEventPayload(
                visitor_id=event.visitor_id,
                goal_id=event.goal_id,
                goal_key=event.goal_key,
            ),
        )

    # --- bucketing activation tracking (Story 2.5) -------------------------

    def track_bucketing(
        self,
        *,
        visitor_id: str,
        experience_id: str,
        variation_id: str,
        segments: Optional[Mapping[str, Any]] = None,
    ) -> None:
        """Dedup, enqueue, and emit a bucketing activation event (Story 2.5).

        Called after a visitor is successfully bucketed into an experience variation
        (from :meth:`~convert_sdk.context.Context.run_experience` /
        :meth:`~convert_sdk.context.Context.run_experiences` when
        ``enable_tracking=True``).

        Flow:
        1. Evaluate bucketing deduplication via the DataStore boundary: if the
           ``(visitor_id, experience_id)`` pair was already tracked, return immediately
           (no enqueue, no emit — AC#3).
        2. Build a :class:`~convert_sdk.domain.results.BucketingEvent` and enqueue it.
           If the batch size is reached, release via the shared release path.
        3. Emit ``LifecycleEvent.BUCKETING`` with a
           :class:`~convert_sdk.events.BucketingEventPayload` (AC#5). Handler
           exceptions are swallowed by the
           :class:`~convert_sdk.adapters.events.in_process.InProcessEventBus`
           — no guard needed here.
        """
        should_enqueue = evaluate_bucketing_dedup(
            self._store, visitor_id=visitor_id, experience_id=experience_id
        )
        if not should_enqueue:
            return

        event = BucketingEvent(
            visitor_id=visitor_id,
            experience_id=experience_id,
            variation_id=variation_id,
        )
        reached_batch = self._queue.enqueue(event, segments=segments)
        self._emit_bucketing(event)
        if reached_batch:
            self._release(ReleaseReason.SIZE)

    def _emit_bucketing(self, event: BucketingEvent) -> None:
        """Emit ``LifecycleEvent.BUCKETING`` for a bucketed enqueue (Story 2.5).

        Mirrors :meth:`_emit_conversion`: guarded no-op when no event bus is wired.
        The bus swallows handler exceptions so the tracking flow is never broken by a
        bad subscriber.
        """
        if self._event_bus is None:
            return
        self._event_bus.emit(
            LifecycleEvent.BUCKETING,
            BucketingEventPayload(
                visitor_id=event.visitor_id,
                experience_id=event.experience_id,
                variation_id=event.variation_id,
            ),
        )

    # --- flush / release ---------------------------------------------------

    def flush(self) -> None:
        """Explicitly release the queue (``ReleaseReason.EXPLICIT``).

        Drains, serializes via the Story 2.2 builder, and delivers through the
        transport, clearing the queue on success. An empty queue is a safe
        no-op (no transport call, no error).
        """
        self._release(ReleaseReason.EXPLICIT)

    def flush_timeout(self) -> None:
        """Release the queue from the periodic timer (``ReleaseReason.TIMEOUT``).

        Routes through the SAME single shared release path as :meth:`flush`
        (Critical Warning #2/#4) — only the reported ``reason`` differs so the
        ``API_QUEUE_RELEASED`` event carries the correct per-trigger reason
        (Story 2.4, qs-07).
        """
        self._release(ReleaseReason.TIMEOUT)

    def flush_atexit(self) -> None:
        """Release the queue from the atexit hook (``ReleaseReason.ATEXIT``).

        Routes through the SAME single shared release path as :meth:`flush`;
        only the reported ``reason`` differs (Story 2.4, qs-07).
        """
        self._release(ReleaseReason.ATEXIT)

    def _release(self, reason: ReleaseReason) -> None:
        """The ONE shared release path used by size/explicit/timeout/atexit.

        Drains the queue, builds one tracking payload per drained per-visitor
        item via the Story 2.2 serializer, and POSTs through the transport.

        Story 2.4 emits ``LifecycleEvent.API_QUEUE_RELEASED`` exactly once per
        ACTUAL release (an empty-queue release fires nothing — Critical Warning
        #5) and reports the delivery outcome:

        * **Success** — emit a :class:`QueueReleasedPayload` carrying ``reason``,
          ``batch_size``, and visitor/event counts (parity with the JS
          ``releaseQueue`` success branch) and log a privacy-safe success line.
        * **Failure** (``TrackingDeliveryError`` raised by the transport adapter
          after exhausting its own retries) — emit the same payload PLUS the
          delivery error (privacy-safe context only: ``status_code`` +
          ``retry_attempts``), log a privacy-safe failure line, **drop** the
          drained events (NOT re-queued — intentional Python divergence from the
          JS catch branch, F-010 / architecture #Retry-and-Backoff-Formula), and
          **return without raising** so ``flush()`` stays non-raising (Critical
          Warning #3). Retries live entirely in the transport adapter — this path
          only observes and reports the outcome (Task 5.5).

        A non-delivery error (e.g. a serialization bug) is NOT swallowed: the
        drained events are restored and the error propagates, so genuine
        programmer faults surface.
        """
        items = self._queue.drain()
        if not items:
            # Empty-queue release is a safe no-op (JS releaseQueue early-return);
            # no API_QUEUE_RELEASED is emitted because no release occurred.
            return

        visitor_count = len(items)
        event_count = sum(len(item.events) for item in items)
        payload = self._build_batch_payload(items)
        transport = self._ensure_transport()
        try:
            status_code = transport.send_tracking(payload, sdk_key=str(self._config.sdk_key))
        except TrackingDeliveryError as error:
            # Delivery failed after the transport adapter exhausted its retries.
            # Surface the outcome via the lifecycle event + privacy-safe log,
            # then DROP the events (do not re-queue) and return without raising.
            # Use a distinct name to avoid shadowing the success-path ``status_code``
            # binding (mypy --strict flags a ``int`` ← ``Any | None`` assignment).
            err_status_code: Optional[int] = getattr(error, "status_code", None)
            retry_attempts = getattr(error, "retry_attempts", None)
            log_tracking_delivery_failure(
                reason=reason.value,
                batch_size=event_count,
                status_code=err_status_code,
                retry_attempts=retry_attempts,
            )
            self._emit_queue_released(
                reason=reason,
                event_count=event_count,
                visitor_count=visitor_count,
                status_code=err_status_code,
                retry_attempts=retry_attempts,
                error=error,
            )
            return
        except Exception:
            # A non-delivery fault (e.g. serialization bug): restore the drained
            # events and propagate — this is NOT a delivery outcome to swallow.
            self._queue.restore(items)
            raise

        # Delivery succeeded: report the success outcome (status_code is the
        # 2xx returned by send_tracking — never None on the success path).
        log_queue_release_success(reason=reason.value, batch_size=event_count)
        self._emit_queue_released(
            reason=reason,
            event_count=event_count,
            visitor_count=visitor_count,
            status_code=status_code,
        )

    def _emit_queue_released(
        self,
        *,
        reason: ReleaseReason,
        event_count: int,
        visitor_count: int,
        status_code: Optional[int] = None,
        retry_attempts: Optional[int] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        """Emit ``LifecycleEvent.API_QUEUE_RELEASED`` (Story 2.4).

        ``batch_size`` is the number of events delivered in this release. On
        failure the payload additionally carries privacy-safe error context
        (``status_code`` + ``retry_attempts`` only — never the SDK key, auth
        headers, raw transport bodies, or raw visitor attributes; NFR23/NFR7).
        """
        if self._event_bus is None:
            return
        self._event_bus.emit(
            LifecycleEvent.API_QUEUE_RELEASED,
            QueueReleasedPayload(
                reason=reason,
                batch_size=event_count,
                visitor_count=visitor_count,
                event_count=event_count,
                status_code=status_code,
                retry_attempts=retry_attempts,
            ),
            error=error,
        )

    def _build_batch_payload(self, items: List[VisitorQueueItem]) -> dict[str, Any]:
        """Serialize all drained per-visitor items into ONE batch envelope.

        Dispatches per event type — :class:`~convert_sdk.domain.results.ConversionEvent`
        uses :func:`~convert_sdk.tracking.payloads.build_tracking_payload`; a
        :class:`~convert_sdk.domain.results.BucketingEvent` uses
        :func:`~convert_sdk.tracking.payloads.build_bucketing_payload`. Then merges
        events belonging to the same visitor into a single ``visitors[]`` entry so the
        batch matches the JS ``VisitorsQueue`` grouping (``api-manager.ts``): one entry
        per visitor carrying all of that visitor's events. A bucketing + conversion event
        for the same visitor land in the same ``events`` array (AC#1). The stable
        envelope fields (``accountId`` / ``projectId`` / ``source`` / ``enrichData``)
        come from the first serialized event so they are computed exactly once.
        """
        # visitor_id -> merged visitors[] entry (preserving insertion order).
        merged: "dict[str, dict[str, Any]]" = {}
        envelope: Optional[dict[str, Any]] = None
        for item in items:
            for event in item.events:
                if isinstance(event, BucketingEvent):
                    single = build_bucketing_payload(
                        self._snapshot, event, data_store=self._config.data_store
                    )
                else:
                    single = build_tracking_payload(
                        self._snapshot, event, data_store=self._config.data_store
                    )
                if envelope is None:
                    envelope = single
                for visitor in single["visitors"]:
                    vid = visitor["visitorId"]
                    existing = merged.get(vid)
                    if existing is None:
                        merged[vid] = visitor
                    else:
                        existing["events"].extend(visitor["events"])
                        # Latest non-empty segments win (matches queue grouping).
                        if visitor.get("segments"):
                            existing["segments"] = visitor["segments"]
        assert envelope is not None  # items is non-empty (checked by caller)
        envelope["visitors"] = list(merged.values())
        return envelope

    def _ensure_transport(self) -> "Transport":
        if self._transport is None:
            if self._transport_provider is not None:
                self._transport = self._transport_provider()
            else:  # pragma: no cover - defensive; Core always wires a provider
                raise RuntimeError(
                    "Tracker has no transport configured for delivery; "
                    "configure an sdk_key or pass a transport."
                )
        return self._transport
