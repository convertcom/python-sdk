"""RED tests for the `experience_keys` filter on feature resolution.

Locks in a NEW keyword-only ``experience_keys: Optional[Sequence[str]] = None``
parameter on the Python SDK's feature entry points: the module-level
``resolve_feature`` / ``resolve_features`` (``evaluation/features.py``) and the
public ``Context.run_feature`` / ``Context.run_features`` /
``Context.diagnose_feature``. None of these accept the keyword today, so every
test below fails with a ``TypeError: unexpected keyword argument
'experience_keys'`` until the capability ships.

Semantics locked in here (not yet implemented):

* narrowing which experiences are considered for a feature changes
  PRECEDENCE, not just post-hoc filtering (two experiences racing for the
  same feature);
* an excluded feature is OMITTED, never padded with ``FeatureStatus.DISABLED``;
* CONFIG order governs evaluation order regardless of the caller's key order;
* edge inputs (``None``, ``[]``, unknown keys, all-unknown, duplicates, a bare
  ``str``) are each a deliberate, new choice;
* ``diagnose_feature`` agrees with ``run_feature`` under the identical filter.

``select_experience`` (``evaluation/experiences.py``) gains no parameter and is
never called directly here.
"""

from __future__ import annotations

import pytest

from convert_sdk import Core, DiagnosticReason, FeatureStatus, SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.evaluation.features import resolve_feature, resolve_features


def _feature(feature_id, key):
    return {"id": feature_id, "key": key, "variables": []}


def _experience_with_feature(exp_id, key, feature_id, variation_id, variation_key):
    return {
        "id": exp_id,
        "key": key,
        "variations": [
            {
                "id": variation_id,
                "key": variation_key,
                "traffic_allocation": 100.0,
                "changes": [
                    {
                        "id": f"c-{exp_id}",
                        "type": "fullStackFeature",
                        "data": {"feature_id": feature_id, "variables_data": {}},
                    }
                ],
            }
        ],
    }


def _config(experiences, features):
    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "features": features,
        "experiences": experiences,
    }


def _ctx(config, visitor_id="visitor-1"):
    core = Core(SDKConfig(data=config), transport=None).initialize()
    return core.create_context(visitor_id)


# Two experiences, each carrying its OWN feature -- CAP-1's narrowing/omission
# fixture. Keys are deliberately multi-character (never single-letter) so a
# naive `experience_keys` guard that iterates a bare string's characters
# cannot coincidentally match either key.
DISTINCT_FEATURES_CONFIG = _config(
    experiences=[
        _experience_with_feature(
            "e-checkout", "checkout-experiment", "f-a", "v-checkout", "checkout-variant"
        ),
        _experience_with_feature(
            "e-upsell", "upsell-experiment", "f-b", "v-upsell", "upsell-variant"
        ),
    ],
    features=[_feature("f-a", "feature-a"), _feature("f-b", "feature-b")],
)

# Two experiences that both carry the SAME feature -- the precedence fixture.
# Config order: primary first, secondary second.
SHARED_FEATURE_CONFIG = _config(
    experiences=[
        _experience_with_feature(
            "e-primary", "primary-experiment", "f-shared", "v-primary", "primary-variant"
        ),
        _experience_with_feature(
            "e-secondary", "secondary-experiment", "f-shared", "v-secondary", "secondary-variant"
        ),
    ],
    features=[_feature("f-shared", "shared-feature")],
)

# Identical experiences, config order reversed (secondary first).
SHARED_FEATURE_CONFIG_REVERSED = _config(
    experiences=[
        _experience_with_feature(
            "e-secondary", "secondary-experiment", "f-shared", "v-secondary", "secondary-variant"
        ),
        _experience_with_feature(
            "e-primary", "primary-experiment", "f-shared", "v-primary", "primary-variant"
        ),
    ],
    features=[_feature("f-shared", "shared-feature")],
)


# --- module-level resolve_feature / resolve_features accept the keyword ------


def test_resolve_feature_accepts_experience_keys_keyword():
    snapshot = load_snapshot(DISTINCT_FEATURES_CONFIG)
    result = resolve_feature(
        "feature-a", snapshot, visitor_id="v1", experience_keys=["checkout-experiment"]
    )
    assert result is not None
    assert result.feature_key == "feature-a"


def test_resolve_features_accepts_experience_keys_keyword():
    snapshot = load_snapshot(DISTINCT_FEATURES_CONFIG)
    results = resolve_features(snapshot, visitor_id="v1", experience_keys=["checkout-experiment"])
    assert {r.feature_key for r in results} == {"feature-a"}


# --- edge-input table: rows 1 (absent) and 2 (empty list) --------------------


@pytest.mark.parametrize("experience_keys", [None, []], ids=["absent", "empty-list"])
def test_absent_and_empty_list_both_consider_every_experience(experience_keys):
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    results = ctx.run_features(experience_keys=experience_keys)
    assert {r.feature_key for r in results} == {"feature-a", "feature-b"}
    assert ctx.run_feature("feature-a", experience_keys=experience_keys) is not None
    assert ctx.run_feature("feature-b", experience_keys=experience_keys) is not None


