"""Shared in-process queue for tracking delivery."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Sequence

from ..config import TrackingConfig, TransportConfig
from ..diagnostics import log_diagnostic_event
from ..domain.results import ConversionEvent, TrackingFlushResult
from ..errors import TrackingDeliveryError
from ..events import LifecycleEvent, visitor_reference
from ..ports.event_bus import EventBus
from ..ports.storage import DataStore
from ..ports.transport import TrackingRequest, Transport
from .payloads import serialize_tracking_payload


logger = logging.getLogger("convert_sdk.tracking")


@dataclass(frozen=True)
class QueueDecision:
    """Internal deduplication decision for a conversion attempt."""

    should_enqueue_conversion: bool
    should_enqueue_transaction: bool
    duplicate_prevented: bool


class TrackingQueue:
    """Owns pending tracking events for all contexts created from one Core."""

    def __init__(
        self,
        *,
        transport: Transport,
        transport_config: TransportConfig,
        tracking_config: TrackingConfig,
        sdk_key: str | None,
        sdk_key_secret: str | None,
        account_id: str | None,
        project_id: str | None,
        event_bus: EventBus,
        data_store: DataStore,
    ) -> None:
        self._transport = transport
        self._transport_config = transport_config
        self._tracking_config = tracking_config
        self._sdk_key = sdk_key
        self._sdk_key_secret = sdk_key_secret
        self._account_id = account_id
        self._project_id = project_id
        self._event_bus = event_bus
        self._data_store = data_store
        self._pending: list[ConversionEvent] = []
        self._lock = Lock()

    @property
    def pending_event_count(self) -> int:
        """Return the number of queued events waiting for explicit release."""

        with self._lock:
            return len(self._pending)

    def update_snapshot_metadata(
        self,
        *,
        account_id: str | None,
        project_id: str | None,
    ) -> None:
        """Refresh the account/project ids attached to outgoing tracking events.

        Called by ``Core`` when a refreshed ``ConfigSnapshot`` is applied so
        that subsequently delivered events carry the new ids. Mirrors the
        JS SDK's ``ApiManager.setData()`` behaviour. Guarded by ``_lock``
        so a release in flight observes a consistent pair.
        """

        with self._lock:
            self._account_id = account_id
            self._project_id = project_id

    def plan_conversion(
        self,
        *,
        visitor_id: str,
        goal_id: str,
        has_conversion_data: bool,
        allow_repeat_reporting: bool,
    ) -> QueueDecision:
        """Apply deduplication rules and return the queueing decision."""

        dedupe_key = (visitor_id, goal_id)
        with self._lock:
            goal_already_tracked = self._data_store.has_tracked_goal(*dedupe_key)
            if goal_already_tracked:
                if not (allow_repeat_reporting and has_conversion_data):
                    return QueueDecision(
                        should_enqueue_conversion=False,
                        should_enqueue_transaction=False,
                        duplicate_prevented=True,
                    )
                return QueueDecision(
                    should_enqueue_conversion=False,
                    should_enqueue_transaction=True,
                    duplicate_prevented=False,
                )

            return QueueDecision(
                should_enqueue_conversion=True,
                should_enqueue_transaction=has_conversion_data,
                duplicate_prevented=False,
            )

    def enqueue(
        self,
        events: Sequence[ConversionEvent],
        *,
        mark_tracked_goal: tuple[str, str] | None = None,
    ) -> int:
        """Queue conversion events for later explicit delivery."""

        queued_events = tuple(events)
        if not queued_events:
            return 0

        with self._lock:
            self._pending.extend(queued_events)
            if mark_tracked_goal is not None:
                self._data_store.mark_tracked_goal(*mark_tracked_goal)
            pending_event_count = len(self._pending)

        first = queued_events[0]
        self._event_bus.emit(
            LifecycleEvent.TRACKING_EVENT_QUEUED,
            visitor_ref=visitor_reference(first.visitor_id),
            goal_id=first.goal_id,
            goal_key=first.goal_key,
            queued_event_count=len(queued_events),
            pending_event_count=pending_event_count,
            has_conversion_data=any(bool(event.conversion_data) for event in queued_events),
        )
        log_diagnostic_event(
            "tracking.event.queued",
            visitor_id=first.visitor_id,
            goal_key=first.goal_key,
            queued_event_count=len(queued_events),
            pending_event_count=pending_event_count,
            has_conversion_data=any(bool(event.conversion_data) for event in queued_events),
        )
        return len(queued_events)

    def release(self, reason: str | None = None) -> TrackingFlushResult:
        """Send queued events through the configured transport in batches."""

        if reason is not None and not isinstance(reason, str):
            raise TypeError("reason must be a string or None")

        delivered_event_count = 0
        delivered_batch_count = 0
        with self._lock:
            if not self._pending:
                return TrackingFlushResult(
                    attempted=False,
                    delivered_event_count=0,
                    delivered_batch_count=0,
                    remaining_event_count=0,
                    reason=reason,
                )
            pending_event_count = len(self._pending)

        self._event_bus.emit(
            LifecycleEvent.QUEUE_RELEASE_STARTED,
            reason=reason,
            pending_event_count=pending_event_count,
            batch_size=self._tracking_config.batch_size,
        )
        log_diagnostic_event(
            "tracking.queue.release.started",
            reason=reason,
            pending_event_count=pending_event_count,
            batch_size=self._tracking_config.batch_size,
        )

        quarantined_event_count = 0
        while True:
            with self._lock:
                if not self._pending:
                    break
                batch = tuple(self._pending[: self._tracking_config.batch_size])
                # Read account/project ids together with the batch under
                # the same lock so a concurrent update_snapshot_metadata
                # call cannot expose half-updated ids on the request.
                account_id = self._account_id
                project_id = self._project_id

            try:
                payload = serialize_tracking_payload(
                    batch,
                    source=self._tracking_config.source,
                    enrich_data=self._tracking_config.enrich_data,
                )
            except Exception as exc:
                # Poison-pill quarantine: the offending batch is
                # un-serializable (e.g. mismatched account/project ids
                # within the batch). Without this the bad events stay
                # in ``_pending`` and the next ``release()`` hits the
                # same exception forever. Drop the batch with a
                # diagnostic and continue with the rest of the queue.
                with self._lock:
                    del self._pending[: len(batch)]
                quarantined_event_count += len(batch)
                log_diagnostic_event(
                    "tracking.delivery.quarantined",
                    level=logging.WARNING,
                    reason=reason,
                    batch_size=len(batch),
                    error_type=type(exc).__name__,
                    error_code=getattr(exc, "code", None),
                )
                logger.warning(
                    "tracking batch quarantined due to serialization failure",
                    extra={"error_type": type(exc).__name__},
                )
                continue

            try:
                self._transport.send_tracking(
                    TrackingRequest(
                        sdk_key=self._sdk_key,
                        sdk_key_secret=self._sdk_key_secret,
                        account_id=account_id,
                        project_id=project_id,
                        payload=payload,
                        transport=self._transport_config,
                    )
                )
            except Exception as exc:
                with self._lock:
                    remaining_event_count = len(self._pending)
                details = {
                    "reason": reason,
                    "batch_size": len(batch),
                    "delivered_event_count": delivered_event_count,
                    "delivered_batch_count": delivered_batch_count,
                    "remaining_event_count": remaining_event_count,
                    "error_type": type(exc).__name__,
                }
                self._event_bus.emit(
                    LifecycleEvent.TRACKING_DELIVERY_FAILED,
                    **details,
                )
                log_diagnostic_event(
                    "tracking.delivery.failed",
                    level=logging.WARNING,
                    **details,
                )
                logger.warning("tracking delivery failure", extra=details)
                # Wrap in a typed error that carries the partial-
                # success bookkeeping. Callers that catch this can
                # tell how many batches actually went out before the
                # failure; the original exception is reachable via
                # ``__cause__``.
                raise TrackingDeliveryError(
                    f"Tracking delivery failed after {delivered_batch_count} "
                    f"successful batch(es): {type(exc).__name__}",
                    delivered_event_count=delivered_event_count,
                    delivered_batch_count=delivered_batch_count,
                    remaining_event_count=remaining_event_count,
                    context={"reason": reason, "error_type": type(exc).__name__},
                ) from exc

            with self._lock:
                del self._pending[: len(batch)]
                remaining_event_count = len(self._pending)
            delivered_batch_count += 1
            delivered_event_count += len(batch)

        result = TrackingFlushResult(
            attempted=True,
            delivered_event_count=delivered_event_count,
            delivered_batch_count=delivered_batch_count,
            remaining_event_count=remaining_event_count,
            reason=reason,
        )
        self._event_bus.emit(
            LifecycleEvent.QUEUE_RELEASED,
            reason=reason,
            delivered_event_count=result.delivered_event_count,
            delivered_batch_count=result.delivered_batch_count,
            remaining_event_count=result.remaining_event_count,
        )
        log_diagnostic_event(
            "tracking.queue.release.succeeded",
            reason=reason,
            delivered_event_count=result.delivered_event_count,
            delivered_batch_count=result.delivered_batch_count,
            remaining_event_count=result.remaining_event_count,
        )
        return result
