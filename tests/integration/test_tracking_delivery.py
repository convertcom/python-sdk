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

    from .conftest import MOCK_BASE_URL

    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(
            sdk_key=SDK_KEY,
            batch_size=2,
            transport=TransportConfig(base_url=MOCK_BASE_URL),
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


def test_failed_delivery_preserves_queue_for_retry(
    respx_mock, mock_config_endpoint
):
    import httpx

    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.config import SDKConfig, TransportConfig
    from convert_sdk.core import Core
    from convert_sdk.errors import TrackingDeliveryError

    from .conftest import MOCK_BASE_URL

    # First POST fails (502), second succeeds (200) — RESPX side effect chain.
    route = respx_mock.post(f"/track/{SDK_KEY}").mock(
        side_effect=[
            httpx.Response(502, text="bad gateway"),
            httpx.Response(200, json={"status": "ok"}),
        ]
    )
    transport = HttpxTransport(TransportConfig(base_url=MOCK_BASE_URL))
    core = Core(
        SDKConfig(sdk_key=SDK_KEY, transport=TransportConfig(base_url=MOCK_BASE_URL)),
        transport=transport,
    ).initialize()
    try:
        core.create_context("v1").track_conversion("purchase_completed")
        # First flush surfaces the delivery error (no retry in tracking layer).
        try:
            core.flush()
        except TrackingDeliveryError:
            pass
        # The event was preserved; an explicit retry now succeeds.
        core.flush()
        assert route.call_count == 2
    finally:
        core.close()
