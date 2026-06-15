"""Integration: tracking queue -> serialize -> deliver (qs-06).

Exercises the full delivery pipeline against the frozen qs-06 RESPX harness
(``conftest.py``): track -> flush -> serialize via Story 2.2 ``payloads.py`` ->
POST ``/track/{sdkKey}``. Asserts the POSTed batch matches the Story 2.2
serialized shape and that a successful delivery clears the queue. All offline —
no real network (RESPX route-level mocking, never socket-level).
"""

from __future__ import annotations

import json

from .conftest import SDK_KEY


def _posted_bodies(route):
    return [json.loads(call.request.content) for call in route.calls]


def test_flush_delivers_queued_conversion_and_clears_queue(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    core = sdk_with_mock_transport
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("purchase_completed", revenue=49.99)

    # No delivery until flush (enqueue is lightweight, no network I/O).
    assert mock_tracking_endpoint.call_count == 0

    core.flush()

    assert mock_tracking_endpoint.call_count == 1
    body = _posted_bodies(mock_tracking_endpoint)[0]
    # Story 2.2 envelope shape (verbose JS-SDK wire names).
    assert body["accountId"] == "100123"
    assert body["projectId"] == "200456"
    assert body["source"] == "js-sdk"
    visitor = body["visitors"][0]
    assert visitor["visitorId"] == "visitor-1"
    event = visitor["events"][0]
    assert event["eventType"] == "conversion"
    assert event["data"]["goalId"] == "g1"
    assert {"key": "amount", "value": 49.99} in event["data"]["goalData"]

    # Queue cleared on success -> a second flush is a no-op (no new POST).
    core.flush()
    assert mock_tracking_endpoint.call_count == 1


def test_flush_on_empty_queue_makes_no_post(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    core = sdk_with_mock_transport
    core.flush()
    assert mock_tracking_endpoint.call_count == 0


def test_batch_size_release_delivers_without_explicit_flush(
    respx_mock, mock_config_endpoint, mock_tracking_endpoint
):
    # Build a Core with batch_size=2 sharing the mocked transport.
    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core

    from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL

    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            batch_size=2,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
        ),
        transport=transport,
    ).initialize()
    try:
        ctx = core.create_context("v1")
        ctx.track_conversion("purchase_completed")
        assert mock_tracking_endpoint.call_count == 0
        # Second distinct goal reaches batch_size=2 -> auto release.
        ctx.track_conversion("signup")
        assert mock_tracking_endpoint.call_count == 1
    finally:
        core.close()


def test_multiple_visitors_delivered_in_one_batch(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    core = sdk_with_mock_transport
    core.create_context("v1").track_conversion("purchase_completed")
    core.create_context("v2").track_conversion("signup")
    core.flush()
    assert mock_tracking_endpoint.call_count == 1
    body = _posted_bodies(mock_tracking_endpoint)[0]
    assert {v["visitorId"] for v in body["visitors"]} == {"v1", "v2"}


def test_failed_delivery_surfaces_via_event_drops_events_and_does_not_raise(
    respx_mock, mock_config_endpoint, caplog
):
    """Story 2.4 (F-010) delivery-failure contract.

    A failing flush emits ``API_QUEUE_RELEASED`` with the delivery error, logs a
    privacy-safe failure line, DROPS the events (does NOT re-queue), and does NOT
    raise out of ``flush()``. This intentionally supersedes the Story 2.3
    preserve-and-raise behavior (architecture #Retry-and-Backoff-Formula).
    """
    import logging

    import httpx

    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core
    from convert_sdk.events import LifecycleEvent, QueueReleasedPayload

    from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL

    # Both POSTs fail (503) — there is no tracking-layer retry; the transport
    # adapter raises TrackingDeliveryError and the release path drops the events.
    route = respx_mock.post(f"/track/{SDK_KEY}").mock(
        return_value=httpx.Response(503, text="unavailable")
    )
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
        ),
        transport=transport,
    ).initialize()
    released = []
    core.on(
        LifecycleEvent.API_QUEUE_RELEASED,
        lambda payload, error=None: released.append((payload, error)),
    )
    try:
        core.create_context("v1").track_conversion("purchase_completed")
        with caplog.at_level(logging.ERROR, logger="convert_sdk"):
            # Must NOT raise (Critical Warning #3).
            core.flush()

        # Exactly one failure outcome emitted.
        assert len(released) == 1
        payload, error = released[0]
        assert isinstance(payload, QueueReleasedPayload)
        assert payload.reason.value == "explicit"
        assert payload.batch_size == 1
        assert payload.event_count == 1
        assert payload.visitor_count == 1
        assert payload.status_code == 503
        assert error is not None

        # Privacy-safe failure log (NFR23): batch size + status present.
        failure_logs = [r for r in caplog.records if "tracking delivery failure" in r.message]
        assert failure_logs, "expected a privacy-safe delivery-failure log line"

        # Events were DROPPED, not re-queued: a later (still-failing) flush emits
        # nothing more because the queue is empty.
        first_calls = route.call_count
        core.flush()
        assert route.call_count == first_calls  # no second delivery attempt
        assert len(released) == 1
    finally:
        core.close()


