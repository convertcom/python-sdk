from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, List, Mapping

import pytest

from convert_sdk import Core, SDKConfig
from convert_sdk.diagnostics import redact_diagnostic_details
from convert_sdk.errors import ConfigLoadError
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_experience_evaluation import sample_config_payload


@dataclass
class RecordingTransport:
    tracking_requests: List[TrackingRequest] = field(default_factory=list)
    config_error: Exception | None = None

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        if self.config_error is not None:
            raise self.config_error
        raise AssertionError(f"fetch_config should not be called during this test: {request}")

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        self.tracking_requests.append(request)
        return {"accepted": True}


def diagnostic_records(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [
        record
        for record in caplog.records
        if record.name == "convert_sdk.diagnostics"
    ]


def assert_record_is_privacy_safe(record: logging.LogRecord) -> None:
    details = getattr(record, "sdk_details", {})
    detail_text = repr(details)
    record_text = f"{record.getMessage()} {detail_text}"

    assert "visitor-123" not in record_text
    assert "sdk-key-secret" not in record_text
    assert "top-secret" not in record_text
    assert "Authorization" not in record_text
    assert "amount" not in record_text
    assert "10.0" not in record_text
    assert "config_data" not in record_text
    assert "payload" not in record_text


def test_diagnostic_logs_cover_core_evaluation_and_tracking_flows(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = RecordingTransport()

    with caplog.at_level(logging.DEBUG, logger="convert_sdk.diagnostics"):
        core = Core(
            SDKConfig(
                config_data=sample_config_payload(),
                environment="production",
            ),
            transport=transport,
        )
        context = core.create_context("visitor-123", {"tier": "premium"})
        context.run_experience(
            "checkout-flow",
            visitor_attributes={"amount": 10.0},
            location_attributes={"path": "/checkout"},
        )
        context.run_feature(
            "checkout-banner",
            visitor_attributes={"amount": 10.0},
            location_attributes={"path": "/checkout"},
        )
        context.track_conversion("purchase", conversion_data={"amount": 10.0})
        context.release_queues("checkout-complete")

    records = diagnostic_records(caplog)
    events = [record.sdk_event for record in records]

    assert "sdk.initialization.started" in events
    assert "config.load.started" in events
    assert "config.load.succeeded" in events
    assert "sdk.initialization.succeeded" in events
    assert "context.created" in events
    assert "evaluation.experience.completed" in events
    assert "evaluation.feature.completed" in events
    assert "tracking.conversion.started" in events
    assert "tracking.conversion.queued" in events
    assert "tracking.event.queued" in events
    assert "tracking.queue.release.started" in events
    assert "tracking.queue.release.succeeded" in events

    for record in records:
        assert isinstance(record.sdk_event, str)
        assert isinstance(record.sdk_details, Mapping)
        assert_record_is_privacy_safe(record)


def test_diagnostic_logs_redact_accidental_sensitive_details() -> None:
    redacted = redact_diagnostic_details(
        {
            "visitor_id": "visitor-123",
            "sdk_key": "sdk-key-secret",
            "sdk_key_secret": "top-secret",
            "headers": {"Authorization": "Bearer token"},
            "conversion_data": {"amount": 10.0},
            "payload": {"visitors": [{"visitorId": "visitor-123"}]},
            "safe_count": 2,
        }
    )

    assert redacted["visitor_ref"] != "visitor-123"
    assert redacted["sdk_key"] == "<redacted>"
    assert redacted["sdk_key_secret"] == "<redacted>"
    assert redacted["headers"] == "<redacted>"
    assert redacted["conversion_data"] == "<redacted>"
    assert redacted["payload"] == "<redacted>"
    assert redacted["safe_count"] == 2


def test_config_failure_diagnostics_do_not_log_secret_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    transport = RecordingTransport(
        config_error=RuntimeError("network error for sdk-key-secret and visitor-123")
    )

    with caplog.at_level(logging.DEBUG, logger="convert_sdk.diagnostics"):
        with pytest.raises(ConfigLoadError):
            Core(
                SDKConfig(
                    sdk_key="sdk-key-secret",
                    sdk_key_secret="top-secret",
                ),
                transport=transport,
            )

    records = diagnostic_records(caplog)
    events = [record.sdk_event for record in records]

    assert "config.load.failed" in events
    assert "sdk.initialization.failed" in events
    for record in records:
        assert_record_is_privacy_safe(record)

    failure = next(record for record in records if record.sdk_event == "config.load.failed")
    assert failure.sdk_details["source"] == "sdk_key"
    assert failure.sdk_details["error_type"] == "RuntimeError"
