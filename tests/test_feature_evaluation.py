"""Story 1.6 (minimal feature foundation) — local feature resolution tests.

Story 1.5's feature-resolution code shipped only on a superseded branch lineage,
so Story 1.6 builds the *minimal* foundation it needs to document and demonstrate
feature evaluation: ``Context.run_feature`` / ``Context.run_features`` returning
typed :class:`~convert_sdk.domain.results.FeatureResult` objects, resolved locally
from selected variations' ``fullStackFeature`` changes matched to declared feature
definitions in the snapshot.

Behavioral guardrails (mirrors Story 1.5 intent + Story 1.4 evaluation reuse):

* Typed result with cast variables when a qualified visitor buckets into a
  variation carrying a ``fullStackFeature`` change for the feature (AC #1).
* ``None`` for undeclared / unavailable / disabled / unqualified features — never
  an exception on a normal miss (AC #1).
* Deterministic repeated evaluation for the same visitor + snapshot (AC #3).
* ``run_features`` returns only the applicable typed results, with no network I/O
  (AC #2).
"""

import pytest

from convert_sdk import Core, FeatureResult, FeatureStatus, SDKConfig


# Two variations carry a fullStackFeature change for feature "f1" (declared with
# typed variables) so resolution returns a typed, cast result. The experience is
# unrestricted (no audience) so every visitor qualifies and buckets.
CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "features": [
        {
            "id": "10024",
            "key": "checkout-banner",
            "name": "Checkout Banner",
            "variables": [
                {"key": "enabled", "type": "boolean"},
                {"key": "caption", "type": "string"},
                {"key": "max_items", "type": "integer"},
                {"key": "meta", "type": "json"},
            ],
        }
    ],
    "experiences": [
        {
            "id": "e1",
            "key": "banner-experiment",
            "variations": [
                {
                    "id": "v1",
                    "key": "control",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c1",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "false",
                                    "caption": "Control",
                                    "max_items": "3",
                                    "meta": '{"variant":"control"}',
                                },
                            },
                        }
                    ],
                },
                {
                    "id": "v2",
                    "key": "treatment",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c2",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "true",
                                    "caption": "Treatment",
                                    "max_items": "5",
                                    "meta": '{"variant":"treatment"}',
                                },
                            },
                        }
                    ],
                },
            ],
        },
        {
            # An experience with no feature change — should never contribute a
            # feature result for "checkout-banner".
            "id": "e2",
            "key": "no-feature",
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        },
    ],
}


def _ready_core(transport=None):
    return Core(SDKConfig(data=CONFIG), transport=transport).initialize()


def _ctx(visitor_id="visitor-1"):
    return _ready_core().create_context(visitor_id)


# --- public surface -----------------------------------------------------------


def test_feature_result_and_status_are_public():
    assert FeatureResult is not None
    assert hasattr(FeatureStatus, "ENABLED")
    assert hasattr(FeatureStatus, "DISABLED")


# --- AC #1: typed result with cast variables ----------------------------------


def test_run_feature_returns_typed_result_with_cast_variables():
    ctx = _ctx()
    result = ctx.run_feature("checkout-banner")
    assert isinstance(result, FeatureResult)
    assert result.feature_key == "checkout-banner"
    assert result.feature_id == "10024"
    assert result.status == FeatureStatus.ENABLED
    # Variables are cast per the declared feature variable types.
    assert isinstance(result.variables["enabled"], bool)
    assert isinstance(result.variables["caption"], str)
    assert isinstance(result.variables["max_items"], int)
    assert isinstance(result.variables["meta"], dict)
    assert result.variables["meta"]["variant"] in {"control", "treatment"}


def test_run_feature_variables_are_read_only():
    result = _ctx().run_feature("checkout-banner")
    with pytest.raises(Exception):
        result.variables["enabled"] = "tampered"  # type: ignore[index]


# --- AC #1: None for normal misses --------------------------------------------


def test_run_feature_returns_none_for_undeclared_feature():
    assert _ctx().run_feature("does-not-exist") is None


def test_run_feature_does_not_raise_on_miss():
    # No exception for a normal miss; just None.
    assert _ctx("").run_feature("checkout-banner") is None


# --- AC #3: determinism -------------------------------------------------------


def test_run_feature_is_deterministic_for_same_visitor():
    first = _ctx("stable-visitor").run_feature("checkout-banner")
    second = _ctx("stable-visitor").run_feature("checkout-banner")
    assert first is not None and second is not None
    assert first.variation_key == second.variation_key
    assert dict(first.variables) == dict(second.variables)


# --- AC #2: run_features returns applicable typed results, no network ---------


class _ExplodingTransport:
    """Any network call is a test failure — evaluation must stay local."""

    def fetch_config(self, config):  # pragma: no cover - must never be called
        raise AssertionError("run_features must not perform network I/O")

    def close(self):
        pass


def test_run_features_returns_only_applicable_typed_results():
    core = Core(SDKConfig(data=CONFIG), transport=_ExplodingTransport()).initialize()
    ctx = core.create_context("visitor-1")
    results = ctx.run_features()
    assert isinstance(results, list)
    assert all(isinstance(r, FeatureResult) for r in results)
    keys = {r.feature_key for r in results}
    assert "checkout-banner" in keys
    # Exactly one result for the single declared feature that has a change.
    assert len([r for r in results if r.feature_key == "checkout-banner"]) == 1


def test_run_features_empty_when_no_feature_changes():
    config = {
        "account_id": "1",
        "project": {"id": "2"},
        "features": [{"id": "f9", "key": "lonely", "variables": []}],
        "experiences": [
            {
                "id": "e9",
                "key": "plain",
                "variations": [{"id": "vx", "key": "only", "traffic_allocation": 100.0}],
            }
        ],
    }
    ctx = Core(SDKConfig(data=config)).initialize().create_context("v")
    assert ctx.run_features() == []
