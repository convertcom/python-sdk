"""Event-delivery adapters for the Convert Python SDK (Story 2.4).

Concrete implementations of the ``ports/event_bus.py`` ``EventBus`` port. The
MVP ships a single in-process synchronous adapter
(:class:`~convert_sdk.adapters.events.in_process.InProcessEventBus`) mirroring
the JS ``EventManager`` ``on``/``fire`` model; an async/queued adapter can be
added later without touching the emission call sites.
"""
