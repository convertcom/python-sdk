"""Lifecycle event types for SDK observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any, Mapping


class LifecycleEvent(str, Enum):
    """Known SDK lifecycle event names."""

    CONVERSION_CREATED = "conversion_created"
    CONVERSION_DEDUPLICATED = "conversion_deduplicated"
    TRACKING_EVENT_QUEUED = "tracking_event_queued"
    QUEUE_RELEASE_STARTED = "queue_release_started"
    QUEUE_RELEASED = "queue_released"
    TRACKING_DELIVERY_FAILED = "tracking_delivery_failed"


def visitor_reference(visitor_id: str) -> str:
    """Return a stable non-reversible visitor reference for diagnostics."""

    return sha256(visitor_id.encode("utf-8")).hexdigest()[:16]


def freeze_event_details(details: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """Freeze lifecycle details into an immutable mapping."""

    if not details:
        return MappingProxyType({})
    return MappingProxyType({str(key): value for key, value in details.items()})


@dataclass(frozen=True)
class LifecycleEventPayload:
    """Payload delivered to SDK lifecycle event handlers."""

    event: LifecycleEvent
    details: Mapping[str, Any] = field(default_factory=lambda: MappingProxyType({}))
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self) -> None:
        object.__setattr__(self, "details", freeze_event_details(self.details))
