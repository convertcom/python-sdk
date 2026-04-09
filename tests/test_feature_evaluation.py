from __future__ import annotations

from typing import Mapping

from convert_sdk import FeatureResult, FeatureStatus

from test_experience_evaluation import build_context


def test_run_feature_returns_typed_variables_for_an_applicable_feature() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    result = context.run_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )

    assert isinstance(result, FeatureResult)
    assert result.feature_key == "checkout-banner"
    assert result.status is FeatureStatus.ENABLED
    assert isinstance(result.variables["enabled"], bool)
    assert isinstance(result.variables["discount"], int)
    assert isinstance(result.variables["payload"], Mapping)
    assert result.variables["payload"]["theme"] in {"default", "promo"}


def test_run_feature_returns_none_when_feature_is_unavailable_or_disabled() -> None:
    context = build_context("visitor-123", {"tier": "free"})

    assert (
        context.run_feature(
            "checkout-banner",
            location_attributes={"path": "/checkout"},
        )
        is None
    )
    assert context.run_feature("missing-feature") is None


def test_run_feature_is_deterministic_for_the_same_visitor_and_snapshot() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    first = context.run_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )
    second = context.run_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )

    assert first == second


def test_run_features_returns_all_applicable_feature_results() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    results = context.run_features(location_attributes={"path": "/checkout"})

    assert [result.feature_key for result in results] == ["checkout-banner"]
