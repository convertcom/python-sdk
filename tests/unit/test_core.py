from __future__ import annotations

import threading
import time

from convertcom_sdk import ConvertSDK, SystemEvents
from convertcom_sdk.utils import HttpResponse


def test_convert_sdk_creates_context_from_static_config(config):
    sdk = ConvertSDK(config)

    context = sdk.create_context("visitor-1", {"browser": "chrome"})

    assert context is not None
    assert context.get_visitor_data() == {"segments": {"browser": "chrome"}}


def test_convert_sdk_fetches_config_from_sdk_key():
    requests = []

    def request_sender(*, method, base_url, route, headers, data, **kwargs):
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


def test_core_auto_refreshes_and_can_be_closed():
    requests = []
    refreshed = threading.Event()

    def request_sender(*, method, base_url, route, headers, data, **kwargs):
        requests.append((method, base_url, route, headers, data, kwargs))
        if len(requests) >= 2:
            refreshed.set()
        return HttpResponse(
            status=200,
            data={"account_id": "100", "project": {"id": "200"}, "features": []},
            headers={"Content-Type": "application/json"},
        )

    sdk = ConvertSDK(
        {
            "sdkKey": "100/200",
            "api": {"endpoint": {"config": "https://cdn.example.com"}},
            "dataRefreshInterval": 50,
        },
        request_sender=request_sender,
    )

    assert refreshed.wait(1)
    sdk.close()
    count_after_close = len(requests)
    time.sleep(0.12)
    assert len(requests) == count_after_close


def test_core_close_stops_datastore_queue_timer(config):
    class FakeDataStore:
        def get(self, key):
            return None

        def set(self, key, value):
            return None

    sdk = ConvertSDK(
        {
            **config,
            "dataStore": FakeDataStore(),
            "events": {"batch_size": 10, "release_interval": 500},
        }
    )
    context = sdk.create_context("visitor-1")

    context.update_visitor_properties("visitor-1", {"country": "US"})

    assert sdk._data_manager.data_store_manager._requests_queue_timer is not None
    sdk.close()
    assert sdk._data_manager.data_store_manager._requests_queue_timer is None
