"""Unit tests for the anchored bucketing layout's pure selection primitives
(qs-01-anchored-bucketing-layout.md, bucketing contract v12).

``build_bucket_ranges`` / ``select_bucket_anchored`` live in
``convert_sdk.evaluation.bucketing`` and implement the anchored-layout
contract mirrored from the JS reference (``../javascript-sdk`` branch
``feat/anchored-bucketing-layout``,
``packages/bucketing/src/bucketing-manager.ts`` ``getBucketRanges`` /
``selectBucketAnchored``)::

    build_bucket_ranges(
        allocations: Sequence[Mapping[str, Any]],  # [{"id", "allocation", "active"}, ...]
    ) -> list[dict[str, Any]]                        # [{"id", "anchor", "width"}, ...]

    select_bucket_anchored(
        ranges: Sequence[Mapping[str, Any]],         # output of build_bucket_ranges
        value: int,
    ) -> Optional[str]

Hash, seed (9999), scaling, and ``get_bucket_value_for_visitor`` are all
unchanged and already covered by ``tests/test_bucketing.py`` -- this file
covers only the new anchored-layout arithmetic these two callables add.
"""

from __future__ import annotations

from typing import Any

import pytest

from convert_sdk.evaluation.bucketing import build_bucket_ranges, select_bucket_anchored


def _allocation(id_: str, allocation: float, active: bool = True) -> "dict[str, Any]":
    """Shared allocation-entry factory -- avoids copy-pasted dict literals."""
    return {"id": id_, "allocation": allocation, "active": active}


def _select(allocations: "list[dict[str, Any]]", value: int):
    """Shared build+select round trip -- the same two-call seam every case below exercises."""
    return select_bucket_anchored(build_bucket_ranges(allocations), value)


def _thirds(total_pct: float) -> "list[dict[str, Any]]":
    """3 equal running arms summing to ``total_pct`` -- the qs-01 worked example."""
    each = total_pct / 3
    return [_allocation("O", each), _allocation("V1", each), _allocation("V2", each)]


# --- AC5: totalWeight <= 0 --> not bucketed ----------------------------------


def test_total_weight_zero_is_not_bucketed():
    allocations = [_allocation("a", 0, active=False), _allocation("b", 0, active=True)]
    assert _select(allocations, 0) is None


def test_negative_total_weight_is_not_bucketed():
    # Defensive: the contract only specifies "<= 0", not "never negative".
    allocations = [_allocation("a", -5)]
    assert _select(allocations, 0) is None


# --- AC5: the range is half-open [anchor, anchor + width) -------------------


def test_value_equal_to_anchor_is_in_range():
    # 2 equal arms of weight 50 each -> anchors 0 and 5000, width 5000 each.
    allocations = [_allocation("a", 50), _allocation("b", 50)]
    assert _select(allocations, 5000) == "b"  # exactly at b's anchor -> IN


def test_value_equal_to_anchor_plus_width_is_out():
    allocations = [_allocation("a", 50), _allocation("b", 50)]
    assert _select(allocations, 10000) is None  # b's anchor + width == 10000, OUT


def test_value_one_below_anchor_plus_width_is_in():
    allocations = [_allocation("a", 50), _allocation("b", 50)]
    assert _select(allocations, 4999) == "a"
    assert _select(allocations, 9999) == "b"


# --- AC2 / AC3: qs-01 worked example (3 equal arms, 15% -> 25%) -------------
# packed   15%: O [0,500)     V1 [500,1000)     V2 [1000,1500)
# packed   25%: O [0,833)     V1 [833,1666)     V2 [1666,2500)
# anchored 15%: O [0,500)     V1 [3333,3833)    V2 [6667,7167)
# anchored 25%: O [0,833)     V1 [3333,4166)    V2 [6667,7500)
# V1/V2's anchors are IDENTICAL at both coverage levels; only width grows.


