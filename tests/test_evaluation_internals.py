"""Direct unit tests for evaluation/ internal helpers (Story 5.1 coverage gate).

These tests exercise the small pure helper functions inside the ``evaluation/``
package directly, rather than only through the higher-level ``select_experience``
/ ``resolve_feature`` / ``select_custom_segments`` surfaces. They exist to satisfy
the qs-03 coverage gate's 95%-on-``evaluation/`` floor: the integration-style
suites cover the happy paths, but several defensive branches (malformed-config
fallbacks, type-cast edge cases, surrogate-pair hashing) are only reachable by
feeding the helpers crafted inputs. No production code is changed by this file —
it is pure additive test surface targeting the previously-uncovered lines.
"""

from __future__ import annotations

import pytest

from convert_sdk.evaluation import bucketing, experiences, features, rules, segments


# ---------------------------------------------------------------------------
# bucketing._utf16_code_units — surrogate-pair (astral) handling
# ---------------------------------------------------------------------------


def test_utf16_code_units_bmp_char_is_single_unit():
    # A BMP character maps to one code unit equal to its code point.
    assert bucketing._utf16_code_units("A") == [0x41]


def test_utf16_code_units_astral_char_splits_into_surrogate_pair():
    # U+1F600 (😀) is outside the BMP and must split into a high/low surrogate
    # pair to match JS charCodeAt semantics (covers the >0xFFFF branch).
    units = bucketing._utf16_code_units("\U0001F600")
    assert units == [0xD83D, 0xDE00]
    assert all(0xD800 <= u <= 0xDFFF for u in units)


def test_utf16_code_units_mixed_string():
    units = bucketing._utf16_code_units("a\U0001F600b")
    assert units == [0x61, 0xD83D, 0xDE00, 0x62]


# ---------------------------------------------------------------------------
# experiences._is_running / _has_traffic / _build_buckets / _find_variation
# ---------------------------------------------------------------------------


def test_is_running_defaults_true_when_no_status():
    assert experiences._is_running({}) is True


def test_is_running_true_for_running_status_false_otherwise():
    assert experiences._is_running({"status": "running"}) is True
    assert experiences._is_running({"status": "RUNNING"}) is True
    assert experiences._is_running({"status": "paused"}) is False


def test_has_traffic_no_allocation_means_full_traffic():
    assert experiences._has_traffic({}) is True


def test_has_traffic_non_numeric_allocation_defaults_true():
    assert experiences._has_traffic({"traffic_allocation": "abc"}) is True


def test_has_traffic_nan_allocation_defaults_true():
    assert experiences._has_traffic({"traffic_allocation": float("nan")}) is True


def test_has_traffic_zero_is_false_positive_is_true():
    assert experiences._has_traffic({"traffic_allocation": 0}) is False
    assert experiences._has_traffic({"traffic_allocation": 50}) is True


def test_build_buckets_skips_non_running_no_traffic_and_idless():
    experience = {
        "variations": [
            {"id": "v1", "status": "running", "traffic_allocation": 100},
            {"id": "v2", "status": "paused", "traffic_allocation": 100},
            {"id": "v3", "status": "running", "traffic_allocation": 0},
            {"status": "running", "traffic_allocation": 100},  # no id -> skip
        ]
    }
    buckets = experiences._build_buckets(experience)
    assert set(buckets) == {"v1"}
    assert buckets["v1"] == 100.0


def test_build_buckets_nan_allocation_falls_back_to_hundred():
    experience = {
        "variations": [
            {"id": "v1", "status": "running", "traffic_allocation": float("nan")},
        ]
    }
    buckets = experiences._build_buckets(experience)
    assert buckets["v1"] == 100.0


def test_build_buckets_empty_when_no_variations():
    assert experiences._build_buckets({}) == {}


def test_find_variation_hit_and_miss():
    experience = {"variations": [{"id": "v1"}, {"id": "v2"}]}
    assert experiences._find_variation(experience, "v2") == {"id": "v2"}
    assert experiences._find_variation(experience, "missing") is None
    assert experiences._find_variation({}, "v1") is None


