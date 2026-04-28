"""Direct unit coverage for evaluation/ internals.

These tests target branches not exercised by the JS-parity vectors or the
end-to-end experience/feature suites. They keep the qs-03 95%-on-evaluation/
gate passing without relying on integration paths.
"""

from __future__ import annotations

from typing import Any, Mapping

import pytest

from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.evaluation import bucketing as bucketing_mod
from convert_sdk.evaluation.entity_lookup import get_entity_by_id, get_entity_by_key
from convert_sdk.evaluation.experiences import (
    diagnose_experience,
    evaluate_experience,
    evaluate_experiences,
)
from convert_sdk.evaluation.features import (
    diagnose_feature,
    evaluate_feature,
    evaluate_features,
)
from convert_sdk.evaluation.rules import evaluate_rules
from convert_sdk.evaluation.segments import (
    evaluate_custom_segments,
    normalize_default_segments,
)


def _snapshot(**overrides: Any) -> ConfigSnapshot:
    base: dict[str, Any] = {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "experiences": [],
        "features": [],
        "audiences": [],
        "segments": [],
        "goals": [],
    }
    base.update(overrides)
    return ConfigSnapshot.from_config_data(base)


# ---------------------------------------------------------------------------
# rules.py — full match-type matrix and group dispatch
# ---------------------------------------------------------------------------


class TestEvaluateRulesEmptyOrInvalid:
    def test_returns_true_when_rules_empty(self) -> None:
        assert evaluate_rules({}, {}) is True

    def test_returns_true_when_rules_is_none(self) -> None:
        assert evaluate_rules(None, {}) is True

    def test_returns_false_when_key_missing(self) -> None:
        assert evaluate_rules({"key": "", "value": "x"}, {"x": "x"}) is False

    def test_returns_false_when_attribute_missing(self) -> None:
        assert evaluate_rules({"key": "tier", "value": "premium"}, {}) is False


