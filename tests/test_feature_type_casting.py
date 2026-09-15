"""RED tests for the `type_casting` control on feature resolution (CAP-2).

Locks in a NEW keyword-only ``type_casting: bool = True`` parameter on
``Context.run_feature`` / ``Context.run_features`` (and the module-level
``resolve_feature`` / ``resolve_features`` they delegate to). Neither accepts
the keyword today, so every test below fails with a ``TypeError: unexpected
keyword argument 'type_casting'`` until the capability ships.

Semantics locked in here (not yet implemented):

* ``True`` (the default) reproduces today's cast-unconditionally behaviour,
  including the lossy ``boolean`` cast of an uncastable stored value to
  ``False`` -- the regression half of CAP-2's success criterion.
* ``False`` returns every variable exactly as the served config stores it: no
  boolean coercion, no JSON parse, no int/float conversion.
* The flag changes no decision -- every ``FeatureResult`` field but
  ``variables`` is identical either way (D-6, D-7's premise).
* Truthiness decides, matching ``enable_tracking``/``enable_storage``, not JS's
  key-presence rule or Ruby's "only literal false" rule (D-6).
* ``run_features`` forwards the flag to every resolved feature, not just the
  first.
* ``experience_keys`` and ``type_casting`` compose without interfering.

``diagnose_feature`` deliberately does NOT gain this keyword (D-7) and is out
of scope here.
"""

from __future__ import annotations

import pytest

from convert_sdk import Core, SDKConfig


def _feature(feature_id, key, variables):
    return {"id": feature_id, "key": key, "variables": variables}


def _change(feature_id, variables_data, change_id):
    return {
        "id": change_id,
        "type": "fullStackFeature",
        "data": {"feature_id": feature_id, "variables_data": variables_data},
    }


