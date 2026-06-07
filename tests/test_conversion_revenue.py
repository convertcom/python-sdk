"""Story 2.2 (SDK-2) — revenue + conversion_data + attribution in the service.

Covers the tracking-service layer (no wire mapping — that is SDK-3):

* ``Context.track_conversion`` accepts optional ``revenue`` and
  ``conversion_data`` keyword arguments (forward-compatible over Story 2.1's
  goal-key-only surface) and still returns the unchanged typed
  ``ConversionResult`` contract.
* ``tracking.conversions.create_conversion`` carries revenue + conversion_data
  into the internal ``ConversionEvent`` and populates attribution context
  (active segments + active variation/bucketing assignments) derived from the
  visitor's evaluation against the immutable snapshot at conversion time (AC#1,
  FR34).
* A non-JSON-serializable / nested ``conversion_data`` value raises the typed
  ``ConversionDataError`` and does NOT produce a queued event (AC#3).
* The Story 2.1 unknown-goal NON-EXCEPTION outcome is preserved.
"""

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.results import ConversionResult, ConversionStatus
from convert_sdk.errors import ConversionDataError
from convert_sdk.tracking.conversions import create_conversion


# A config with one always-on experience so the visitor gets a deterministic
# active variation assignment (for bucketing attribution).
CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {
            "id": "e1",
            "key": "exp-one",
            "variations": [{"id": "v1", "key": "var-one", "traffic_allocation": 100}],
        },
    ],
    "features": [],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "audiences": [],
    "segments": [],
}


def _context(visitor_id="visitor-1", **kwargs):
    snap = load_snapshot(CONFIG)
    return Context(visitor_id, snap, **kwargs)


# --- public surface: revenue + conversion_data keyword args --------------


def test_track_conversion_accepts_revenue_kwarg():
    ctx = _context()
    result = ctx.track_conversion("purchase_completed", revenue=42.5)
    assert isinstance(result, ConversionResult)
    assert result.status is ConversionStatus.QUEUED
    assert result.event is not None
    assert result.event.revenue == 42.5


def test_track_conversion_accepts_conversion_data_kwarg():
    ctx = _context()
    result = ctx.track_conversion(
        "purchase_completed",
        conversion_data={"transactionId": "tx-9", "productsCount": 3},
    )
    assert result.status is ConversionStatus.QUEUED
    assert result.event.conversion_data == {
        "transactionId": "tx-9",
        "productsCount": 3,
    }


def test_track_conversion_result_contract_unchanged_for_goal_key_only():
    # Story 2.1 callers (no new kwargs) must see identical behavior.
    ctx = _context()
    result = ctx.track_conversion("signup")
    assert result.status is ConversionStatus.QUEUED
    assert result.goal_id == "g2"
    assert result.goal_key == "signup"
    assert result.event.revenue is None
    assert result.event.conversion_data is None


def test_track_conversion_unknown_goal_still_non_exception():
    ctx = _context()
    result = ctx.track_conversion("ghost", revenue=10.0)
    assert result.status is ConversionStatus.GOAL_NOT_FOUND
    assert result.event is None


# --- attribution context (AC#1 / FR34) -----------------------------------


def test_event_carries_active_variation_bucketing_assignments():
    ctx = _context()
    result = ctx.track_conversion("purchase_completed")
    # The always-on experience e1 buckets the visitor into variation v1.
    assert result.event.bucketing_assignments == {"e1": "v1"}


def test_event_carries_visitor_segments_for_attribution():
    ctx = _context(visitor_attributes={"country": "US", "plan": "pro"})
    result = ctx.track_conversion("purchase_completed")
    assert result.event.segments == {"country": "US", "plan": "pro"}


def test_create_conversion_service_populates_revenue_and_attribution():
    snap = load_snapshot(CONFIG)
    result = create_conversion(
        snap,
        visitor_id="visitor-1",
        goal_key="purchase_completed",
        revenue=99.0,
        conversion_data={"transactionId": "tx-1"},
        visitor_attributes={"country": "FR"},
    )
    assert result.status is ConversionStatus.QUEUED
    assert result.event.revenue == 99.0
    assert result.event.conversion_data == {"transactionId": "tx-1"}
    assert result.event.bucketing_assignments == {"e1": "v1"}
    assert result.event.segments == {"country": "FR"}


# --- validation: bad conversion_data fails fast (AC#3) -------------------


def test_nested_conversion_data_value_raises_typed_error_and_does_not_enqueue():
    ctx = _context()
    with pytest.raises(ConversionDataError):
        ctx.track_conversion(
            "purchase_completed",
            conversion_data={"nested": {"not": "allowed"}},
        )


def test_non_serializable_conversion_data_value_raises_typed_error():
    ctx = _context()

    class Weird:
        pass

    with pytest.raises(ConversionDataError):
        ctx.track_conversion(
            "purchase_completed",
            conversion_data={"obj": Weird()},
        )


def test_list_conversion_data_value_raises_typed_error():
    # Only JSON primitives allowed (str/number/bool/None); arrays/objects no.
    ctx = _context()
    with pytest.raises(ConversionDataError):
        ctx.track_conversion(
            "purchase_completed", conversion_data={"items": [1, 2, 3]}
        )


def test_json_primitive_conversion_data_values_are_accepted():
    ctx = _context()
    result = ctx.track_conversion(
        "purchase_completed",
        conversion_data={
            "transactionId": "tx-1",
            "productsCount": 3,
            "flag": True,
            "nothing": None,
            "rate": 1.5,
        },
    )
    assert result.status is ConversionStatus.QUEUED


def test_bad_conversion_data_error_is_distinct_from_unknown_goal():
    # Programmer misuse (bad data) raises; unknown goal does not — the two are
    # never conflated.
    ctx = _context()
    miss = ctx.track_conversion("ghost_goal")
    assert miss.status is ConversionStatus.GOAL_NOT_FOUND
    with pytest.raises(ConversionDataError):
        ctx.track_conversion("ghost_goal", conversion_data={"x": object()})