def test_raise_15_to_25_pct_ranges_match_worked_example():
    by_id_15 = {r["id"]: r for r in build_bucket_ranges(_thirds(15))}
    by_id_25 = {r["id"]: r for r in build_bucket_ranges(_thirds(25))}

    assert by_id_15["O"]["anchor"] == 0
    assert by_id_15["O"]["width"] == pytest.approx(500)
    assert by_id_15["V1"]["anchor"] == pytest.approx(3333.333, abs=0.01)
    assert by_id_15["V1"]["width"] == pytest.approx(500)
    assert by_id_15["V2"]["anchor"] == pytest.approx(6666.667, abs=0.01)
    assert by_id_15["V2"]["width"] == pytest.approx(500)

    # Anchors are IDENTICAL at 25% -- only width grows (+333.33 each).
    assert by_id_25["O"]["anchor"] == 0
    assert by_id_25["O"]["width"] == pytest.approx(833.33, abs=0.01)
    assert by_id_25["V1"]["anchor"] == pytest.approx(by_id_15["V1"]["anchor"])
    assert by_id_25["V1"]["width"] == pytest.approx(833.33, abs=0.01)
    assert by_id_25["V2"]["anchor"] == pytest.approx(by_id_15["V2"]["anchor"])
    assert by_id_25["V2"]["width"] == pytest.approx(833.33, abs=0.01)


def test_raise_is_a_superset_same_visitor_keeps_arm():
    # A value already inside V1's 15% band stays in V1 at 25% (superset).
    value_in_both_bands = 3500  # in [3333.33, 3833.33) AND [3333.33, 4166.67)
    assert _select(_thirds(15), value_in_both_bands) == "V1"
    assert _select(_thirds(25), value_in_both_bands) == "V1"


def test_raise_admits_new_visitors_per_sliver_at_the_arms_own_edge():
    # Outside V1's 15% band but inside its 25% band -- new admission, no flip.
    value_new_admission = 4000
    assert _select(_thirds(15), value_new_admission) is None
    assert _select(_thirds(25), value_new_admission) == "V1"


def test_lower_ejects_without_flipping_arms():
    # A visitor bucketed at 25% falls out cleanly at 15% -- never into another arm.
    value_new_admission = 4000
    assert _select(_thirds(25), value_new_admission) == "V1"
    assert _select(_thirds(15), value_new_admission) is None
    assert _select(_thirds(15), value_new_admission) != "O"
    assert _select(_thirds(15), value_new_admission) != "V2"


# --- AC4: stopped arms keep their anchor weight, get zero width -------------


def test_stopped_arm_keeps_weight_but_gets_zero_width():
    running = [_allocation("O", 10), _allocation("V1", 80), _allocation("V2", 10)]
    stopped = [_allocation("O", 10), _allocation("V1", 80, active=False), _allocation("V2", 10)]

    ranges_running = {r["id"]: r for r in build_bucket_ranges(running)}
    ranges_stopped = {r["id"]: r for r in build_bucket_ranges(stopped)}

    # O and V2's anchors AND widths are byte-identical -- V1 stopping doesn't
    # reshuffle its neighbours.
    assert ranges_running["O"] == ranges_stopped["O"]
    assert ranges_stopped["V2"]["anchor"] == ranges_running["V2"]["anchor"]
    assert ranges_stopped["V2"]["width"] == ranges_running["V2"]["width"]

    # V1 keeps its anchor (weight preserved) but drops to zero width.
    assert ranges_stopped["V1"]["anchor"] == ranges_running["V1"]["anchor"]
    assert ranges_stopped["V1"]["width"] == 0
    assert ranges_running["V1"]["width"] != 0


def test_stopped_arm_is_never_selected():
    stopped = [_allocation("O", 10), _allocation("V1", 80, active=False), _allocation("V2", 10)]
    value_inside_v1s_old_band = 4957  # inside V1's would-be [1000, 9000) band
    assert _select(stopped, value_inside_v1s_old_band) is None


def test_explicit_zero_allocation_behaves_like_stopped_never_100pct():
    # ta: 0 must be zero WIDTH, never re-interpreted as the isNaN "100%" default.
    allocations = [
        _allocation("O", 2),
        _allocation("V1", 47),
        _allocation("Z", 0, active=False),
        _allocation("V2", 1),
    ]
    ranges = {r["id"]: r for r in build_bucket_ranges(allocations)}
    assert ranges["Z"]["width"] == 0
