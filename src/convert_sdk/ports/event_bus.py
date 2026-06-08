"""EventBus port for the Convert Python SDK (Story 2.4, L1).

Defines the capability the SDK depends on to publish lifecycle events and let
applications subscribe to them, decoupled from any concrete event-delivery
implementation. Keeping it behind a :class:`typing.Protocol` lets the in-process
synchronous adapter (``adapters/events/in_process.py``) be swapped for an
async/queued implementation later without touching the emission call sites
(architecture #Async-Readiness).

Naming follows the architecture's capability-noun rule: ``EventBus`` (no
``I``-prefix), like ``Transport`` and ``DataStore`` (#Naming-Patterns).

Layering: L1. This module imports the L0 ``events.py`` types only; it must NOT
import ``tracking/`` or concrete ``adapters/`` (CI-enforced by import-linter,
Critical Warning #9).
"""

from __future__ import annotations

from typing import Any, Callable, Optional, Protocol, runtime_checkable

from convert_sdk.events import LifecycleEvent

#: A lifecycle-event handler. Invoked as ``handler(payload, error)`` — mirroring
#: the JS ``EventManager`` ``fn(args, err)`` contract — so a handler can observe
#: both the success payload and an optional delivery error.
EventHandler = Callable[..., None]


@runtime_checkable
class EventBus(Protocol):
    """Publishes lifecycle events to registered handlers.

    The bus only notifies handlers; it must NOT become a second orchestration
    layer that duplicates queue/flush/dedup control flow (Critical Warning #10,
    architecture #Service-Boundaries).
    """

    def on(self, event: LifecycleEvent, handler: EventHandler) -> None:
        """Register ``handler`` to be invoked when ``event`` is emitted."""
        ...

    def emit(
        self,
        event: LifecycleEvent,
        payload: Any,
        error: Optional[BaseException] = None,
    ) -> None:
        """Invoke every handler registered for ``event`` with ``(payload, error)``.

        A handler that raises must be isolated, logged, and swallowed so one bad
        handler cannot break delivery or other handlers. Emitting an event with
        no registered handlers is a zero-cost no-op.
        """
        ...
