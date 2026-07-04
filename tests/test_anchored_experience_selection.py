"""Unit tests for the anchored-layout gate + config-adaptation helpers in
``convert_sdk.evaluation.experiences``, plus the full-pipeline wiring, guard
precedence, and API-shape acceptance criteria (qs-01-anchored-bucketing-layout.md,
bucketing contract v12).

``experiences._is_anchored_layout`` and
``experiences._build_variation_allocations`` are module-level functions on
``convert_sdk.evaluation.experiences``, exercised directly here mirroring the
direct-helper convention in ``tests/test_evaluation_internals.py``.

Grounded in the JS reference (``../javascript-sdk`` branch
``feat/anchored-bucketing-layout``, ``packages/data/src/data-manager.ts``)::

    isAnchoredLayout = Number(experience.version) > 11
    _buildVariationAllocations(variations) -> VariationAllocation[]
        { id, allocation: isNaN(ta) ? 100.0 : Number(ta),
          active: (status ? status === RUNNING : true) && (ta > 0 || isNaN(ta)) }

and in ``src/convert_sdk/evaluation/experiences.py`` (read in full for this
spec): ``select_experience`` is a PURE, STATELESS function today -- it takes
only the immutable snapshot plus a visitor id/attributes and always
recomputes the hash-based bucket from scratch. There is no
``force_variation_id`` / sticky / stored-decision parameter or branch at this
seam (contrast the JS reference's ``DataManager._retrieveBucketing``, which
checks ``forceVariationId`` and a stored ``bucketing`` map BEFORE ever reaching
the packed/anchored gate). AC8's tests below document that actual, verified
gap rather than fabricate a mechanism this Python seam doesn't have.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ExperienceResult
from convert_sdk.evaluation import experiences
from convert_sdk.evaluation.experiences import select_experience


def _snapshot(experiences_list: "list[dict[str, Any]]") -> Any:
    return load_snapshot(
        {
            "account_id": "1",
            "project": {"id": "2"},
            "experiences": list(experiences_list),
        }
    )


def _thirds_experience(
    version: Any, total_pct: float, exp_id: str = "e1", key: str = "exp"
) -> "dict[str, Any]":
    """3 equal running arms summing to ``total_pct`` -- the qs-01 worked example."""
    each = total_pct / 3
    return {
        "id": exp_id,
        "key": key,
        "version": version,
        "variations": [
            {"id": "O", "traffic_allocation": each, "status": "running"},
            {"id": "V1", "traffic_allocation": each, "status": "running"},
            {"id": "V2", "traffic_allocation": each, "status": "running"},
        ],
    }


# ---------------------------------------------------------------------------
# AC1 -- the version gate, in isolation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("version", "expect_anchored"),
    [
        (12, True),
        (13, True),
        ("12", True),  # numeric-string coercion parity: Number("12") > 11
        (11, False),
        # GREEN-phase fix (genuine RED-phase test bug, flagged not silently
        # patched): the gate is a literal `Number(experience.version) > 11`
        # with no flooring (../javascript-sdk data-manager.ts:695, and no
        # fractional-version case exists in that file's own gate test suite
        # data-manager-anchored-gate.tests.ts to contradict it). 11.9 > 11 is
        # mathematically True, so this must route anchored, not packed -- the
        # spec text's "version <= 11 ... -> packed" also excludes 11.9.
        (11.9, True),
        ("11", False),
        ("abc", False),  # Number("abc") is NaN -> NaN > 11 is False
        (float("nan"), False),
    ],
)
def test_is_anchored_layout_gate_branching(version, expect_anchored):
    experience = {"id": "e1", "variations": [], "version": version}
    assert experiences._is_anchored_layout(experience) is expect_anchored


def test_is_anchored_layout_missing_version_is_packed():
    assert experiences._is_anchored_layout({"id": "e1", "variations": []}) is False


# ---------------------------------------------------------------------------
# AC4 / AC5 -- experiences._build_variation_allocations
# ---------------------------------------------------------------------------


def test_build_variation_allocations_preserves_full_order_incl_inactive():
    experience = {
        "variations": [
            {"id": "O", "traffic_allocation": 10, "status": "running"},
            {"id": "V1", "traffic_allocation": 80, "status": "stopped"},
            {"id": "V2", "traffic_allocation": 10, "status": "running"},
        ]
    }
    allocations = experiences._build_variation_allocations(experience)
    # Unlike _build_buckets (packed), the stopped arm is NOT dropped.
    assert [a["id"] for a in allocations] == ["O", "V1", "V2"]
    by_id = {a["id"]: a for a in allocations}
    assert by_id["V1"]["allocation"] == 80.0
    assert by_id["V1"]["active"] is False
    assert by_id["O"]["active"] is True
    assert by_id["V2"]["active"] is True


def test_build_variation_allocations_missing_ta_defaults_to_100_and_active():
    experience = {"variations": [{"id": "DEFAULT", "status": "running"}]}
    allocations = experiences._build_variation_allocations(experience)
    assert allocations == [{"id": "DEFAULT", "allocation": 100.0, "active": True}]


def test_build_variation_allocations_non_numeric_ta_treated_as_nan():
    experience = {
        "variations": [{"id": "v1", "traffic_allocation": "abc", "status": "running"}]
    }
    allocations = experiences._build_variation_allocations(experience)
    assert allocations[0]["allocation"] == 100.0
    assert allocations[0]["active"] is True


def test_build_variation_allocations_actual_nan_float_defaults_to_100():
    experience = {
        "variations": [
            {"id": "v1", "traffic_allocation": float("nan"), "status": "running"}
        ]
    }
    allocations = experiences._build_variation_allocations(experience)
    assert allocations[0]["allocation"] == 100.0
    assert allocations[0]["active"] is True


def test_build_variation_allocations_explicit_zero_is_inactive_never_100():
    experience = {
        "variations": [{"id": "Z", "traffic_allocation": 0, "status": "running"}]
    }
    allocations = experiences._build_variation_allocations(experience)
    assert allocations[0]["allocation"] == 0.0
    assert allocations[0]["active"] is False  # never re-interpreted as 100%


def test_build_variation_allocations_skips_entries_without_id():
    experience = {
        "variations": [
            {"traffic_allocation": 50, "status": "running"},  # no id -> skipped
            {"id": "v1", "traffic_allocation": 50, "status": "running"},
        ]
    }
    allocations = experiences._build_variation_allocations(experience)
    assert [a["id"] for a in allocations] == ["v1"]


def test_build_variation_allocations_empty_when_no_variations():
    assert experiences._build_variation_allocations({}) == []


# ---------------------------------------------------------------------------
# AC1 (full pipeline) -- select_experience must actually consult the gate
# ---------------------------------------------------------------------------


def test_select_experience_end_to_end_diverges_packed_vs_anchored_same_visitor():
    """``select_experience`` must read ``experience.version`` and route to the
    anchored builder, not silently default to packed for every version.

    ``gate-visitor-6`` + ``experience_id="gate-e1"`` hashes (via the existing,
    unchanged ``get_bucket_value_for_visitor``) to bucket value 4042 -- derived
    once, offline, by brute-force search over ``gate-visitor-{i}``, not
    hand-waved. At a 25%-total 3-equal-arm allocation this value sits inside
    ONLY the anchored layout's V1 sliver ``[3333.33, 4166.67)``: the packed
    layout's cumulative walk never reaches past 2500 at 25% total, so packed
    must return ``None`` for the identical visitor/value while anchored
    returns ``V1``.
    """
    exp_v12 = _thirds_experience(12, 25, exp_id="gate-e1", key="exp")
    exp_v11 = _thirds_experience(11, 25, exp_id="gate-e1", key="exp")

    result_anchored = select_experience(
        "exp", _snapshot([exp_v12]), visitor_id="gate-visitor-6"
    )
    result_packed = select_experience(
        "exp", _snapshot([exp_v11]), visitor_id="gate-visitor-6"
    )

    assert result_packed is None  # packed 25% thirds never covers value 4042
    assert result_anchored is not None
    assert result_anchored.variation_id == "V1"


# ---------------------------------------------------------------------------
# AC8 -- guard precedence (documents the actual, verified seam behavior)
# ---------------------------------------------------------------------------


def test_select_experience_has_no_stored_or_forced_variation_override_today():
    """AC8 ('a stored decision still wins over both layouts') presupposes a
    stored/sticky/forced-variation branch at this seam. Verified by reading
    ``src/convert_sdk/evaluation/experiences.py`` in full and grepping
    ``src/convert_sdk/`` for ``force_variation`` / ``sticky`` /
    ``stored_variation``: ``select_experience`` is a PURE, STATELESS function
    -- no such branch or keyword exists here. This test documents that
    faithfully instead of fabricating a mechanism that isn't in the code: it
    pins down that no forced-variation keyword exists on this seam today, and
    that the only "guard" a stateless function can offer -- deterministic
    re-derivation of the SAME bucket for the SAME visitor -- continues to hold
    once the anchored path is wired in.
    """
    signature = inspect.signature(select_experience)
    assert "force_variation_id" not in signature.parameters
    assert "forced_variation" not in signature.parameters
    assert "sticky" not in signature.parameters

    # total_pct=100 (full coverage) guarantees a bucketing HIT regardless of
    # this visitor's hash value under EITHER layout -- a partial-coverage
    # allocation would let this determinism check pass trivially on two
    # coincidental misses instead of exercising an actual variation pick.
    exp = _thirds_experience(12, 100, exp_id="stable-e1", key="exp")
    snap = _snapshot([exp])
    first = select_experience("exp", snap, visitor_id="stable-v1")
    second = select_experience("exp", snap, visitor_id="stable-v1")
    assert first is not None and second is not None
    assert first.variation_id == second.variation_id


# ---------------------------------------------------------------------------
# AC9 -- no event/API drift
# ---------------------------------------------------------------------------


def test_select_experience_anchored_result_is_same_typed_shape_as_packed():
    """The anchored path must return the SAME ``ExperienceResult`` shape (or
    ``None``) as packed -- no new fields, no different type, no exception.
    """
    exp_v12 = _thirds_experience(12, 100, exp_id="shape-e1", key="exp")
    result = select_experience(
        "exp", _snapshot([exp_v12]), visitor_id="shape-visitor-1"
    )
    assert result is not None
    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "exp"
    assert result.experience_id == "shape-e1"
    assert result.variation_id in {"O", "V1", "V2"}
    assert result.variation_key is None  # thirds fixture variations carry no "key"


def test_select_experience_anchored_not_bucketed_returns_none_not_exception():
    """A totalWeight<=0 anchored miss returns ``None`` -- never raises."""
    exp = {
        "id": "zero-e1",
        "key": "exp",
        "version": 12,
        "variations": [
            {"id": "a", "traffic_allocation": 0, "status": "running"},
            {"id": "b", "traffic_allocation": 0, "status": "stopped"},
        ],
    }
    result = select_experience("exp", _snapshot([exp]), visitor_id="any-visitor")
    assert result is None