def _experience(exp_id, key, variation_id, variation_key, change):
    return {
        "id": exp_id,
        "key": key,
        "variations": [
            {
                "id": variation_id,
                "key": variation_key,
                "traffic_allocation": 100.0,
                "changes": [change],
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


# --- boundary 1: CAP-2's success criterion, one feature, every declared type -

TYPE_CASTING_FEATURE_ID = "f-type"
TYPE_CASTING_FEATURE_KEY = "typed-feature"

# "on" is the value the boolean cast cannot represent: not "true"/"1"/"yes"
# (case-insensitive), so casting-on coerces it to False -- the CAP-2 defect.
STORED_VARIABLES_DATA = {
    "enabled": "on",
    "count": "7",
    "meta": '{"k": "v"}',
    "raw": "unchanged-value",
}

TYPE_CASTING_CONFIG = _config(
    experiences=[
        _experience(
            "e-type",
            "typed-experiment",
            "v-type",
            "typed-variant",
            _change(TYPE_CASTING_FEATURE_ID, STORED_VARIABLES_DATA, "c-type"),
        )
    ],
    features=[
        _feature(
            TYPE_CASTING_FEATURE_ID,
            TYPE_CASTING_FEATURE_KEY,
            [
                {"key": "enabled", "type": "boolean"},
                {"key": "count", "type": "integer"},
                {"key": "meta", "type": "json"},
                {"key": "raw"},  # no declared type -> passthrough
            ],
        )
    ],
)


def test_type_casting_default_true_matches_todays_cast_behaviour():
    ctx = _ctx(TYPE_CASTING_CONFIG)

    result = ctx.run_feature(TYPE_CASTING_FEATURE_KEY)
    assert result is not None
    assert result.variables["enabled"] is False
    assert result.variables["count"] == 7
    assert isinstance(result.variables["count"], int)
    assert result.variables["meta"] == {"k": "v"}
    assert result.variables["raw"] == "unchanged-value"

    all_results = ctx.run_features()
    assert len(all_results) == 1
    assert all_results[0].variables["enabled"] is False
    assert all_results[0].variables["count"] == 7
    assert all_results[0].variables["meta"] == {"k": "v"}
    assert all_results[0].variables["raw"] == "unchanged-value"


def test_type_casting_false_returns_stored_values_uncast():
    ctx = _ctx(TYPE_CASTING_CONFIG)

    result = ctx.run_feature(TYPE_CASTING_FEATURE_KEY, type_casting=False)
    assert result is not None
    assert result.variables["enabled"] == "on"
    assert result.variables["count"] == "7"
    assert result.variables["meta"] == '{"k": "v"}'
    assert result.variables["raw"] == "unchanged-value"

    all_results = ctx.run_features(type_casting=False)
    assert len(all_results) == 1
    assert all_results[0].variables["enabled"] == "on"
    assert all_results[0].variables["count"] == "7"
    assert all_results[0].variables["meta"] == '{"k": "v"}'
    assert all_results[0].variables["raw"] == "unchanged-value"


# --- boundary 2: the flag changes no decision -------------------------------


def test_type_casting_flag_changes_no_decision_only_variables_differ():
    ctx = _ctx(TYPE_CASTING_CONFIG)

    cast_on = ctx.run_feature(TYPE_CASTING_FEATURE_KEY)
    cast_off = ctx.run_feature(TYPE_CASTING_FEATURE_KEY, type_casting=False)

    assert cast_on is not None
    assert cast_off is not None
    assert cast_on.feature_key == cast_off.feature_key
    assert cast_on.feature_id == cast_off.feature_id
    assert cast_on.status is cast_off.status
    assert cast_on.experience_key == cast_off.experience_key
    assert cast_on.variation_key == cast_off.variation_key
    assert dict(cast_on.variables) != dict(cast_off.variables)


# --- boundary 3: D-6 truthiness, parametrized over falsy and truthy values --


@pytest.mark.parametrize(
    "type_casting", [False, None, 0, ""], ids=["false", "none", "zero", "empty-string"]
)
def test_falsy_type_casting_values_all_disable_casting(type_casting):
    ctx = _ctx(TYPE_CASTING_CONFIG)
    result = ctx.run_feature(TYPE_CASTING_FEATURE_KEY, type_casting=type_casting)
    assert result is not None
    assert result.variables["enabled"] == "on"


@pytest.mark.parametrize("type_casting", [True, 1, "yes"], ids=["true", "one", "truthy-string"])
def test_truthy_type_casting_values_all_leave_casting_on(type_casting):
    ctx = _ctx(TYPE_CASTING_CONFIG)
    result = ctx.run_feature(TYPE_CASTING_FEATURE_KEY, type_casting=type_casting)
    assert result is not None
    assert result.variables["enabled"] is False


# --- boundary 4: run_features carries the flag to every resolved feature ---

TWO_FEATURE_CONFIG = _config(
    experiences=[
        _experience(
            "e-alpha",
            "alpha-experiment",
            "v-alpha",
            "alpha-variant",
            _change("f-alpha", {"enabled": "enabled"}, "c-alpha"),
        ),
        _experience(
            "e-beta",
            "beta-experiment",
            "v-beta",
            "beta-variant",
            _change("f-beta", {"enabled": "on"}, "c-beta"),
        ),
    ],
    features=[
        _feature("f-alpha", "feature-alpha", [{"key": "enabled", "type": "boolean"}]),
        _feature("f-beta", "feature-beta", [{"key": "enabled", "type": "boolean"}]),
    ],
)


def test_run_features_carries_type_casting_to_every_resolved_feature():
    ctx = _ctx(TWO_FEATURE_CONFIG)
    results = ctx.run_features(type_casting=False)
    assert len(results) == 2
    by_key = {r.feature_key: r for r in results}
    assert by_key["feature-alpha"].variables["enabled"] == "enabled"
    assert by_key["feature-beta"].variables["enabled"] == "on"


# --- boundary 5: composition with experience_keys ---------------------------

# Same feature carried by two experiences (precedence fixture), each storing a
# different uncastable boolean value, so a passing test must prove BOTH that
# experience_keys shifted precedence to the named experience AND that its
# variables came back uncast.
SHARED_FEATURE_ID = "f-shared-typed"
SHARED_FEATURE_KEY = "shared-typed-feature"

SHARED_TYPE_CASTING_CONFIG = _config(
    experiences=[
        _experience(
            "e-primary-t",
            "primary-typed-experiment",
            "v-primary-t",
            "primary-typed-variant",
            _change(SHARED_FEATURE_ID, {"enabled": "on"}, "c-primary-t"),
        ),
        _experience(
            "e-secondary-t",
            "secondary-typed-experiment",
            "v-secondary-t",
            "secondary-typed-variant",
            _change(SHARED_FEATURE_ID, {"enabled": "enabled"}, "c-secondary-t"),
        ),
    ],
    features=[_feature(SHARED_FEATURE_ID, SHARED_FEATURE_KEY, [{"key": "enabled", "type": "boolean"}])],
)


def test_type_casting_composes_with_experience_keys_filter():
    ctx = _ctx(SHARED_TYPE_CASTING_CONFIG, visitor_id="shared-typed-visitor")

    result = ctx.run_feature(
        SHARED_FEATURE_KEY,
        experience_keys=["secondary-typed-experiment"],
        type_casting=False,
    )

    assert result is not None
    assert result.experience_key == "secondary-typed-experiment"
    assert result.variables["enabled"] == "enabled"
