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
