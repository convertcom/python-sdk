from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

import pytest

from convert_sdk import (
    ConfigLoadError,
    ConfigValidationError,
    Core,
    EntityDiagnostic,
    ExperienceDiagnostic,
    FeatureDiagnostic,
    GoalDiagnostic,
    GoalNotFoundError,
    SDKConfig,
)
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_experience_evaluation import build_context


@dataclass
class FailingTransport:
    error: Exception

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        raise self.error

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        return {"accepted": False}


def diagnostic_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "convert_sdk.diagnostics"
    ]


def test_config_fetch_errors_expose_safe_actionable_context() -> None:
    transport = FailingTransport(
        RuntimeError("network error for sdk-key-secret and top-secret")
    )

    with pytest.raises(ConfigLoadError) as excinfo:
        Core(
            SDKConfig(
                sdk_key="sdk-key-secret",
                sdk_key_secret="top-secret",
            ),
            transport=transport,
        )

    error = excinfo.value
    assert error.code == "config.fetch_failed"
    assert error.context["source"] == "sdk_key"
    assert error.context["error_type"] == "RuntimeError"
    assert error.context["endpoint_host"] == "cdn-4.convertexperiments.com"
    assert "sdk-key-secret" not in str(error)
    assert "top-secret" not in str(error)


def test_config_processing_errors_expose_safe_context_without_raw_config() -> None:
    with pytest.raises(ConfigValidationError) as excinfo:
        Core(SDKConfig(config_data={"account_id": "1001"}))

    error = excinfo.value
    assert error.code == "config.invalid_data"
    assert error.context["reason"] == "project_mapping_required"
    assert error.context["field"] == "project"
    assert "1001" not in str(error)


def test_experience_diagnostics_distinguish_resolved_and_miss_outcomes() -> None:
    qualified_context = build_context("visitor-123", {"tier": "premium"})
    resolved = qualified_context.diagnose_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    assert isinstance(resolved, ExperienceDiagnostic)
    assert resolved.resolved is True
    assert resolved.reason == "resolved"
    assert resolved.result is not None
    assert resolved.details["bucket_value"] == resolved.result.bucket_value

    unqualified_context = build_context("visitor-123", {"tier": "free"})
    miss = unqualified_context.diagnose_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    assert miss.resolved is False
    assert miss.reason == "audience_mismatch"
    assert miss.result is None
    assert (
        unqualified_context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        is None
    )

    missing = unqualified_context.diagnose_experience("missing-experience")
    assert missing.resolved is False
    assert missing.reason == "experience_not_found"


def test_feature_goal_and_entity_diagnostics_return_non_exception_misses() -> None:
    context = build_context("visitor-123", {"tier": "free"})

    feature = context.diagnose_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )
    assert isinstance(feature, FeatureDiagnostic)
    assert feature.resolved is False
    assert feature.reason == "feature_not_in_selected_variations"

    missing_feature = context.diagnose_feature("missing-feature")
    assert missing_feature.resolved is False
    assert missing_feature.reason == "feature_not_found"

    goal = context.diagnose_goal("missing-goal")
    assert isinstance(goal, GoalDiagnostic)
    assert goal.resolved is False
    assert goal.reason == "goal_not_found"

    entity = context.diagnose_config_entity("feature", "missing-feature")
    assert isinstance(entity, EntityDiagnostic)
    assert entity.resolved is False
    assert entity.reason == "entity_not_found"

    resolved_entity = context.diagnose_config_entity_by_id("goal", "goal-1")
    assert resolved_entity.resolved is True
    assert resolved_entity.reason == "resolved"


def test_goal_tracking_errors_remain_distinct_from_normal_misses() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    with pytest.raises(GoalNotFoundError) as excinfo:
        context.track_conversion("missing-goal")

    error = excinfo.value
    assert error.code == "goal.not_found"
    assert error.context["reason"] == "goal_not_found"
    assert error.context["goal_key"] == "missing-goal"


def test_diagnostic_miss_logs_include_reason_without_raw_visitor_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    context = build_context("visitor-123", {"tier": "free", "email": "aisha@example.com"})

    with caplog.at_level(logging.DEBUG, logger="convert_sdk.diagnostics"):
        context.diagnose_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )

    record = next(
        record
        for record in diagnostic_records(caplog)
        if record.sdk_event == "evaluation.experience.completed"
    )

    assert record.sdk_details["reason"] == "audience_mismatch"
    assert "visitor_ref" in record.sdk_details
    record_text = repr(record.sdk_details)
    assert "visitor-123" not in record_text
    assert "aisha@example.com" not in record_text
