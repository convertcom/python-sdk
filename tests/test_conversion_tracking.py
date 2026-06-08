"""Story 2.1 — conversion tracking tests (SDK-1/SDK-2/SDK-3).

Covers the first tracking-domain slice:

* Typed conversion result models (``ConversionResult`` / ``ConversionStatus``)
  and the in-process ``ConversionEvent`` value object (SDK-1).
* The ``tracking.conversions.create_conversion`` service that resolves a goal
  from the immutable snapshot and builds a queued conversion event, returning a
  typed NON-EXCEPTION result for both a valid goal (QUEUED) and an unknown goal
  (GOAL_NOT_FOUND, FR50) (SDK-2).
* ``Context.track_conversion(goal_key)`` public surface and the public API
  exports (SDK-3).

No network I/O, no payload assembly, no batching/dedup/flush — those land in
later Epic 2 stories.
"""

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.results import (
    ConversionEvent,
    ConversionResult,
    ConversionStatus,
)


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {"id": "e1", "key": "exp-one", "variations": [{"id": "v1", "key": "var-one"}]},
    ],
    "features": [],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "audiences": [],
    "segments": [],
}


# --- SDK-1: typed domain models ------------------------------------------


def test_conversion_status_has_queued_and_not_found():
    assert ConversionStatus.QUEUED.value == "queued"
    assert ConversionStatus.GOAL_NOT_FOUND.value == "goal_not_found"


def test_conversion_result_queued_carries_goal_identity_and_visitor():
    event = ConversionEvent(
        visitor_id="visitor-1", goal_id="g1", goal_key="purchase_completed"
    )
    result = ConversionResult(
        status=ConversionStatus.QUEUED,
        goal_key="purchase_completed",
        goal_id="g1",
        visitor_id="visitor-1",
        event=event,
    )
    assert result.status is ConversionStatus.QUEUED
    assert result.goal_key == "purchase_completed"
    assert result.goal_id == "g1"
    assert result.visitor_id == "visitor-1"
    assert result.event is event
    assert result.event.goal_key == "purchase_completed"


def test_conversion_result_goal_not_found_is_distinguishable_without_exception():
    result = ConversionResult(
        status=ConversionStatus.GOAL_NOT_FOUND,
        goal_key="ghost_goal",
        goal_id=None,
        visitor_id="visitor-1",
        event=None,
    )
    # Distinguishable from success purely by status (no try/except).
    assert result.status is ConversionStatus.GOAL_NOT_FOUND
    assert result.event is None
    assert result.goal_id is None


def test_conversion_result_is_frozen():
    result = ConversionResult(
        status=ConversionStatus.GOAL_NOT_FOUND,
        goal_key="x",
        goal_id=None,
        visitor_id="v",
        event=None,
    )
    with pytest.raises(Exception):
        result.status = ConversionStatus.QUEUED  # type: ignore[misc]


# --- SDK-2: create_conversion service ------------------------------------


def test_create_conversion_queues_event_for_valid_goal():
    from convert_sdk.tracking.conversions import create_conversion

    snap = load_snapshot(CONFIG)
    result = create_conversion(snap, visitor_id="visitor-1", goal_key="purchase_completed")
    assert result.status is ConversionStatus.QUEUED
    assert result.goal_id == "g1"
    assert result.goal_key == "purchase_completed"
    assert result.visitor_id == "visitor-1"
    assert result.event is not None
    assert result.event.visitor_id == "visitor-1"
    assert result.event.goal_id == "g1"
    assert result.event.goal_key == "purchase_completed"


def test_create_conversion_unknown_goal_returns_typed_not_found_result():
    from convert_sdk.tracking.conversions import create_conversion

    snap = load_snapshot(CONFIG)
    result = create_conversion(snap, visitor_id="visitor-1", goal_key="ghost_goal")
    # FR50: diagnosable NON-EXCEPTION outcome, distinguishable from success.
    assert result.status is ConversionStatus.GOAL_NOT_FOUND
    assert result.goal_key == "ghost_goal"
    assert result.event is None


def test_create_conversion_does_not_raise_for_unknown_goal():
    from convert_sdk.tracking.conversions import create_conversion

    snap = load_snapshot(CONFIG)
    # Must not raise — non-exception diagnosable outcome.
    create_conversion(snap, visitor_id="v", goal_key="nope")


# --- SDK-3: Context.track_conversion public surface ----------------------


def _context(visitor_id="visitor-1"):
    snap = load_snapshot(CONFIG)
    return Context(visitor_id, snap)


def test_context_track_conversion_returns_queued_result_for_valid_goal():
    ctx = _context()
    result = ctx.track_conversion("purchase_completed")
    assert isinstance(result, ConversionResult)
    assert result.status is ConversionStatus.QUEUED
    assert result.goal_id == "g1"
    assert result.goal_key == "purchase_completed"
    assert result.visitor_id == "visitor-1"
    assert result.event is not None


