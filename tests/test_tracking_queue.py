from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

from convert_sdk import Core, SDKConfig, TrackingConfig
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_experience_evaluation import sample_config_payload


@dataclass
class RecordingTransport:
    tracking_requests: List[TrackingRequest] = field(default_factory=list)

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        raise AssertionError(f"fetch_config should not be called during this test: {request}")

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        self.tracking_requests.append(request)
        return {"accepted": True}


def build_core(
    transport: RecordingTransport,
    *,
    batch_size: int = 10,
) -> Core:
    return Core(
        SDKConfig(
            config_data=sample_config_payload(),
            environment="production",
            tracking=TrackingConfig(batch_size=batch_size),
        ),
        transport=transport,
    )


def test_track_conversion_enqueues_without_immediate_delivery() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    context = core.create_context("visitor-123", {"tier": "premium"})

    result = context.track_conversion("purchase")

    assert result.queued_event_count == 1
    assert transport.tracking_requests == []


def test_release_queues_batches_multiple_visitors() -> None:
    transport = RecordingTransport()
    core = build_core(transport, batch_size=2)
    first = core.create_context("visitor-123", {"tier": "premium"})
    second = core.create_context("visitor-456", {"tier": "premium"})
    third = core.create_context("visitor-789", {"tier": "premium"})

    first.track_conversion("purchase")
    second.track_conversion("purchase")
    third.track_conversion("purchase")
    flush_result = first.release_queues("order-complete")

    assert flush_result.attempted is True
    assert flush_result.delivered_event_count == 3
    assert flush_result.delivered_batch_count == 2
    assert flush_result.remaining_event_count == 0
    assert flush_result.reason == "order-complete"
    assert len(transport.tracking_requests) == 2
    assert [len(request.payload["visitors"]) for request in transport.tracking_requests] == [2, 1]


def test_track_conversion_prevents_duplicate_reporting_by_default() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    context = core.create_context("visitor-123", {"tier": "premium"})

    first = context.track_conversion("purchase")
    duplicate = context.track_conversion("purchase")
    flush_result = context.release_queues()

    assert first.duplicate_prevented is False
    assert duplicate.duplicate_prevented is True
    assert duplicate.queued_event_count == 0
    assert duplicate.events == ()
    assert flush_result.delivered_event_count == 1
    assert len(transport.tracking_requests) == 1
    assert len(transport.tracking_requests[0].payload["visitors"][0]["events"]) == 1


def test_track_conversion_allows_repeated_transaction_reporting_when_forced() -> None:
    transport = RecordingTransport()
    core = build_core(transport)
    context = core.create_context("visitor-123", {"tier": "premium"})

    first = context.track_conversion(
        "purchase",
        conversion_data={"amount": 10.0},
    )
    second = context.track_conversion(
        "purchase",
        conversion_data={"amount": 15.0},
        force_multiple_transactions=True,
    )
    flush_result = context.release_queues()

    events = transport.tracking_requests[0].payload["visitors"][0]["events"]

    assert first.queued_event_count == 2
    assert second.queued_event_count == 1
    assert second.duplicate_prevented is False
    assert flush_result.delivered_event_count == 3
    assert len(events) == 3
    assert "goalData" not in events[0]["data"]
    assert events[1]["data"]["goalData"] == [{"key": "amount", "value": 10.0}]
    assert events[2]["data"]["goalData"] == [{"key": "amount", "value": 15.0}]
