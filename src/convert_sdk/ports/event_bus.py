"""Event-bus protocol for lifecycle notifications."""

from __future__ import annotations

from typing import Callable, Protocol

from ..events import LifecycleEvent, LifecycleEventPayload


EventHandler = Callable[[LifecycleEventPayload], None]


class EventBus(Protocol):
    """Protocol for lifecycle event delivery."""

    def subscribe(self, event: LifecycleEvent, handler: EventHandler) -> None:
        """Subscribe a handler to a lifecycle event."""

    def unsubscribe(self, event: LifecycleEvent, handler: EventHandler) -> None:
        """Remove a lifecycle event handler."""

    def emit(self, event: LifecycleEvent, **details: object) -> None:
        """Emit a lifecycle event with privacy-safe details."""