def test_successful_flush_emits_queue_released_with_reason_and_counts(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    from convert_sdk.events import LifecycleEvent, QueueReleasedPayload

    core = sdk_with_mock_transport
    released = []
    core.on(
        LifecycleEvent.API_QUEUE_RELEASED,
        lambda payload, error=None: released.append((payload, error)),
    )
    core.create_context("v1").track_conversion("purchase_completed")
    core.create_context("v2").track_conversion("signup")
    core.flush()

    assert mock_tracking_endpoint.call_count == 1
    assert len(released) == 1
    payload, error = released[0]
    assert error is None
    assert isinstance(payload, QueueReleasedPayload)
    assert payload.reason.value == "explicit"
    assert payload.batch_size == 2
    assert payload.event_count == 2
    assert payload.visitor_count == 2
    # Success payload carries the real 2xx from the metrics endpoint (not None).
    assert isinstance(payload.status_code, int)
    assert 200 <= payload.status_code < 300


def test_empty_flush_emits_no_queue_released(
    sdk_with_mock_transport, mock_tracking_endpoint
):
    from convert_sdk.events import LifecycleEvent

    core = sdk_with_mock_transport
    released = []
    core.on(LifecycleEvent.API_QUEUE_RELEASED, lambda payload, error=None: released.append(payload))
    # Nothing tracked -> empty-queue flush is a no-op (no release occurred).
    core.flush()
    assert mock_tracking_endpoint.call_count == 0
    assert released == []


def test_failure_event_and_log_contain_no_secrets_or_pii(
    respx_mock, mock_config_endpoint, caplog
):
    """NFR23/NFR7: the failure payload + failure log carry only batch_size,
    status code, and retry count — never the SDK key, auth header, or raw
    visitor attributes."""
    import logging

    import httpx

    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core
    from convert_sdk.events import LifecycleEvent

    from .conftest import MOCK_BASE_URL, MOCK_TRACK_BASE_URL

    respx_mock.post(f"/track/{SDK_KEY}").mock(return_value=httpx.Response(500))
    transport = HttpxTransport(
        TransportConfig(base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL)
    )
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            transport=TransportConfig(
                base_url=MOCK_BASE_URL, track_base_url=MOCK_TRACK_BASE_URL
            ),
        ),
        transport=transport,
    ).initialize()
    captured = []
    core.on(
        LifecycleEvent.API_QUEUE_RELEASED,
        lambda payload, error=None: captured.append((payload, error)),
    )
    try:
        core.create_context("secret-visitor").track_conversion(
            "purchase_completed",
            conversion_data={"plan": "enterprise"},
        )
        with caplog.at_level(logging.ERROR, logger="convert_sdk"):
            core.flush()

        payload, error = captured[0]
        # The payload surface exposes only safe diagnostic fields.
        assert payload.status_code == 500
        assert payload.batch_size == 1
        assert not hasattr(payload, "sdk_key")
        assert not hasattr(payload, "visitor_attributes")
        # No log line leaks the SDK key, the bearer header value, or raw
        # conversion attributes.
        joined = " ".join(r.getMessage() for r in caplog.records)
        assert SDK_KEY not in joined
        assert "Bearer" not in joined
        assert "enterprise" not in joined
    finally:
        core.close()
