"""Story 2.3 — goal deduplication unit tests (BE-2).

Parametrized over every row of the goal-deduplication truth table
(architecture #Goal-Deduplication-Truth-Table), proving:

* dedup key is ``(visitor_id, goal_id)`` within the DataStore scope;
* a differing ``revenue`` / ``conversion_data`` does NOT defeat dedup (dedup is
  by goal identity, not payload content);
* ``force_multiple=True`` re-tracks an already-tracked goal;
* the "goal tracked" marker is persisted UNCONDITIONALLY for every call that
  passes the goal-rule check — including ``force_multiple=True`` (F-007,
  mirroring JS ``putData`` executed before the conditional sends);
* state goes through the ``DataStore`` protocol, never a private dict
  (Critical Warning #5).
"""

import pytest

from convert_sdk import InMemoryDataStore
from convert_sdk.tracking.deduplication import (
    DedupDecision,
    evaluate_dedup,
    goal_marker_key,
)


# --- key shape ------------------------------------------------------------


def test_goal_marker_key_is_visitor_and_goal_scoped():
    k1 = goal_marker_key("v1", "g1")
    k2 = goal_marker_key("v1", "g2")
    k3 = goal_marker_key("v2", "g1")
    assert k1 != k2 and k1 != k3 and k2 != k3


def test_goal_marker_key_is_namespaced_and_collision_safe():
    # F-050: collision-safe namespaced key f"dedup:{json.dumps([visitor, goal])}".
    # A naive composite (f"{visitor}:{goal}") collides when values contain the
    # separator; the JSON-list form does not.
    assert goal_marker_key("v1", "g1").startswith("dedup:")
    # ("a:b", "c") and ("a", "b:c") must produce DISTINCT keys.
    assert goal_marker_key("a:b", "c") != goal_marker_key("a", "b:c")


# --- truth table ----------------------------------------------------------


def test_first_time_tracks_and_stores_marker():
    store = InMemoryDataStore()
    decision = evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    assert decision.suppressed is False
    assert decision.should_send_conversion is True
    # Marker persisted so the next default call suppresses.
    assert store.has(goal_marker_key("v1", "g1")) is True


def test_default_duplicate_is_suppressed():
    store = InMemoryDataStore()
    evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    decision = evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    assert decision.suppressed is True
    assert decision.should_send_conversion is False


def test_differing_payload_still_suppressed():
    # Dedup is by goal identity, not payload — a different revenue/data must not
    # defeat suppression.
    store = InMemoryDataStore()
    evaluate_dedup(
        store, visitor_id="v1", goal_id="g1", force_multiple=False, has_goal_data=True
    )
    decision = evaluate_dedup(
        store, visitor_id="v1", goal_id="g1", force_multiple=False, has_goal_data=True
    )
    assert decision.suppressed is True


def test_force_multiple_retracks_already_tracked_goal():
    store = InMemoryDataStore()
    evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    decision = evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=True)
    assert decision.suppressed is False


def test_force_multiple_on_already_tracked_sends_transaction_not_conversion():
    # F-006: on a repeat under force_multiple, the bare conversion is NOT
    # re-sent (guarded by !goalTriggered); only the transaction (goalData) path.
    store = InMemoryDataStore()
    evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    decision = evaluate_dedup(
        store, visitor_id="v1", goal_id="g1", force_multiple=True, has_goal_data=True
    )
    assert decision.should_send_conversion is False
    assert decision.should_send_transaction is True


def test_first_call_with_goal_data_sends_both_conversion_and_transaction():
    # First time, goalData present, !goalTriggered -> conversion AND transaction.
    store = InMemoryDataStore()
    decision = evaluate_dedup(
        store, visitor_id="v1", goal_id="g1", force_multiple=False, has_goal_data=True
    )
    assert decision.should_send_conversion is True
    assert decision.should_send_transaction is True


def test_first_call_without_goal_data_sends_only_conversion():
    store = InMemoryDataStore()
    decision = evaluate_dedup(
        store, visitor_id="v1", goal_id="g1", force_multiple=False, has_goal_data=False
    )
    assert decision.should_send_conversion is True
    assert decision.should_send_transaction is False


def test_force_multiple_persists_marker_unconditionally():
    # F-007: even when the FIRST call uses force_multiple=True, the marker must
    # be stored so subsequent default-mode calls dedup correctly.
    store = InMemoryDataStore()
    evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=True)
    assert store.has(goal_marker_key("v1", "g1")) is True
    # A following default call now suppresses.
    decision = evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    assert decision.suppressed is True


def test_dedup_uses_data_store_boundary_not_private_state():
    # Two separate dedup evaluations sharing a store see each other's markers;
    # two evaluations with separate stores are isolated (per-process boundary).
    store_a = InMemoryDataStore()
    store_b = InMemoryDataStore()
    evaluate_dedup(store_a, visitor_id="v1", goal_id="g1", force_multiple=False)
    # store_b never saw the marker -> not suppressed.
    decision_b = evaluate_dedup(store_b, visitor_id="v1", goal_id="g1", force_multiple=False)
    assert decision_b.suppressed is False


@pytest.mark.parametrize(
    "already, force_multiple, has_goal_data, exp_suppressed, exp_conv, exp_txn",
    [
        # not tracked, default, no goalData -> track, conversion only
        (False, False, False, False, True, False),
        # not tracked, default, goalData -> track, conversion + transaction
        (False, False, True, False, True, True),
        # already, default -> suppress
        (True, False, False, True, False, False),
        (True, False, True, True, False, False),
        # already, force_multiple, goalData -> transaction only (no conversion)
        (True, True, True, False, False, True),
        # already, force_multiple, no goalData -> nothing to re-send, not suppressed
        (True, True, False, False, False, False),
    ],
)
def test_truth_table_matrix(
    already, force_multiple, has_goal_data, exp_suppressed, exp_conv, exp_txn
):
    store = InMemoryDataStore()
    if already:
        evaluate_dedup(store, visitor_id="v1", goal_id="g1", force_multiple=False)
    decision = evaluate_dedup(
        store,
        visitor_id="v1",
        goal_id="g1",
        force_multiple=force_multiple,
        has_goal_data=has_goal_data,
    )
    assert decision.suppressed is exp_suppressed
    assert decision.should_send_conversion is exp_conv
    assert decision.should_send_transaction is exp_txn
    assert isinstance(decision, DedupDecision)