class TestEvaluateRulesDispatch:
    def test_or_group_any_match(self) -> None:
        rules = {
            "OR": [
                {"key": "tier", "value": "free"},
                {"key": "tier", "value": "premium"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "premium"}) is True

    def test_or_group_with_mapping_input(self) -> None:
        rules = {"OR": {"key": "tier", "value": "premium"}}
        assert evaluate_rules(rules, {"tier": "premium"}) is True

    def test_or_group_no_matches(self) -> None:
        rules = {"OR": [{"key": "tier", "value": "free"}]}
        assert evaluate_rules(rules, {"tier": "premium"}) is False

    def test_or_group_iter_skips_non_mappings(self) -> None:
        rules = {"OR": ["junk", 123, {"key": "tier", "value": "premium"}]}
        assert evaluate_rules(rules, {"tier": "premium"}) is True

    def test_or_group_with_unsupported_type_returns_false(self) -> None:
        rules: Mapping[str, Any] = {"OR": 1234}
        assert evaluate_rules(rules, {"tier": "premium"}) is False

    def test_and_group_all_match(self) -> None:
        rules = {
            "AND": [
                {"key": "tier", "value": "premium"},
                {"key": "country", "value": "US"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "premium", "country": "US"}) is True

    def test_and_group_one_failure_blocks(self) -> None:
        rules = {
            "AND": [
                {"key": "tier", "value": "premium"},
                {"key": "country", "value": "US"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "premium", "country": "DE"}) is False

    def test_or_when_group(self) -> None:
        rules = {
            "OR_WHEN": [
                {"key": "tier", "value": "premium"},
                {"key": "tier", "value": "platinum"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "platinum"}) is True

    def test_or_when_group_no_match(self) -> None:
        rules = {
            "OR_WHEN": [
                {"key": "tier", "value": "premium"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "free"}) is False

    def test_and_with_nested_or_when(self) -> None:
        rules = {
            "AND": [
                {"OR_WHEN": [{"key": "tier", "value": "premium"}]},
                {"key": "country", "value": "US"},
            ]
        }
        assert evaluate_rules(rules, {"tier": "premium", "country": "US"}) is True

    def test_single_rule_passthrough(self) -> None:
        rules = {"key": "tier", "value": "premium"}
        assert evaluate_rules(rules, {"tier": "premium"}) is True


class TestRuleMatchTypes:
    @pytest.mark.parametrize(
        ("match_type", "expected", "actual", "result"),
        [
            ("equals", "premium", "premium", True),
            ("equals", "premium", "free", False),
            ("matches", "10", 10, True),
            # JS aliases ``equalsNumber`` to ``equals`` (stringified
            # case-insensitive compare). Parity-correct behaviour is to
            # compare the string forms — ``str(10) == str("10")`` → True;
            # ``str(10) == str("11")`` → False.
            ("equalsNumber", 10, "10", True),
            ("equalsNumber", 10, "11", False),
            ("less", 5, 1, True),
            ("less", 5, 5, False),
            ("lessEqual", 5, 5, True),
            ("lessEqual", 5, 6, False),
            # JS ``less``/``lessEqual`` return False on type mismatch
            # rather than raising. Coerce-or-False mirrors that.
            ("less", 5, "abc", False),
            ("lessEqual", 5, "abc", False),
        ],
    )
    def test_numeric_and_equality(
        self, match_type: str, expected: Any, actual: Any, result: bool
    ) -> None:
        rules = {"key": "k", "value": expected, "matching": {"match_type": match_type}}
        assert evaluate_rules(rules, {"k": actual}) is result

    def test_contains_in_string(self) -> None:
        rules = {"key": "path", "value": "checkout", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"path": "/checkout/cart"}) is True

    def test_contains_in_sequence(self) -> None:
        rules = {"key": "tags", "value": "vip", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"tags": ["vip", "trial"]}) is True

    def test_contains_returns_false_for_unsupported_actual(self) -> None:
        rules = {"key": "tags", "value": "vip", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"tags": 42}) is False

    def test_contains_returns_false_when_byte_actual(self) -> None:
        rules = {"key": "blob", "value": "v", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"blob": b"raw"}) is False

    def test_starts_with(self) -> None:
        rules = {"key": "path", "value": "/api", "matching": {"match_type": "startsWith"}}
        assert evaluate_rules(rules, {"path": "/api/v2/users"}) is True
        rules2 = {"key": "path", "value": "/api", "matching": {"match_type": "startsWith"}}
        assert evaluate_rules(rules2, {"path": "/web"}) is False

    def test_ends_with(self) -> None:
        rules = {"key": "path", "value": ".html", "matching": {"match_type": "endsWith"}}
        assert evaluate_rules(rules, {"path": "/index.html"}) is True
        rules2 = {"key": "path", "value": ".html", "matching": {"match_type": "endsWith"}}
        assert evaluate_rules(rules2, {"path": "/index.json"}) is False

    def test_regex_matches(self) -> None:
        rules = {"key": "path", "value": r"^/api/v\d+", "matching": {"match_type": "regexMatches"}}
        assert evaluate_rules(rules, {"path": "/api/v2/users"}) is True

    def test_unknown_match_type_returns_false(self) -> None:
        # Parity with JS: unknown match types fall through the
        # comparison switch and return False rather than the prior
        # Python-only ``actual == expected`` shortcut.
        rules = {"key": "k", "value": "x", "matching": {"match_type": "garbage"}}
        assert evaluate_rules(rules, {"k": "x"}) is False

    def test_negated_match(self) -> None:
        rules = {
            "key": "tier",
            "value": "free",
            "matching": {"match_type": "equals", "negated": True},
        }
        assert evaluate_rules(rules, {"tier": "premium"}) is True


class TestRuleNumericCoercion:
    def test_less_handles_numeric_strings(self) -> None:
        # JS coerces numeric-looking strings via ``isNumeric`` before
        # comparing with ``less`` / ``lessEqual``.
        rules = {"key": "v", "value": "10", "matching": {"match_type": "less"}}
        assert evaluate_rules(rules, {"v": "5"}) is True
        rules2 = {"key": "v", "value": "10", "matching": {"match_type": "less"}}
        assert evaluate_rules(rules2, {"v": "15"}) is False

    def test_less_returns_false_on_non_numeric_string(self) -> None:
        # JS returns false when one side is non-numeric rather than
        # raising — mirror that to avoid crashing the evaluator.
        rules = {"key": "v", "value": 10, "matching": {"match_type": "less"}}
        assert evaluate_rules(rules, {"v": "abc"}) is False


# ---------------------------------------------------------------------------
# entity_lookup.py — error paths and variation traversal
# ---------------------------------------------------------------------------


class TestEntityLookupErrors:
    def test_normalize_entity_type_rejects_empty(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(ValueError, match="entity_type is required"):
            get_entity_by_key(snapshot, "", "anything")

    def test_normalize_entity_type_rejects_non_string(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(ValueError, match="entity_type is required"):
            get_entity_by_key(snapshot, None, "anything")  # type: ignore[arg-type]

    def test_normalize_lookup_value_rejects_empty(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(ValueError, match="key is required"):
            get_entity_by_key(snapshot, "experience", "  ")

    def test_normalize_lookup_value_id_rejects_empty(self) -> None:
        snapshot = _snapshot()
        with pytest.raises(ValueError, match="entity_id is required"):
            get_entity_by_id(snapshot, "experience", "")

    def test_unknown_entity_type_returns_none(self) -> None:
        snapshot = _snapshot()
        assert get_entity_by_key(snapshot, "unknown", "x") is None
        assert get_entity_by_id(snapshot, "unknown", "x") is None

    def test_experiment_alias_normalized(self) -> None:
        snapshot = _snapshot(
            experiences=[{"id": "e1", "key": "checkout", "variations": []}]
        )
        assert get_entity_by_key(snapshot, "experiments", "checkout") is not None


class TestEntityLookupVariations:
    def test_variation_lookup_by_key_finds_match(self) -> None:
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [{"id": "v1", "key": "control"}],
                }
            ]
        )
        result = get_entity_by_key(snapshot, "variation", "control")
        assert result is not None
        assert result["id"] == "v1"

    def test_variation_lookup_by_id_finds_match(self) -> None:
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [{"id": "v1", "key": "control"}],
                }
            ]
        )
        result = get_entity_by_id(snapshot, "variation", "v1")
        assert result is not None
        assert result["key"] == "control"

    def test_variation_lookup_returns_none_when_missing(self) -> None:
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [{"id": "v1", "key": "control"}],
                }
            ]
        )
        assert get_entity_by_key(snapshot, "variation", "missing") is None
        assert get_entity_by_id(snapshot, "variation", "missing") is None

    def test_variation_lookup_with_no_experiences(self) -> None:
        snapshot = _snapshot()
        assert get_entity_by_key(snapshot, "variation", "anything") is None
        assert get_entity_by_id(snapshot, "variation", "anything") is None