# ---------------------------------------------------------------------------
# experiences.select_experience — defensive miss paths
# ---------------------------------------------------------------------------


class _FakeSnapshot:
    """Minimal snapshot stub exposing only what the helpers read."""

    def __init__(self, experiences_by_key=None, experiences_list=None):
        self._by_key = experiences_by_key or {}
        self.experiences = experiences_list or list((experiences_by_key or {}).values())

    def get_experience_by_key(self, key):
        return self._by_key.get(key)


def test_select_experience_empty_visitor_id_is_none():
    snap = _FakeSnapshot({"exp": {"id": "e1"}})
    assert experiences.select_experience("exp", snap, visitor_id="") is None


def test_select_experience_missing_experience_is_none():
    snap = _FakeSnapshot({})
    assert experiences.select_experience("nope", snap, visitor_id="visitor-1") is None


def test_select_experience_experience_without_id_is_none():
    # Qualifies (no audiences/site_area) but has no id -> miss.
    snap = _FakeSnapshot({"exp": {"variations": [{"id": "v1", "status": "running"}]}})
    assert experiences.select_experience("exp", snap, visitor_id="visitor-1") is None


def test_select_experience_no_active_buckets_is_none():
    snap = _FakeSnapshot(
        {"exp": {"id": "e1", "variations": [{"id": "v1", "traffic_allocation": 0}]}}
    )
    assert experiences.select_experience("exp", snap, visitor_id="visitor-1") is None


def test_select_experience_resolves_single_full_traffic_variation():
    snap = _FakeSnapshot(
        {
            "exp": {
                "id": "e1",
                "key": "exp",
                "variations": [
                    {"id": "v1", "key": "control", "traffic_allocation": 100}
                ],
            }
        }
    )
    result = experiences.select_experience("exp", snap, visitor_id="visitor-1")
    assert result is not None
    assert result.experience_id == "e1"
    assert result.variation_id == "v1"
    assert result.variation_key == "control"


# ---------------------------------------------------------------------------
# features._cast_value — per-type casting + best-effort fallbacks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "declared", "expected"),
    [
        ("true", "boolean", True),
        ("0", "boolean", False),
        (True, "boolean", True),
        ("42", "integer", 42),
        ("3.5", "float", 3.5),
        (10, "string", "10"),
        ('{"a": 1}', "json", {"a": 1}),
        ({"a": 1}, "json", {"a": 1}),
        ("passthrough", None, "passthrough"),
        ("unknown-type-passes-through", "weird", "unknown-type-passes-through"),
    ],
)
def test_cast_value_variants(raw, declared, expected):
    assert features._cast_value(raw, declared) == expected


def test_cast_value_uncastable_returns_input_unchanged():
    # int("abc") raises ValueError -> best-effort returns the original value.
    assert features._cast_value("abc", "integer") == "abc"


def test_is_fullstack_feature_change_matches_type():
    assert features._is_fullstack_feature_change({"type": "fullStackFeature"}) is True
    assert features._is_fullstack_feature_change({"type": "visual"}) is False
    assert features._is_fullstack_feature_change({}) is False


def test_feature_change_for_finds_matching_feature_id():
    variation = {
        "changes": [
            {"type": "visual"},  # skipped (not a fullstack change)
            {"type": "fullStackFeature", "data": {"feature_id": "other"}},
            {"type": "fullStackFeature", "data": {"feature_id": "f1", "x": 1}},
        ]
    }
    assert features._feature_change_for(variation, "f1") == {"feature_id": "f1", "x": 1}
    assert features._feature_change_for(variation, "missing") is None
    assert features._feature_change_for({}, "f1") is None


def test_variable_types_and_cast_variables():
    feature = {
        "variables": [
            {"key": "flag", "type": "boolean"},
            {"key": "count", "type": "integer"},
            {"key": "skip"},  # no type -> excluded from type map
        ]
    }
    assert features._variable_types(feature) == {"flag": "boolean", "count": "integer"}
    cast = features._cast_variables({"flag": "true", "count": "7", "raw": "x"}, feature)
    assert cast == {"flag": True, "count": 7, "raw": "x"}


