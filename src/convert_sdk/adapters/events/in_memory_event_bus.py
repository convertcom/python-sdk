"""In-memory lifecycle event bus."""

from __future__ import annotations

import logging
from collections import defaultdict
from threading import RLock

from ...events import LifecycleEvent, LifecycleEventPayload
from ...ports.event_bus import EventHandler


logger = logging.getLogger("convert_sdk.events")


class InMemoryEventBus:
    """Small synchronous event bus for SDK lifecycle hooks."""

    def __init__(self) -> None:
        self._handlers: dict[LifecycleEvent, list[EventHandler]] = defaultdict(list)
        self._lock = RLock()

    def subscribe(self, event: LifecycleEvent, handler: EventHandler) -> None:
        if not callable(handler):
            raise TypeError("handler must be callable")
        with self._lock:
            if handler not in self._handlers[event]:
                self._handlers[event].append(handler)

    def unsubscribe(self, event: LifecycleEvent, handler: EventHandler) -> None:
        with self._lock:
            handlers = self._handlers.get(event)
            if not handlers or handler not in handlers:
                return
            handlers.remove(handler)

    def emit(self, event: LifecycleEvent, **details: object) -> None:
        payload = LifecycleEventPayload(event=event, details=details)
        with self._lock:
            handlers = tuple(self._handlers.get(event, ()))

        for handler in handlers:
            try:
                handler(payload)
            except Exception:
                logger.exception("lifecycle handler failed")
