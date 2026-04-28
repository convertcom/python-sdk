from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

import pytest

from convert_sdk import Core, LifecycleEvent, LifecycleEventPayload, SDKConfig
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_experience_evaluation import sample_config_payload


@dataclass
class RecordingTransport:
    tracking_requests: List[TrackingRequest] = field(default_factory=list)
    error: Exception | None = None

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        raise AssertionError(f"fetch_config should not be called during this test: {request}")

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        self.tracking_requests.append(request)
        if self.error is not None:
            raise self.error
        return {"accepted": True}


def build_core(transport: RecordingTransport) -> Core:
    return Core(
        SDKConfig(
            config_data=sample_config_payload(),
            environment="production",
        ),
        transport=transport,
    )


def capture_events(
    core: Core,
    *events: LifecycleEvent,
) -> list[LifecycleEventPayload]:
    captured: list[LifecycleEventPayload] = []
    for event in events:
        core.on(event, captured.append)
    return captured


def assert_payload_is_privacy_safe(payload: LifecycleEventPayload) -> None:
    detail_text = repr(dict(payload.details))

    assert "visitor-123" not in detail_text
    assert "secret" not in detail_text
    assert "1001/2002" not in detail_text
    assert "amount" not in detail_text
    assert "10.0" not in detail_text


def test_conversion_and_queue_lifecycle_events_are_emitted_in_order() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    captured = capture_events(
        core,
        LifecycleEvent.CONVERSION_CREATED,
        LifecycleEvent.TRACKING_EVENT_QUEUED,
        LifecycleEvent.QUEUE_RELEASE_STARTED,
        LifecycleEvent.QUEUE_RELEASED,
    )
    context = core.create_context("visitor-123", {"tier": "premium"})

    result = context.track_conversion("purchase", conversion_data={"amount": 10.0})
    flush_result = context.release_queues("checkout-complete")

    assert [payload.event for payload in captured] == [
        LifecycleEvent.CONVERSION_CREATED,
        LifecycleEvent.TRACKING_EVENT_QUEUED,
        LifecycleEvent.QUEUE_RELEASE_STARTED,
        LifecycleEvent.QUEUE_RELEASED,
    ]
    assert result.queued_event_count == 2
    assert flush_result.delivered_event_count == 2
    assert captured[0].details["goal_key"] == "purchase"
    assert captured[0].details["event_count"] == 2
    assert captured[1].details["queued_event_count"] == 2
    assert captured[2].details["reason"] == "checkout-complete"
    assert captured[3].details["delivered_event_count"] == 2
    assert captured[3].details["remaining_event_count"] == 0
    for payload in captured:
        assert_payload_is_privacy_safe(payload)


def test_duplicate_conversion_emits_deduplicated_event() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    captured = capture_events(core, LifecycleEvent.CONVERSION_DEDUPLICATED)
    context = core.create_context("visitor-123", {"tier": "premium"})

    context.track_conversion("purchase")
    duplicate = context.track_conversion("purchase")

    assert duplicate.duplicate_prevented is True
    assert [payload.event for payload in captured] == [
        LifecycleEvent.CONVERSION_DEDUPLICATED
    ]
    assert captured[0].details["goal_key"] == "purchase"
    assert captured[0].details["reason"] == "duplicate_prevented"
    assert_payload_is_privacy_safe(captured[0])


def test_delivery_failure_emits_event_logs_safely_and_reraises(caplog: pytest.LogCaptureFixture) -> None:
    transport = RecordingTransport(error=RuntimeError("network secret visitor-123"))
    core = build_core(transport)
    captured = capture_events(
        core,
        LifecycleEvent.QUEUE_RELEASE_STARTED,
        LifecycleEvent.TRACKING_DELIVERY_FAILED,
    )
    context = core.create_context("visitor-123", {"tier": "premium"})
    context.track_conversion("purchase")

    with (
        caplog.at_level("WARNING", logger="convert_sdk.tracking"),
        pytest.raises(RuntimeError, match="network secret visitor-123"),
    ):
        context.release_queues("manual-flush")

    assert [payload.event for payload in captured] == [
        LifecycleEvent.QUEUE_RELEASE_STARTED,
        LifecycleEvent.TRACKING_DELIVERY_FAILED,
    ]
    failure_details = captured[1].details
    assert failure_details["error_type"] == "RuntimeError"
    assert failure_details["remaining_event_count"] == 1
    assert "tracking delivery failure" in caplog.text
    assert "visitor-123" not in caplog.text
    assert "secret" not in caplog.text
    assert_payload_is_privacy_safe(captured[1])


def test_core_off_removes_lifecycle_handler() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    captured: list[LifecycleEventPayload] = []

    core.on(LifecycleEvent.CONVERSION_CREATED, captured.append)
    core.off(LifecycleEvent.CONVERSION_CREATED, captured.append)
    core.create_context("visitor-123", {"tier": "premium"}).track_conversion("purchase")

    assert captured == []
