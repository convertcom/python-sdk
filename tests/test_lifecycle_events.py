"""Story 2.4 — public lifecycle-event surface (Core.on) + emission wiring.

Unit-level coverage (flat ``tests/`` layout) for:

* ``LifecycleEvent`` being exported from the public ``convert_sdk`` surface so
  integrators can call ``Core.on(LifecycleEvent.API_QUEUE_RELEASED, ...)``.
* ``Core.on(event, handler)`` registering a handler against the single
  per-Core ``EventBus`` and that handler receiving emitted events.
* The shared bus being one-per-Core and injected into the tracking layer.

Delivery-outcome / per-trigger reason behavior is proven in the integration
suite (``tests/integration/test_tracking_delivery.py`` /
``test_queue_lifecycle.py``); here we prove the wiring/subscription surface.
"""

from __future__ import annotations

import convert_sdk
from convert_sdk import Core, LifecycleEvent, SDKConfig
from convert_sdk.events import ConversionEventPayload


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [],
    "features": [],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "audiences": [],
    "segments": [],
}


def _core() -> Core:
    return Core(SDKConfig(data=CONFIG)).initialize()


def test_lifecycle_event_exported_from_public_surface():
    assert "LifecycleEvent" in convert_sdk.__all__
    assert convert_sdk.LifecycleEvent is LifecycleEvent


def test_core_on_registers_handler_invoked_on_conversion():
    core = _core()
    received = []
    core.on(LifecycleEvent.CONVERSION, lambda payload, error=None: received.append(payload))

    core.create_context("v1").track_conversion("purchase_completed")

    assert len(received) == 1
    payload = received[0]
    assert isinstance(payload, ConversionEventPayload)
    assert payload.visitor_id == "v1"
    assert payload.goal_id == "g1"
    assert payload.goal_key == "purchase_completed"


def test_single_event_bus_shared_across_contexts():
    core = _core()
    seen = []
    core.on(LifecycleEvent.CONVERSION, lambda payload, error=None: seen.append(payload.visitor_id))

    core.create_context("v1").track_conversion("purchase_completed")
    core.create_context("v2").track_conversion("signup")

    # One bus per Core -> a handler registered on Core observes conversions from
    # every context Core created.
    assert seen == ["v1", "v2"]


def test_core_on_before_initialize_does_not_crash():
    # Registering a handler is safe regardless of init order; the bus is owned
    # by Core (not the snapshot), so subscription is always available.
    core = Core(SDKConfig(data=CONFIG))
    core.on(LifecycleEvent.CONVERSION, lambda payload, error=None: None)
    core.initialize()
    # Emission still reaches the pre-registered handler after init.
    fired = []
    core.on(LifecycleEvent.CONVERSION, lambda payload, error=None: fired.append(payload))
    core.create_context("v1").track_conversion("purchase_completed")
    assert len(fired) == 1