# ---------------------------------------------------------------------------
# segments.py — empty inputs, duplicates, type errors
# ---------------------------------------------------------------------------


class TestSegments:
    def test_evaluate_custom_segments_skips_blank_keys(self) -> None:
        snapshot = _snapshot(
            segments=[{"id": "s1", "key": "vip", "rules": {"key": "tier", "value": "premium"}}]
        )
        result = evaluate_custom_segments(
            snapshot,
            segment_keys=["", "  ", "vip"],
            attributes={"tier": "premium"},
        )
        assert result == ("vip",)

    def test_evaluate_custom_segments_skips_duplicates(self) -> None:
        snapshot = _snapshot(
            segments=[{"id": "s1", "key": "vip", "rules": {"key": "tier", "value": "premium"}}]
        )
        result = evaluate_custom_segments(
            snapshot,
            segment_keys=["vip", "vip"],
            attributes={"tier": "premium"},
        )
        assert result == ("vip",)

    def test_evaluate_custom_segments_unknown_segment_returns_empty(self) -> None:
        snapshot = _snapshot()
        assert evaluate_custom_segments(snapshot, segment_keys=["unknown"], attributes={}) == ()

    def test_normalize_default_segments_rejects_string(self) -> None:
        with pytest.raises(TypeError):
            normalize_default_segments("not-a-sequence")  # type: ignore[arg-type]

    def test_normalize_default_segments_rejects_non_sequence(self) -> None:
        with pytest.raises(TypeError):
            normalize_default_segments(42)  # type: ignore[arg-type]

    def test_normalize_default_segments_dedupes_and_strips(self) -> None:
        assert normalize_default_segments([" vip ", "free", "vip", ""]) == ("vip", "free")


# ---------------------------------------------------------------------------
# experiences.py — diagnose paths, audience modes, environment variants
# ---------------------------------------------------------------------------