def test_context_track_conversion_associates_event_with_visitor():
    ctx = _context(visitor_id="abc-999")
    result = ctx.track_conversion("signup")
    assert result.status is ConversionStatus.QUEUED
    assert result.visitor_id == "abc-999"
    assert result.event.visitor_id == "abc-999"
    assert result.goal_id == "g2"


def test_context_track_conversion_unknown_goal_is_diagnosable_non_exception():
    ctx = _context()
    result = ctx.track_conversion("not_a_real_goal")
    assert result.status is ConversionStatus.GOAL_NOT_FOUND
    assert result.event is None


def test_public_api_exports_conversion_types():
    import convert_sdk

    assert "ConversionResult" in convert_sdk.__all__
    assert "ConversionStatus" in convert_sdk.__all__
    assert convert_sdk.ConversionResult is ConversionResult
    assert convert_sdk.ConversionStatus is ConversionStatus


# --- Story 3.3 Task 5: reporting carry of default segments ----------------
#
# A tracked conversion's ``segments`` payload field reflects the visitor's
# active default segments at the time of conversion (FR14). The Story 2.2
# serializer owns the field shape; Story 3.3 only makes the data available.


def test_conversion_carries_active_default_segments_after_set_segments():
    from convert_sdk.tracking.payloads import build_tracking_payload

    snap = load_snapshot(CONFIG)
    ctx = Context("v_a", snap)
    ctx.set_segments({"browser": "chrome", "country": "US"})
    result = ctx.track_conversion("purchase_completed")
    assert result.event is not None
    # The serialized conversion's segments field reflects the active default
    # segments (filtered through the existing VisitorSegments allowlist).
    visitor = build_tracking_payload(snap, result.event)["visitors"][0]
    assert visitor["segments"] == {"browser": "chrome", "country": "US"}


def test_conversion_carries_custom_segments_after_run_custom_segments():
    from convert_sdk.tracking.payloads import build_tracking_payload

    cfg = dict(CONFIG)
    cfg["segments"] = [{"id": "s_us", "key": "us-seg", "rules": None}]
    snap = load_snapshot(cfg)
    ctx = Context("v_a", snap)
    ctx.run_custom_segments(["us-seg"])  # rule-less → matches
    result = ctx.track_conversion("purchase_completed")
    assert result.event is not None
    visitor = build_tracking_payload(snap, result.event)["visitors"][0]
    # The matched custom-segment ids carry through under customSegments.
    assert visitor["segments"]["customSegments"] == ["s_us"]


def test_default_segments_take_precedence_over_attribute_segments():
    from convert_sdk.tracking.payloads import build_tracking_payload

    snap = load_snapshot(CONFIG)
    ctx = Context("v_a", snap, visitor_attributes={"country": "DE"})
    ctx.set_segments({"country": "US"})
    result = ctx.track_conversion("purchase_completed")
    visitor = build_tracking_payload(snap, result.event)["visitors"][0]
    # Default segments are the explicit association → they win on key conflict.
    assert visitor["segments"]["country"] == "US"


def test_conversion_without_segments_unaffected():
    # A visitor with no default segments keeps the prior attribute-derived
    # segments behavior (no regression to Story 2.2).
    from convert_sdk.tracking.payloads import build_tracking_payload

    snap = load_snapshot(CONFIG)
    ctx = Context("v_a", snap, visitor_attributes={"country": "US"})
    result = ctx.track_conversion("purchase_completed")
    visitor = build_tracking_payload(snap, result.event)["visitors"][0]
    assert visitor["segments"] == {"country": "US"}


# --- Story 2.3: dedup outcomes + force_multiple on the public surface -----


def test_conversion_status_has_deduplicated():
    assert ConversionStatus.DEDUPLICATED.value == "deduplicated"


def test_conversion_result_tracked_and_reason_properties():
    # PRD contract surfaced WITHOUT changing the Story 2.1 fields: tracked/reason
    # are derived from status.
    queued = ConversionResult(
        status=ConversionStatus.QUEUED,
        goal_key="g",
        goal_id="g1",
        visitor_id="v",
        event=None,
    )
    assert queued.tracked is True
    assert queued.reason is None

    dedup = ConversionResult(
        status=ConversionStatus.DEDUPLICATED,
        goal_key="g",
        goal_id="g1",
        visitor_id="v",
        event=None,
    )
    assert dedup.tracked is False
    assert dedup.reason == "deduplicated"

    not_found = ConversionResult(
        status=ConversionStatus.GOAL_NOT_FOUND,
        goal_key="g",
        goal_id=None,
        visitor_id="v",
        event=None,
    )
    assert not_found.tracked is False
    assert not_found.reason == "goal_not_found"


def _core_with_two_goals():
    from convert_sdk import Core, SDKConfig

    core = Core(SDKConfig(data=CONFIG)).initialize()
    return core


