from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

import pytest

from convert_sdk import Core, SDKConfig, TrackingConfig
from convert_sdk.domain.context_state import ContextState
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_experience_evaluation import sample_config_payload


@dataclass
class RecordingTransport:
    config_requests: list[ConfigRequest] = field(default_factory=list)
    tracking_requests: list[TrackingRequest] = field(default_factory=list)

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        self.config_requests.append(request)
        return sample_config_payload()

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        self.tracking_requests.append(request)
        return {"accepted": True}


@dataclass
class RecordingDataStore:
    states: dict[str, ContextState] = field(default_factory=dict)
    tracked_goals: set[tuple[str, str]] = field(default_factory=set)
    load_calls: list[str] = field(default_factory=list)
    save_calls: list[str] = field(default_factory=list)

    def load_context_state(self, visitor_id: str) -> ContextState | None:
        self.load_calls.append(visitor_id)
        return self.states.get(visitor_id)

    def save_context_state(self, state: ContextState) -> None:
        self.save_calls.append(state.visitor_id)
        self.states[state.visitor_id] = state

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        return (visitor_id, goal_id) in self.tracked_goals

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        self.tracked_goals.add((visitor_id, goal_id))


def diagnostic_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "convert_sdk.diagnostics"
    ]


def test_custom_transport_and_storage_preserve_evaluation_and_tracking_semantics() -> None:
    transport = RecordingTransport()
    store = RecordingDataStore()
    core = Core(
        SDKConfig(
            sdk_key="sdk-key-secret",
            environment="production",
            tracking=TrackingConfig(batch_size=1),
        ),
        transport=transport,
        data_store=store,
    )

    context = core.create_context("visitor-123", {"tier": "free"})
    context.update_visitor_attributes({"tier": "premium"})
    reloaded = core.create_context("visitor-123")

    experience = reloaded.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )
    feature = reloaded.run_feature(
        "checkout-banner",
        location_attributes={"path": "/checkout"},
    )
    conversion = reloaded.track_conversion("purchase")
    flush = reloaded.release_queues("custom-integration-test")

    assert len(transport.config_requests) == 1
    assert len(transport.tracking_requests) == 1
    assert store.load_calls.count("visitor-123") == 2
    assert store.save_calls.count("visitor-123") >= 2
    assert experience is not None
    assert feature is not None
    assert conversion.queued_event_count == 1
    assert flush.delivered_event_count == 1


def test_standard_logging_configuration_captures_cross_sdk_comparable_context(
    caplog: pytest.LogCaptureFixture,
) -> None:
    core = Core(
        SDKConfig(
            config_data=sample_config_payload(),
            environment="production",
        )
    )
    context = core.create_context("visitor-123", {"tier": "premium"})

    with caplog.at_level(logging.DEBUG, logger="convert_sdk.diagnostics"):
        diagnostic = context.diagnose_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )

    record = next(
        record
        for record in diagnostic_records(caplog)
        if record.sdk_event == "evaluation.experience.completed"
    )

    assert diagnostic.resolved is True
    assert record.sdk_details["reason"] == "resolved"
    assert record.sdk_details["environment"] == "production"
    assert isinstance(record.sdk_details["bucket_value"], int)
    assert record.sdk_details["variation_key"] in {"control", "free-shipping"}
    assert "visitor_ref" in record.sdk_details
    assert "visitor-123" not in repr(record.sdk_details)