def _experience_snapshot(**experience_overrides: Any) -> ConfigSnapshot:
    experience: dict[str, Any] = {
        "id": "e1",
        "key": "checkout",
        "status": "running",
        "variations": [
            {
                "id": "v1",
                "key": "control",
                "status": "running",
                "traffic_allocation": 100.0,
            }
        ],
    }
    experience.update(experience_overrides)
    return _snapshot(experiences=[experience])


class TestDiagnoseExperience:
    def test_experience_not_found(self) -> None:
        snapshot = _snapshot()
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="missing",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.resolved is False
        assert diagnostic.reason == "experience_not_found"

    def test_experience_archived(self) -> None:
        # JS rejects experiences listed in ``archived_experiences``;
        # the parity-correct gating mechanism in Python is the same
        # list, not a Python-only ``experience.status`` filter (which
        # was removed for parity).
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
            archived_experiences=["e1"],
        )
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "experience_archived"

    def test_environment_mismatch(self) -> None:
        # JS reads singular ``experience.environment`` and rejects when
        # the request environment differs.
        snapshot = _experience_snapshot(environment="staging")
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            environment="production",
        )
        assert diagnostic.reason == "environment_mismatch"

    def test_environment_unset_means_any_environment(self) -> None:
        # JS skips the environment check when ``experience.environment``
        # is unset — the request environment value is ignored.
        snapshot = _experience_snapshot()
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            environment="production",
        )
        assert diagnostic.resolved is True

    def test_location_mismatch(self) -> None:
        snapshot = _experience_snapshot(
            site_area={"key": "path", "value": "/checkout"},
        )
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={"path": "/home"},
        )
        assert diagnostic.reason == "location_mismatch"

    def test_audience_mismatch(self) -> None:
        snapshot = _snapshot(
            audiences=[
                {
                    "id": "a1",
                    "key": "premium-only",
                    "status": "running",
                    "rules": {"key": "tier", "value": "premium"},
                }
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "audiences": ["a1"],
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
        )
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={"tier": "free"},
            location_attributes={},
        )
        assert diagnostic.reason == "audience_mismatch"

    def test_no_variations(self) -> None:
        snapshot = _experience_snapshot(variations=[])
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "no_variations"

    def test_no_variation_selected_when_traffic_zero(self) -> None:
        snapshot = _experience_snapshot(
            variations=[
                {"id": "v1", "key": "control", "status": "running", "traffic_allocation": 0.0}
            ]
        )
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "no_variation_selected"

    def test_resolved_diagnostic(self) -> None:
        snapshot = _experience_snapshot()
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.resolved is True
        assert diagnostic.reason == "resolved"


