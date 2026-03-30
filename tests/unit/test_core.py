from __future__ import annotations

from convertcom_sdk import ConvertSDK, SystemEvents
from convertcom_sdk.utils import HttpResponse


def test_convert_sdk_creates_context_from_static_config(config):
    sdk = ConvertSDK(config)

    context = sdk.create_context("visitor-1", {"browser": "chrome"})

    assert context is not None
    assert context.get_visitor_data() == {"segments": {"browser": "chrome"}}


def test_convert_sdk_fetches_config_from_sdk_key():
    requests = []

    def request_sender(*, method, base_url, route, headers, data):
        requests.append((method, base_url, route, headers, data))
        return HttpResponse(
            status=200,
            data={"account_id": "100", "project": {"id": "200"}, "features": []},
            headers={"Content-Type": "application/json"},
        )

    sdk = ConvertSDK(
        {
            "sdkKey": "100/200",
            "api": {"endpoint": {"config": "https://cdn.example.com"}},
        },
        request_sender=request_sender,
    )

    assert requests[0][2] == "/config/100/200?environment=staging"
    assert sdk.create_context("visitor-1") is not None


def test_core_fires_ready_event_for_static_config(config):
    sdk = ConvertSDK(config)
    received = []

    sdk.on(SystemEvents.READY, lambda args, err: received.append((args, err)))

    assert received == [(None, None)]
    assert sdk.on_ready() is None