# --- edge-input table row 3: one unknown key among known ---------------------


def test_one_unknown_key_among_known_is_skipped_known_keys_still_resolve():
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    results = ctx.run_features(
        experience_keys=["checkout-experiment", "upsell-experiment", "does-not-exist"]
    )
    assert {r.feature_key for r in results} == {"feature-a", "feature-b"}


# --- edge-input table row 4: every key unknown -------------------------------


def test_every_key_unknown_omits_every_feature_never_disabled():
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    results = ctx.run_features(experience_keys=["ghost-one", "ghost-two"])
    assert results == []
    assert all(r.status is not FeatureStatus.DISABLED for r in results)
    assert ctx.run_feature("feature-a", experience_keys=["ghost-one", "ghost-two"]) is None
    assert ctx.run_feature("feature-b", experience_keys=["ghost-one", "ghost-two"]) is None


# --- edge-input table row 6: duplicate keys ----------------------------------


def test_duplicate_keys_are_deduplicated_and_do_not_change_the_result():
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    single = {r.feature_key for r in ctx.run_features(experience_keys=["checkout-experiment"])}
    duplicated = {
        r.feature_key
        for r in ctx.run_features(
            experience_keys=["checkout-experiment", "checkout-experiment", "checkout-experiment"]
        )
    }
    assert single == duplicated == {"feature-a"}


# --- edge-input table row 7: a bare str is treated as absent -----------------


def test_bare_string_is_treated_as_absent_not_iterated_as_characters():
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    absent = {r.feature_key for r in ctx.run_features(experience_keys=None)}
    bare_str = {r.feature_key for r in ctx.run_features(experience_keys="checkout-experiment")}
    assert bare_str == absent == {"feature-a", "feature-b"}


# --- CAP-2: narrowing omits, never pads DISABLED -----------------------------


def test_narrowing_to_one_experience_omits_the_other_features_result():
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    filtered = ctx.run_features(experience_keys=["checkout-experiment"])
    assert {r.feature_key for r in filtered} == {"feature-a"}
    assert all(r.status is not FeatureStatus.DISABLED for r in filtered)
    assert ctx.run_feature("feature-b", experience_keys=["checkout-experiment"]) is None


# --- CAP-1: precedence, not just membership ----------------------------------


def test_default_precedence_resolves_the_first_experience_in_config_order():
    ctx = _ctx(SHARED_FEATURE_CONFIG, visitor_id="shared-visitor")
    result = ctx.run_feature("shared-feature", experience_keys=None)
    assert result is not None
    assert result.experience_key == "primary-experiment"


def test_experience_keys_filter_shifts_precedence_to_the_named_experience():
    ctx = _ctx(SHARED_FEATURE_CONFIG, visitor_id="shared-visitor")
    result = ctx.run_feature("shared-feature", experience_keys=["secondary-experiment"])
    assert result is not None
    assert result.experience_key == "secondary-experiment"


# --- edge-input table row 5 + point 4: config order governs, caller order doesn't ---


def test_reversing_caller_key_order_does_not_change_precedence():
    ctx = _ctx(SHARED_FEATURE_CONFIG, visitor_id="shared-visitor")
    result = ctx.run_feature(
        "shared-feature", experience_keys=["secondary-experiment", "primary-experiment"]
    )
    assert result is not None
    assert result.experience_key == "primary-experiment"


def test_reversing_config_experience_order_flips_precedence():
    ctx = _ctx(SHARED_FEATURE_CONFIG_REVERSED, visitor_id="shared-visitor")
    result = ctx.run_feature("shared-feature", experience_keys=None)
    assert result is not None
    assert result.experience_key == "secondary-experiment"


# --- CAP-3: diagnose_feature agrees with run_feature under the same filter ---


@pytest.mark.parametrize(
    "feature_key,experience_keys",
    [
        ("feature-a", None),
        ("feature-a", ["upsell-experiment"]),
        ("feature-b", ["checkout-experiment", "upsell-experiment"]),
        ("feature-a", ["ghost-key"]),
    ],
    ids=["resolves-unfiltered", "filtered-out-by-caller", "included-resolves", "unknown-key-omits"],
)
def test_diagnose_feature_agrees_with_run_feature_under_the_identical_filter(
    feature_key, experience_keys
):
    ctx = _ctx(DISTINCT_FEATURES_CONFIG)
    resolved = ctx.run_feature(feature_key, experience_keys=experience_keys) is not None
    diagnosis = ctx.diagnose_feature(feature_key, experience_keys=experience_keys)
    assert diagnosis.resolved is resolved
    if not resolved:
        assert diagnosis.reason is DiagnosticReason.FEATURE_NOT_IN_SELECTED_VARIATIONS
