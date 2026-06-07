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
    ConversionResult,
    ConversionStatus,
)
from convert_sdk.ports.storage import DataStore, resolve_data_store
from convert_sdk.tracking.conversions import create_conversion
from convert_sdk.tracking.deduplication import evaluate_dedup
from convert_sdk.tracking.payloads import _build_goal_data, build_tracking_payload
from convert_sdk.tracking.queue import ReleaseReason, TrackingQueue, VisitorQueueItem

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.config import SDKConfig
    from convert_sdk.domain.config_snapshot import ConfigSnapshot
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
            ``batch_size``, ``sdk_key``, and the optional shared ``data_store``).
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
        transport: Optional["Transport"] = None,
        transport_provider: Optional[Any] = None,
    ) -> None:
        self._snapshot = snapshot
        self._config = config
        self._transport = transport
        self._transport_provider = transport_provider
        self._queue = TrackingQueue(batch_size=config.batch_size)
        self._store: DataStore = resolve_data_store(config.data_store)

    # --- track -------------------------------------------------------------

    def track(
        self,
        *,
        visitor_id: str,
        goal_key: str,
        revenue: Optional[float] = None,
        conversion_data: Optional[Mapping[str, Any]] = None,
        visitor_attributes: Optional[Mapping[str, Any]] = None,
        force_multiple: bool = False,
    ) -> ConversionResult:
        """Resolve, dedup, and (conditionally) enqueue a conversion.

        Returns the typed :class:`ConversionResult`: ``QUEUED`` on enqueue,
        ``DEDUPLICATED`` on a default-mode duplicate, or ``GOAL_NOT_FOUND`` for
        an unknown goal (preserved unchanged from Story 2.1). Programmer misuse
        in ``conversion_data`` still fails fast via ``create_conversion``.
        """
        result = create_conversion(
            self._snapshot,
            visitor_id=visitor_id,
            goal_key=goal_key,
            revenue=revenue,
            conversion_data=conversion_data,
            visitor_attributes=visitor_attributes,
        )
        # Unknown goal: typed NON-EXCEPTION outcome, never enqueued (FR50).
        if result.status is not ConversionStatus.QUEUED or result.event is None:
            return result

        event = result.event
        # goalData presence drives the transaction-send branch (F-006). It is
        # computed via the Story 2.2 serializer helper so "has goalData" matches
        # exactly what would be serialized on the wire (revenue or allowlisted
        # conversion_data keys).
        has_goal_data = bool(_build_goal_data(event))

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
            if reached_batch:
                self._release(ReleaseReason.SIZE)

        return result

    # --- flush / release ---------------------------------------------------

    def flush(self) -> None:
        """Explicitly release the queue (``ReleaseReason.EXPLICIT``).

        Drains, serializes via the Story 2.2 builder, and delivers through the
        transport, clearing the queue on success. An empty queue is a safe
        no-op (no transport call, no error).
        """
        self._release(ReleaseReason.EXPLICIT)

    def _release(self, reason: ReleaseReason) -> None:
        """The ONE shared release path used by size/explicit/timeout/atexit.

        Drains the queue, builds one tracking payload per drained per-visitor
        item via the Story 2.2 serializer, and POSTs through the transport. On a
        delivery failure the drained items are restored so events are not lost
        (no retry here — that is a transport-layer concern).
        """
        items = self._queue.drain()
        if not items:
            # Empty-queue release is a safe no-op (JS releaseQueue early-return).
            return

        payload = self._build_batch_payload(items)
        transport = self._ensure_transport()
        try:
            transport.send_tracking(payload, sdk_key=str(self._config.sdk_key))
        except Exception:
            # Preserve the drained events for a later flush; surface the error.
            self._queue.restore(items)
            raise

    def _build_batch_payload(self, items: List[VisitorQueueItem]) -> dict:
        """Serialize all drained per-visitor items into ONE batch envelope.

        Reuses the Story 2.2 ``build_tracking_payload`` serializer (single
        serialization path, NFR21 parity) for each event, then merges the
        per-visitor ``visitors[]`` entries into a single envelope so the whole
        batch is delivered in one POST (JS releaseQueue batch shape).
        """
        visitors: List[dict] = []
        for item in items:
            for event in item.events:
                single = build_tracking_payload(
                    self._snapshot, event, data_store=self._config.data_store
                )
                visitors.extend(single["visitors"])
        # Take the stable envelope fields from the serializer's first build.
        first = build_tracking_payload(
            self._snapshot, items[0].events[0], data_store=self._config.data_store
        )
        first["visitors"] = visitors
        return first

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
