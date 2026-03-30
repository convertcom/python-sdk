from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any

import pytest

from convertcom_sdk import ApiManager, EventManager, SystemEvents
from convertcom_sdk.utils import HttpError, HttpResponse


@dataclass
class RecordedRequest:
    method: str
    base_url: str
    route: str
    headers: dict[str, str]
    body: Any
    options: dict[str, Any] = field(default_factory=dict)


@dataclass
class RequestState:
    requests: list[RecordedRequest] = field(default_factory=list)
    response_status: int = 200
    response_body: Any = field(default_factory=dict)
    error: Exception | None = None


@pytest.fixture
def request_state():
    return RequestState()


@pytest.fixture
def request_sender(request_state):
    def sender(*, method, base_url, route, headers, data, **kwargs):
        request_state.requests.append(
            RecordedRequest(
                method=method,
                base_url=base_url,
                route=route,
                headers=dict(headers),
                body=data,
                options=dict(kwargs),
            )
        )
        if request_state.error:
            raise request_state.error
        return HttpResponse(
            status=request_state.response_status,
            data=request_state.response_body,
            headers={"Content-Type": "application/json"},
        )

    return sender


def test_request_posts_json_payload(request_state, request_sender):
    api_manager = ApiManager(request_sender=request_sender)
    payload = {"foo": "bar", "nested": {"value": 1}}

    response = api_manager.request(
        "post",
        {"base": "https://example.com", "route": "/test"},
        payload,
    )

    assert response.status == 200
    assert request_state.requests[0].route == "/test"
    assert request_state.requests[0].body == payload


def test_get_config_fetches_sdk_key_config(request_state, request_sender):
    request_state.response_body = {"account_id": "100", "project": {"id": "200"}}
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "environment": "staging",
            "api": {"endpoint": {"config": "https://cdn.example.com"}},
        },
        request_sender=request_sender,
    )

    data = api_manager.get_config()

    assert data == {"account_id": "100", "project": {"id": "200"}}
    assert request_state.requests[0].base_url == "https://cdn.example.com"
    assert request_state.requests[0].route == "/config/100/200?environment=staging"


def test_get_config_formats_low_cache_query(request_state, request_sender):
    request_state.response_body = {"account_id": "100", "project": {"id": "200"}}
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "environment": "staging",
            "network": {"cacheLevel": "low"},
            "api": {"endpoint": {"config": "https://cdn.example.com"}},
        },
        request_sender=request_sender,
    )

    api_manager.get_config()

    assert (
        request_state.requests[0].route
        == "/config/100/200?environment=staging&_conv_low_cache=1"
    )


def test_request_uses_network_timeout_and_retries(request_state, request_sender):
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "api": {"endpoint": {"config": "https://cdn.example.com"}},
            "network": {
                "requestTimeout": 3.5,
                "configRetries": 4,
                "trackRetries": 2,
                "retryBackoff": 0.25,
            },
        },
        request_sender=request_sender,
    )

    api_manager.get_config()

    recorded = request_state.requests[0]
    assert recorded.route == "/config/100/200"
    assert recorded.options["timeout"] == 3.5
    assert recorded.options["retries"] == 4
    assert recorded.options["retry_backoff"] == 0.25


def test_release_queue_groups_events_and_fires_size_event(request_state, request_sender):
    request_state.response_body = {"data": "ok"}
    event_manager = EventManager()
    released = []
    event = threading.Event()
    event_manager.on(
        SystemEvents.API_QUEUE_RELEASED,
        lambda args, err: (released.append((args, err)), event.set()),
    )
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "data": {"account_id": "100", "project": {"id": "200"}},
            "api": {"endpoint": {"track": "https://track.example.com"}},
            "events": {"batch_size": 2, "release_interval": 1000},
            "network": {"tracking": True, "source": "python-sdk"},
        },
        event_manager=event_manager,
        request_sender=request_sender,
    )

    api_manager.enqueue("visitor-1", {"eventType": "bucketing", "data": {"variationId": "1"}})
    api_manager.enqueue("visitor-1", {"eventType": "conversion", "data": {"goalId": "2"}})

    assert event.wait(1)
    request_body = request_state.requests[0].body
    assert request_state.requests[0].route == "/track/100/200"
    assert len(request_body["visitors"]) == 1
    assert request_body["visitors"][0]["visitorId"] == "visitor-1"
    assert len(request_body["visitors"][0]["events"]) == 2
    assert released[0][0]["reason"] == "size"
    assert released[0][0]["result"].data == {"data": "ok"}
    assert released[0][1] is None


def test_release_queue_on_timeout(request_state, request_sender):
    event_manager = EventManager()
    released = []
    event = threading.Event()
    event_manager.on(
        SystemEvents.API_QUEUE_RELEASED,
        lambda args, err: (released.append((args, err)), event.set()),
    )
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "data": {"account_id": "100", "project": {"id": "200"}},
            "api": {"endpoint": {"track": "https://track.example.com"}},
            "events": {"batch_size": 5, "release_interval": 50},
            "network": {"tracking": True},
        },
        event_manager=event_manager,
        request_sender=request_sender,
    )

    api_manager.enqueue("visitor-1", {"eventType": "bucketing", "data": {"variationId": "1"}})
    api_manager.enqueue("visitor-2", {"eventType": "bucketing", "data": {"variationId": "2"}})

    assert event.wait(1)
    assert released[0][0]["reason"] == "timeout"
    assert len(request_state.requests[0].body["visitors"]) == 2


def test_release_queue_error_fires_event_and_preserves_queue(request_state, request_sender):
    request_state.error = HttpError(500, {}, {"Content-Type": "application/json"})
    event_manager = EventManager()
    released = []
    event = threading.Event()
    event_manager.on(
        SystemEvents.API_QUEUE_RELEASED,
        lambda args, err: (released.append((args, err)), event.set()),
    )
    api_manager = ApiManager(
        {
            "sdkKey": "100/200",
            "data": {"account_id": "100", "project": {"id": "200"}},
            "api": {"endpoint": {"track": "https://track.example.com"}},
            "events": {"batch_size": 2, "release_interval": 1000},
            "network": {"tracking": True},
        },
        event_manager=event_manager,
        request_sender=request_sender,
    )

    api_manager.enqueue("visitor-1", {"eventType": "bucketing", "data": {"variationId": "1"}})
    api_manager.enqueue("visitor-2", {"eventType": "bucketing", "data": {"variationId": "2"}})

    assert event.wait(1)
    api_manager.stop_queue()
    assert released[0][0]["reason"] == "size"
    assert released[0][1].status == 500
    assert api_manager._requests_queue.length == 2