# ---------------------------------------------------------------------------
# rules comparators — numeric coercion + comparison branches
# ---------------------------------------------------------------------------


def test_is_numeric_branches():
    assert rules._is_numeric(True) is False  # bool is not treated as numeric
    assert rules._is_numeric(5) is True
    assert rules._is_numeric(2.5) is True
    assert rules._is_numeric("1,000") is True
    assert rules._is_numeric("abc") is False
    assert rules._is_numeric(None) is False


def test_to_number_handles_int_float_and_comma_string():
    assert rules._to_number(3) == 3.0
    assert rules._to_number(2.5) == 2.5
    assert rules._to_number("1,234") == 1234.0


def test_equals_list_membership_mapping_keys_and_string():
    assert rules._equals([1, 2, 3], 2) is True
    assert rules._equals({"a": 1, "b": 2}, "a") is True
    assert rules._equals({"a": 1}, "z") is False
    assert rules._equals("Hello", "hello") is True


def test_less_equal_type_mismatch_is_false():
    # Numeric vs non-numeric coerces only the numeric side, leaving a type
    # mismatch that the comparator rejects rather than raising.
    assert rules._less_equal(5, "not-a-number") is False


def test_less_equal_numeric_true_and_false():
    assert rules._less_equal(3, 5) is True
    assert rules._less_equal(5, 3) is False


def test_exists_and_not_exists():
    assert rules._exists("x", None) is True
    assert rules._exists("", None) is False
    assert rules._exists(None, None) is False
    assert rules._not_exists(None, None) is True
    assert rules._not_exists("", None) is True
    assert rules._not_exists("x", None) is False


def test_process_rule_item_unknown_match_type_is_false():
    assert rules._process_rule_item({"k": "v"}, {"matching": {"match_type": "??"}}) is False


def test_process_rule_item_missing_match_type_is_false():
    assert rules._process_rule_item({"k": "v"}, {"matching": {}}) is False


def test_process_rule_item_absent_key_non_existence_op_is_false():
    rule = {"key": "missing", "matching": {"match_type": "equals"}, "value": "x"}
    assert rules._process_rule_item({"present": "y"}, rule) is False


def test_process_rule_item_negated_inverts_result():
    rule = {"key": "k", "matching": {"match_type": "equals", "negated": True}, "value": "v"}
    # k == v normally True; negated -> False.
    assert rules._process_rule_item({"k": "v"}, rule) is False


# ---------------------------------------------------------------------------
# segments — duplicate-id skip branch
# ---------------------------------------------------------------------------


class _SegSnapshot:
    """Minimal snapshot stub exposing only the ``segments`` collection."""

    def __init__(self, segments_list):
        self.segments = segments_list


def test_select_custom_segments_skips_resolved_segment_without_id():
    # A rule-less segment resolves and matches, but carries no ``id`` -> it is
    # skipped at the id-extraction guard (covers the raw_id is None branch).
    snap = _SegSnapshot([{"key": "seg-no-id"}])
    matched = segments.select_custom_segments(snap, ["seg-no-id"], None)
    assert matched == []


def test_select_custom_segments_skips_existing_and_duplicate_ids():
    # An id already in existing_ids is not re-added; a repeated resolved id is
    # recorded only once (covers the duplicate-id continue branch).
    snap = _SegSnapshot(
        [
            {"key": "a", "id": "seg-1"},
            {"key": "b", "id": "seg-2"},
        ]
    )
    matched = segments.select_custom_segments(
        snap, ["a", "b", "a"], None, existing_ids=["seg-2"]
    )
    assert matched == ["seg-1"]


def test_select_custom_segments_unknown_key_is_no_match():
    snap = _SegSnapshot([{"key": "a", "id": "seg-1"}])
    assert segments.select_custom_segments(snap, ["missing"], None) == []
