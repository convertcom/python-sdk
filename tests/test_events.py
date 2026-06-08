"""Story 2.4 — lifecycle event model + in-process EventBus tests.

Covers:

* The L0 ``events.py`` model: the ``LifecycleEvent`` enum (member names + stable
  string values, frozen by the PRD) and the typed event payload structures
  (conversion payload carries domain fields only — NO raw visitor attributes;
  queue-released payload carries reason/batch_size/counts + optional error).
* The L3 in-process ``EventBus`` adapter: ``on`` registration, ``emit``
  invoking every handler with the documented payload, per-handler error
  isolation (a raising handler is logged + swallowed and does not break other
  handlers or delivery), and a zero-cost no-op when no handler is registered.

Unit-only (flat ``tests/`` layout per Stories 2.1-2.3). No network I/O.
"""

from __future__ import annotations

import logging

import pytest

from convert_sdk.events import (
    ConversionEventPayload,
    LifecycleEvent,
    QueueReleasedPayload,
)
from convert_sdk.adapters.events.in_process import InProcessEventBus
from convert_sdk.tracking.queue import ReleaseReason


# --- L0 enum (PRD-frozen identifiers) -------------------------------------


def test_lifecycle_event_members_and_values():
    assert LifecycleEvent.READY.value == "ready"
    assert LifecycleEvent.CONFIG_UPDATED.value == "config.updated"
    assert LifecycleEvent.BUCKETING.value == "bucketing"
    assert LifecycleEvent.CONVERSION.value == "conversion"
    assert LifecycleEvent.API_QUEUE_RELEASED.value == "api.queue.released"
    assert LifecycleEvent.DATA_STORE_QUEUE_RELEASED.value == "datastore.queue.released"


def test_lifecycle_event_has_exactly_the_expected_members():
    assert {m.name for m in LifecycleEvent} == {
        "READY",
        "CONFIG_UPDATED",
        "BUCKETING",
        "CONVERSION",
        "API_QUEUE_RELEASED",
        "DATA_STORE_QUEUE_RELEASED",
    }


# --- L0 typed payloads -----------------------------------------------------


def test_conversion_payload_carries_domain_fields_only():
    payload = ConversionEventPayload(
        visitor_id="v1", goal_id="g1", goal_key="purchase_completed"
    )
    assert payload.visitor_id == "v1"
    assert payload.goal_id == "g1"
    assert payload.goal_key == "purchase_completed"
    # No raw visitor attributes leak onto the payload surface.
    assert not hasattr(payload, "visitor_attributes")


def test_queue_released_payload_success_shape():
    payload = QueueReleasedPayload(
        reason=ReleaseReason.EXPLICIT,
        batch_size=3,
        visitor_count=2,
        event_count=3,
    )
    assert payload.reason is ReleaseReason.EXPLICIT
    assert payload.batch_size == 3
    assert payload.visitor_count == 2
    assert payload.event_count == 3
    assert payload.status_code is None
    assert payload.retry_attempts is None


def test_queue_released_payload_failure_carries_only_safe_error_context():
    payload = QueueReleasedPayload(
        reason=ReleaseReason.EXPLICIT,
        batch_size=2,
        visitor_count=1,
        event_count=2,
        status_code=503,
        retry_attempts=0,
    )
    assert payload.status_code == 503
    assert payload.retry_attempts == 0
    # Failure context must not expose secrets / raw PII surfaces.
    assert not hasattr(payload, "sdk_key")
    assert not hasattr(payload, "auth_header")
    assert not hasattr(payload, "visitor_attributes")


# --- L3 in-process EventBus ------------------------------------------------


def test_on_registers_and_emit_invokes_all_handlers_with_payload():
    bus = InProcessEventBus()
    received = []
    bus.on(LifecycleEvent.CONVERSION, lambda payload, error=None: received.append(("a", payload, error)))
    bus.on(LifecycleEvent.CONVERSION, lambda payload, error=None: received.append(("b", payload, error)))

    payload = ConversionEventPayload(visitor_id="v1", goal_id="g1", goal_key="k")
    bus.emit(LifecycleEvent.CONVERSION, payload)

    assert [r[0] for r in received] == ["a", "b"]
    assert all(r[1] is payload for r in received)
    assert all(r[2] is None for r in received)


def test_emit_with_no_handlers_is_a_noop():
    bus = InProcessEventBus()
    # No subscribers -> must not raise and must do nothing observable.
    bus.emit(LifecycleEvent.CONVERSION, ConversionEventPayload("v", "g", "k"))


def test_raising_handler_is_isolated_logged_and_swallowed(caplog):
    bus = InProcessEventBus()
    other = []

    def bad(payload, error=None):
        raise ValueError("boom")

    def good(payload, error=None):
        other.append(payload)

    bus.on(LifecycleEvent.CONVERSION, bad)
    bus.on(LifecycleEvent.CONVERSION, good)

    payload = ConversionEventPayload("v", "g", "k")
    with caplog.at_level(logging.ERROR):
        # Must not raise — the bad handler is isolated and swallowed.
        bus.emit(LifecycleEvent.CONVERSION, payload)

    # The good handler still ran despite the earlier handler raising.
    assert other == [payload]
    # The failure was logged (privacy-safe phrasing); no exception propagated.
    assert any("handler" in rec.message.lower() for rec in caplog.records)


def test_emit_passes_error_to_handlers_on_failure_outcome():
    bus = InProcessEventBus()
    seen = []
    bus.on(
        LifecycleEvent.API_QUEUE_RELEASED,
        lambda payload, error=None: seen.append((payload, error)),
    )
    payload = QueueReleasedPayload(
        reason=ReleaseReason.EXPLICIT,
        batch_size=1,
        visitor_count=1,
        event_count=1,
        status_code=500,
        retry_attempts=0,
    )
    err = RuntimeError("delivery failed")
    bus.emit(LifecycleEvent.API_QUEUE_RELEASED, payload, error=err)
    assert seen == [(payload, err)]
