"""Shared in-process queue for tracking delivery."""

from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Sequence

from ..config import TrackingConfig, TransportConfig
from ..domain.results import ConversionEvent, TrackingFlushResult
from ..ports.transport import TrackingRequest, Transport
from .payloads import serialize_tracking_payload


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
    ) -> None:
        self._transport = transport
        self._transport_config = transport_config
        self._tracking_config = tracking_config
        self._sdk_key = sdk_key
        self._sdk_key_secret = sdk_key_secret
        self._account_id = account_id
        self._project_id = project_id
        self._pending: list[ConversionEvent] = []
        self._triggered_goals: set[tuple[str, str]] = set()
        self._lock = Lock()

    @property
    def pending_event_count(self) -> int:
        """Return the number of queued events waiting for explicit release."""

        with self._lock:
            return len(self._pending)

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
            goal_already_tracked = dedupe_key in self._triggered_goals
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
                self._triggered_goals.add(mark_tracked_goal)
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

            while self._pending:
                batch = tuple(self._pending[: self._tracking_config.batch_size])
                payload = serialize_tracking_payload(
                    batch,
                    source=self._tracking_config.source,
                    enrich_data=self._tracking_config.enrich_data,
                )
                self._transport.send_tracking(
                    TrackingRequest(
                        sdk_key=self._sdk_key,
                        sdk_key_secret=self._sdk_key_secret,
                        account_id=self._account_id,
                        project_id=self._project_id,
                        payload=payload,
                        transport=self._transport_config,
                    )
                )
                del self._pending[: len(batch)]
                delivered_batch_count += 1
                delivered_event_count += len(batch)

            return TrackingFlushResult(
                attempted=True,
                delivered_event_count=delivered_event_count,
                delivered_batch_count=delivered_batch_count,
                remaining_event_count=0,
                reason=reason,
            )