def test_track_conversion_default_duplicate_is_deduplicated():
    core = _core_with_two_goals()
    ctx = core.create_context("visitor-1")
    first = ctx.track_conversion("purchase_completed")
    assert first.status is ConversionStatus.QUEUED
    assert first.tracked is True

    second = ctx.track_conversion("purchase_completed")
    assert second.status is ConversionStatus.DEDUPLICATED
    assert second.tracked is False
    assert second.reason == "deduplicated"


def test_track_conversion_force_multiple_retracks():
    core = _core_with_two_goals()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed")
    again = ctx.track_conversion("purchase_completed", force_multiple=True)
    assert again.status is ConversionStatus.QUEUED
    assert again.tracked is True


def test_track_conversion_dedup_is_by_goal_identity_not_payload():
    core = _core_with_two_goals()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed", revenue=10.0)
    # Different revenue must NOT defeat dedup.
    second = ctx.track_conversion("purchase_completed", revenue=99.0)
    assert second.status is ConversionStatus.DEDUPLICATED


def test_track_conversion_unknown_goal_still_not_found():
    core = _core_with_two_goals()
    ctx = core.create_context("visitor-1")
    result = ctx.track_conversion("ghost_goal")
    assert result.status is ConversionStatus.GOAL_NOT_FOUND


def test_dedup_state_shared_across_contexts_from_same_core():
    # Contexts created from one Core share the dedup store, so the same visitor
    # dedups across context instances (per-process boundary).
    core = _core_with_two_goals()
    ctx_a = core.create_context("visitor-1")
    ctx_b = core.create_context("visitor-1")
    ctx_a.track_conversion("signup")
    second = ctx_b.track_conversion("signup")
    assert second.status is ConversionStatus.DEDUPLICATED


# --- Story 2.3: Core.flush() empty-queue no-op + GOAL_NOT_FOUND not queued -


def test_flush_on_empty_queue_is_noop_no_transport_call():
    core = _core_with_two_goals()
    # No events tracked; flush must not raise and must not need a transport.
    core.flush()  # should be a safe no-op


def test_goal_not_found_does_not_enqueue():
    core = _core_with_two_goals()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("ghost_goal")
    # Nothing queued -> flush is a no-op (no transport configured for direct cfg).
    core.flush()


# --- Story 2.4: CONVERSION lifecycle emission on the enqueue path ----------


def _core_with_conversion_listener():
    """A Core plus a list capturing every CONVERSION payload it emits."""
    from convert_sdk import LifecycleEvent

    core = _core_with_two_goals()
    received = []
    core.on(
        LifecycleEvent.CONVERSION,
        lambda payload, error=None: received.append(payload),
    )
    return core, received


def test_conversion_event_fires_once_on_tracked_enqueue():
    from convert_sdk.events import ConversionEventPayload

    core, received = _core_with_conversion_listener()
    core.create_context("visitor-1").track_conversion("purchase_completed")

    assert len(received) == 1
    payload = received[0]
    assert isinstance(payload, ConversionEventPayload)
    assert payload.visitor_id == "visitor-1"
    assert payload.goal_id == "g1"
    assert payload.goal_key == "purchase_completed"


def test_conversion_event_does_not_fire_on_deduplicated_suppression():
    core, received = _core_with_conversion_listener()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed")  # tracked -> 1 emission
    second = ctx.track_conversion("purchase_completed")  # default-mode duplicate

    assert second.status is ConversionStatus.DEDUPLICATED
    # The suppressed duplicate must NOT emit a second CONVERSION (AC #4).
    assert len(received) == 1


def test_conversion_event_does_not_fire_on_goal_not_found():
    core, received = _core_with_conversion_listener()
    result = core.create_context("visitor-1").track_conversion("ghost_goal")

    assert result.status is ConversionStatus.GOAL_NOT_FOUND
    # An unknown goal is a typed no-result, not a state transition (AC #4).
    assert received == []


def test_force_multiple_retrack_emits_conversion_again():
    # A forced repeat re-enqueues only when there is something to send (goalData,
    # e.g. revenue) — the transaction path. Each actual enqueue emits exactly one
    # CONVERSION (events reflect real enqueues, not no-op calls).
    core, received = _core_with_conversion_listener()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed", revenue=10.0)  # 1 (enqueued)
    ctx.track_conversion(
        "purchase_completed", revenue=20.0, force_multiple=True
    )  # 2 (re-enqueued transaction)
    assert len(received) == 2


def test_tracking_behaves_identically_with_and_without_subscribers():
    # NFR5 / AC #5: emission is a no-op when no handler is registered, so the
    # tracked outcome is identical with or without subscribers.
    core_no_sub = _core_with_two_goals()
    r1 = core_no_sub.create_context("v1").track_conversion("purchase_completed")

    core_sub, received = _core_with_conversion_listener()
    r2 = core_sub.create_context("v1").track_conversion("purchase_completed")

    assert r1.status is r2.status is ConversionStatus.QUEUED
    assert len(received) == 1  # subscriber observed it; outcome unchanged