class TestExperienceEvaluation:
    def test_evaluate_experience_returns_none_when_missing(self) -> None:
        snapshot = _snapshot()
        result = evaluate_experience(
            snapshot,
            experience_key="missing",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is None

    def test_evaluate_experiences_skips_keyless_entries(self) -> None:
        snapshot = _snapshot(
            experiences=[
                {"id": "e0", "status": "running", "variations": []},
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                },
            ]
        )
        results = evaluate_experiences(
            snapshot,
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert [result.experience_key for result in results] == ["checkout"]

    def test_audiences_match_all_mode(self) -> None:
        snapshot = _snapshot(
            audiences=[
                {
                    "id": "a1",
                    "status": "running",
                    "rules": {"key": "tier", "value": "premium"},
                },
                {
                    "id": "a2",
                    "status": "running",
                    "rules": {"key": "country", "value": "US"},
                },
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "audiences": ["a1", "a2"],
                    "settings": {"matching_options": {"audiences": "all"}},
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
        )

        match = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={"tier": "premium", "country": "US"},
            location_attributes={},
        )
        assert match is not None

        miss = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={"tier": "premium", "country": "DE"},
            location_attributes={},
        )
        assert miss is None

    def test_audiences_match_treats_unknown_audience_as_false(self) -> None:
        snapshot = _snapshot(
            audiences=[],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "audiences": ["missing"],
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is None

    def test_audience_status_field_is_ignored_for_parity_with_js(self) -> None:
        # JS does not filter audiences by an opaque status field; the
        # rules are evaluated regardless. An empty rules mapping means
        # "all visitors qualify", so a paused-but-empty-rules audience
        # admits everyone — matching JS behaviour.
        snapshot = _snapshot(
            audiences=[{"id": "a1", "status": "paused", "rules": {}}],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "audiences": ["a1"],
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        # Empty rules → audience qualifies → experience selects v1.
        assert result is not None
        assert result.variation_key == "control"

    def test_bucketing_options_pulled_from_snapshot(self) -> None:
        snapshot = _snapshot(
            bucketing={"hash_seed": 42, "max_traffic": 50},
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
        )
        # The diagnostic path reads bucket_value via _bucketing_options.
        diagnostic = diagnose_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        # Result is either resolved or no_variation_selected depending on hash;
        # both paths exercise _bucketing_options without raising.
        assert diagnostic.reason in {"resolved", "no_variation_selected"}


# ---------------------------------------------------------------------------
# features.py — diagnose paths and variable casting
# ---------------------------------------------------------------------------


def _feature_snapshot() -> ConfigSnapshot:
    return _snapshot(
        features=[
            {
                "id": "f1",
                "key": "banner",
                "variables": [
                    {"key": "headline", "type": "string"},
                    {"key": "max_views", "type": "integer"},
                    {"key": "enabled", "type": "boolean"},
                    {"key": "config", "type": "json"},
                ],
            }
        ],
        experiences=[
            {
                "id": "e1",
                "key": "checkout",
                "status": "running",
                "variations": [
                    {
                        "id": "v1",
                        "key": "control",
                        "status": "running",
                        "traffic_allocation": 100.0,
                        "changes": [
                            {
                                "type": "fullStackFeature",
                                "data": {
                                    "feature_id": "f1",
                                    "variables_data": {
                                        "headline": 123,
                                        "max_views": "10",
                                        "enabled": "yes",
                                        "config": '{"x": 1}',
                                    },
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    )


class TestEvaluateFeature:
    def test_returns_none_when_no_match(self) -> None:
        snapshot = _snapshot()
        result = evaluate_feature(
            snapshot,
            feature_key="missing",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is None

    def test_returns_first_match(self) -> None:
        # Default ``type_cast=False`` for parity with JS — variables are
        # surfaced verbatim from the config without coercion.
        snapshot = _feature_snapshot()
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is not None
        assert result.feature_key == "banner"
        # Raw values from the config — no Python-only coercion.
        assert result.variables["headline"] == 123
        assert result.variables["max_views"] == "10"
        assert result.variables["enabled"] == "yes"

    def test_type_cast_opt_in_coerces_variable_values(self) -> None:
        snapshot = _feature_snapshot()
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            type_cast=True,
        )
        assert result is not None
        assert result.variables["max_views"] == 10
        assert result.variables["enabled"] is True
        assert result.variables["config"] == {"x": 1}


class TestCastFeatureValueBranches:
    @pytest.mark.parametrize(
        ("variables_data", "key", "expected"),
        [
            ({"enabled": True}, "enabled", True),
            ({"enabled": "1"}, "enabled", True),
            ({"enabled": "off"}, "enabled", False),
            ({"enabled": 1}, "enabled", True),
            ({"enabled": 0}, "enabled", False),
            ({"max_views": "5"}, "max_views", 5),
            ({"max_views": 5}, "max_views", 5),
            ({"headline": 42}, "headline", "42"),
            ({"config": '["a", "b"]'}, "config", ("a", "b")),
        ],
    )
    def test_type_branches(
        self,
        variables_data: Mapping[str, Any],
        key: str,
        expected: Any,
    ) -> None:
        snapshot = _snapshot(
            features=[
                {
                    "id": "f1",
                    "key": "banner",
                    "variables": [
                        {"key": "enabled", "type": "boolean"},
                        {"key": "max_views", "type": "integer"},
                        {"key": "headline", "type": "string"},
                        {"key": "config", "type": "json"},
                    ],
                }
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {
                                    "type": "fullStackFeature",
                                    "data": {
                                        "feature_id": "f1",
                                        "variables_data": variables_data,
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        )
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            type_cast=True,
        )
        assert result is not None
        assert result.variables[key] == expected

    def test_invalid_json_string_returns_raw(self) -> None:
        snapshot = _snapshot(
            features=[
                {
                    "id": "f1",
                    "key": "banner",
                    "variables": [{"key": "config", "type": "json"}],
                }
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {
                                    "type": "fullStackFeature",
                                    "data": {
                                        "feature_id": "f1",
                                        "variables_data": {"config": "not-json{"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        )
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            type_cast=True,
        )
        assert result is not None
        assert result.variables["config"] == "not-json{"


class TestEvaluateFeaturesGuards:
    def test_skips_non_feature_changes(self) -> None:
        snapshot = _snapshot(
            features=[{"id": "f1", "key": "banner", "variables": []}],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {"type": "domChange", "data": {"feature_id": "f1"}},
                                {
                                    "type": "fullStackFeature",
                                    "data": {
                                        "feature_id": "f1",
                                        "variables_data": {},
                                    },
                                },
                            ],
                        }
                    ],
                }
            ],
        )
        results = evaluate_features(
            snapshot,
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert [result.feature_key for result in results] == ["banner"]

    def test_skips_changes_with_invalid_data(self) -> None:
        snapshot = _snapshot(
            features=[{"id": "f1", "key": "banner", "variables": []}],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {"type": "fullStackFeature", "data": "not-mapping"},
                                {"type": "fullStackFeature", "data": {"feature_id": ""}},
                                {
                                    "type": "fullStackFeature",
                                    "data": {"feature_id": "missing"},
                                },
                            ],
                        }
                    ],
                }
            ],
        )
        results = evaluate_features(
            snapshot,
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert results == []


class TestDiagnoseFeature:
    def test_feature_not_found(self) -> None:
        snapshot = _snapshot()
        diagnostic = diagnose_feature(
            snapshot,
            feature_key="missing",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "feature_not_found"

    def test_feature_no_applicable_experience(self) -> None:
        snapshot = _snapshot(
            features=[{"id": "f1", "key": "banner", "variables": []}],
        )
        diagnostic = diagnose_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "no_applicable_experience"

    def test_feature_not_in_selected_variations(self) -> None:
        snapshot = _snapshot(
            features=[{"id": "f1", "key": "banner", "variables": []}],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [],
                        }
                    ],
                }
            ],
        )
        diagnostic = diagnose_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "feature_not_in_selected_variations"

    def test_feature_resolved(self) -> None:
        snapshot = _feature_snapshot()
        diagnostic = diagnose_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert diagnostic.reason == "resolved"
        assert diagnostic.result is not None


# ---------------------------------------------------------------------------
# bucketing.py — variation status filter branch
# ---------------------------------------------------------------------------


class TestBucketingStatusFilter:
    def test_skips_variations_with_unknown_status(self) -> None:
        # The variation list contains a valid running variation and one with
        # an unsupported status; the filter must drop the latter without
        # raising and still allocate to the running variation.
        variations = (
            {"id": "v0", "key": "junk", "status": "archived", "traffic_allocation": 100.0},
            {"id": "v1", "key": "control", "status": "running", "traffic_allocation": 100.0},
        )
        bucketed = bucketing_mod.select_variation(
            variations,
            visitor_id="v1",
            experience_id="e1",
            bucketing_config=None,
        )
        assert bucketed is not None
        variation, _ = bucketed
        assert variation["key"] == "control"

    def test_missing_traffic_allocation_defaults_to_full_traffic(self) -> None:
        # JS treats a missing ``traffic_allocation`` as 100% (parity
        # behaviour). With the JS-aligned fix, a single variation with
        # no allocation receives the full bucket range.
        variations = (
            {"id": "v1", "key": "control", "status": "running"},
        )
        bucketed = bucketing_mod.select_variation(
            variations,
            visitor_id="visitor-x",
            experience_id="e1",
            bucketing_config=None,
        )
        assert bucketed is not None
        variation, _ = bucketed
        assert variation["key"] == "control"

    def test_non_numeric_traffic_allocation_is_treated_as_zero(self) -> None:
        # JS ``Number()`` coerces non-numeric to NaN and the comparison
        # returns false (the variation is skipped). Python mirrors with
        # 0%, so this single-variation experience produces no match.
        variations = (
            {
                "id": "v1",
                "key": "control",
                "status": "running",
                "traffic_allocation": "not-a-number",
            },
        )
        bucketed = bucketing_mod.select_variation(
            variations,
            visitor_id="visitor-x",
            experience_id="e1",
            bucketing_config=None,
        )
        assert bucketed is None


# ---------------------------------------------------------------------------
# rules.py — JS-parity coverage for the new operator paths
# ---------------------------------------------------------------------------


class TestRuleParityBranches:
    def test_equals_array_value_uses_indexof_semantics(self) -> None:
        # JS ``equals`` for an array value returns ``testAgainst in array``.
        rules = {"key": "tags", "value": "vip", "matching": {"match_type": "equals"}}
        assert evaluate_rules(rules, {"tags": ["free", "vip", "trial"]}) is True
        assert evaluate_rules(rules, {"tags": ["free", "trial"]}) is False

    def test_equals_array_falls_back_to_string_form(self) -> None:
        # JS ``equals`` short-circuits on identity match; Python's
        # parity layer also accepts a stringified-element match so a
        # numeric ``testAgainst`` finds its string twin in the array.
        rules = {"key": "ids", "value": 42, "matching": {"match_type": "equals"}}
        assert evaluate_rules(rules, {"ids": ["1", "42", "100"]}) is True

    def test_equals_non_empty_mapping_checks_keys(self) -> None:
        # JS ``equals`` for a mapping returns ``str(testAgainst) in keys``.
        rules = {
            "key": "feature_flags",
            "value": "checkout",
            "matching": {"match_type": "equals"},
        }
        assert evaluate_rules(rules, {"feature_flags": {"checkout": True}}) is True
        assert evaluate_rules(rules, {"feature_flags": {"home": True}}) is False

    def test_equals_is_case_insensitive(self) -> None:
        rules = {"key": "tier", "value": "Premium", "matching": {"match_type": "equals"}}
        assert evaluate_rules(rules, {"tier": "PREMIUM"}) is True

    def test_contains_lowercases_both_sides(self) -> None:
        rules = {"key": "path", "value": "CHECKOUT", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"path": "/Checkout/cart"}) is True

    def test_contains_returns_true_for_whitespace_only_test_against(self) -> None:
        # JS ``contains`` short-circuits when ``testAgainst`` is empty
        # or whitespace-only after trimming.
        rules = {"key": "path", "value": "   ", "matching": {"match_type": "contains"}}
        assert evaluate_rules(rules, {"path": "/anything"}) is True

    def test_starts_and_ends_with_lowercase_both_sides(self) -> None:
        starts = {"key": "path", "value": "/API", "matching": {"match_type": "startsWith"}}
        ends = {"key": "path", "value": ".HTML", "matching": {"match_type": "endsWith"}}
        assert evaluate_rules(starts, {"path": "/api/v2"}) is True
        assert evaluate_rules(ends, {"path": "/index.html"}) is True

    def test_regex_matches_is_case_insensitive(self) -> None:
        rules = {
            "key": "path",
            "value": r"^/API/V\d+",
            "matching": {"match_type": "regexMatches"},
        }
        assert evaluate_rules(rules, {"path": "/api/v2/users"}) is True

    def test_regex_matches_returns_false_on_malformed_pattern(self) -> None:
        # JS would throw at ``new RegExp`` time and the rule manager
        # would catch upstream. Python mirrors with safe-false here so
        # one bad rule does not crash the whole evaluation.
        rules = {
            "key": "path",
            "value": "[unterminated",
            "matching": {"match_type": "regexMatches"},
        }
        assert evaluate_rules(rules, {"path": "/anything"}) is False

    def test_is_in_splits_on_pipe_and_lowercases_test_against(self) -> None:
        rules = {
            "key": "country",
            "value": "us|UK|de",
            "matching": {"match_type": "isIn"},
        }
        assert evaluate_rules(rules, {"country": "uk"}) is True
        assert evaluate_rules(rules, {"country": "FR"}) is False

    def test_is_in_accepts_list_test_against(self) -> None:
        rules = {
            "key": "country",
            "value": ["us", "UK"],
            "matching": {"match_type": "isIn"},
        }
        assert evaluate_rules(rules, {"country": "uk"}) is True

    def test_is_in_with_unsupported_test_against_returns_false(self) -> None:
        # ``test_against`` is neither list/tuple nor string → no
        # candidates → no match.
        rules = {"key": "country", "value": 42, "matching": {"match_type": "isIn"}}
        assert evaluate_rules(rules, {"country": "fr"}) is False

    def test_coerce_numeric_handles_empty_and_non_numeric_strings(self) -> None:
        # ``less`` must return False when either side is non-coercible.
        empty_rule = {"key": "v", "value": 5, "matching": {"match_type": "less"}}
        assert evaluate_rules(empty_rule, {"v": "   "}) is False
        non_numeric = {"key": "v", "value": 5, "matching": {"match_type": "lessEqual"}}
        assert evaluate_rules(non_numeric, {"v": "abc"}) is False

    def test_coerce_numeric_handles_unsupported_type(self) -> None:
        # An object value falls through ``_coerce_numeric`` to ``None``
        # and ``less`` returns False.
        rule = {"key": "v", "value": 5, "matching": {"match_type": "less"}}
        assert evaluate_rules(rule, {"v": {"unexpected": "shape"}}) is False


# ---------------------------------------------------------------------------
# experiences.py — archived_experiences support (singular + mapping forms)
# ---------------------------------------------------------------------------


class TestArchivedExperiences:
    def test_archived_list_form_rejects_listed_id(self) -> None:
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
            archived_experiences=["e1"],
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is None

    def test_archived_mapping_form_uses_values(self) -> None:
        # JS ``getEntitiesList`` accepts both list and dict shapes; the
        # Python parity helper iterates ``.values()`` for mappings.
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
            archived_experiences={"by-id": "e1"},
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is None

    def test_malformed_archived_field_is_ignored(self) -> None:
        # An int (non-iterable) for ``archived_experiences`` should not
        # crash evaluation — the helper returns False and bucketing
        # proceeds normally.
        snapshot = _snapshot(
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
            archived_experiences=42,
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is not None
        assert result.variation_key == "control"

    def test_archived_check_skipped_when_experience_has_no_id(self) -> None:
        # An experience with no ``id`` cannot match the archived list,
        # so the helper short-circuits to False.
        snapshot = _snapshot(
            experiences=[
                {
                    "key": "checkout",
                    "variations": [
                        {"id": "v1", "key": "control", "traffic_allocation": 100.0}
                    ],
                }
            ],
            archived_experiences=["whatever"],
        )
        result = evaluate_experience(
            snapshot,
            experience_key="checkout",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
        )
        assert result is not None


# ---------------------------------------------------------------------------
# features.py — type_cast safe-fallback paths
# ---------------------------------------------------------------------------


class TestCastFeatureSafeFallback:
    def test_invalid_integer_returns_frozen_original(self) -> None:
        # ``int("1.5")`` raises ``ValueError``; with the safe fallback
        # the variable is surfaced as the frozen original instead of
        # crashing the whole ``evaluate_features`` call.
        snapshot = _snapshot(
            features=[
                {
                    "id": "f1",
                    "key": "banner",
                    "variables": [{"key": "max_views", "type": "integer"}],
                }
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {
                                    "type": "fullStackFeature",
                                    "data": {
                                        "feature_id": "f1",
                                        "variables_data": {"max_views": "1.5"},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        )
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            type_cast=True,
        )
        assert result is not None
        # Falls back to the frozen original string rather than raising.
        assert result.variables["max_views"] == "1.5"

    def test_string_cast_handles_none(self) -> None:
        snapshot = _snapshot(
            features=[
                {
                    "id": "f1",
                    "key": "banner",
                    "variables": [{"key": "headline", "type": "string"}],
                }
            ],
            experiences=[
                {
                    "id": "e1",
                    "key": "checkout",
                    "status": "running",
                    "variations": [
                        {
                            "id": "v1",
                            "key": "control",
                            "status": "running",
                            "traffic_allocation": 100.0,
                            "changes": [
                                {
                                    "type": "fullStackFeature",
                                    "data": {
                                        "feature_id": "f1",
                                        "variables_data": {"headline": None},
                                    },
                                }
                            ],
                        }
                    ],
                }
            ],
        )
        result = evaluate_feature(
            snapshot,
            feature_key="banner",
            visitor_id="v1",
            visitor_attributes={},
            location_attributes={},
            type_cast=True,
        )
        assert result is not None
        assert result.variables["headline"] == ""
