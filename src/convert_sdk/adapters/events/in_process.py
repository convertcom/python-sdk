"""In-process synchronous EventBus adapter for the Convert Python SDK (Story 2.4, L3).

Implements the ``ports/event_bus.py`` ``EventBus`` port with a per-event handler
registry, mirroring the JS ``EventManager`` ``on``/``fire`` model
(``javascript-sdk/packages/event/src/event-manager.ts``):

* :meth:`on` pushes a handler onto the per-event listener list.
* :meth:`emit` calls every listener as ``handler(payload, error)`` inside a
  per-listener ``try/except`` that logs (privacy-safe) and **swallows** any
  handler exception — one bad integrator handler can never break delivery or the
  other handlers (AC #2, Critical Warning #6; direct parity with the JS
  ``fire()`` per-listener try/catch).
* Emitting an event with no registered handlers is a **zero-cost no-op**: an
  empty (or absent) handler list returns immediately with no I/O and no
  measurable overhead, preserving the NFR5 enqueue budget when no subscriber
  exists (AC #5, Task 2.4).

Design note (Task 2.5): ``CONVERSION`` and ``API_QUEUE_RELEASED`` are emitted
**live** (non-deferred) — they reflect real, repeated state transitions, so a
handler only receives events fired after it subscribes. Deferred one-shot firing
(JS parity for ``READY``) is intentionally NOT implemented here: Story 2.4 does
not emit any one-shot event (READY/CONFIG_UPDATED emission belongs to the
init/config layer — Critical Warning #12), so deferred firing would add cost
without exercising any current call site.

Layering: L3 (concrete adapter). It imports the L0 ``events.py`` types, the L1
``ports/event_bus.py`` protocol, and the SDK ``logging`` helper only — never
``tracking/`` (Critical Warning #9).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from convert_sdk.events import LifecycleEvent
from convert_sdk.logging import log_event_handler_error
from convert_sdk.ports.event_bus import EventHandler


class InProcessEventBus:
    """A synchronous, in-process implementation of the ``EventBus`` port.

    Handler registration and invocation are synchronous and ordered (handlers
    fire in registration order). The bus is intentionally minimal: it notifies
    handlers and does nothing else — it is NOT a second orchestration layer
    (Critical Warning #10).
    """

    def __init__(self) -> None:
        # event -> ordered list of handlers (created lazily on first subscribe).
        self._handlers: Dict[LifecycleEvent, List[EventHandler]] = {}

    def on(self, event: LifecycleEvent, handler: EventHandler) -> None:
        """Register ``handler`` for ``event`` (appended in subscription order)."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(
        self,
        event: LifecycleEvent,
        payload: Any,
        error: Optional[BaseException] = None,
    ) -> None:
        """Invoke every handler for ``event`` with ``(payload, error)``.

        No-subscriber emit is a zero-cost no-op. Each handler runs inside a
        ``try/except`` so a raising handler is logged (privacy-safe — only the
        event name + traceback, never the payload) and swallowed; subsequent
        handlers still run and the emission never propagates an exception.
        """
        handlers = self._handlers.get(event)
        if not handlers:
            # Zero-cost no-op: no subscribers -> no work, no I/O (NFR5).
            return
        # Iterate a snapshot so a handler that subscribes during emission does
        # not change the in-flight iteration.
        for handler in tuple(handlers):
            try:
                handler(payload, error)
            except Exception:
                # Parity with JS EventManager.fire per-listener try/catch:
                # isolate, log privacy-safely, swallow. One bad handler must not
                # break delivery or the other handlers.
                log_event_handler_error(event=event.value)
