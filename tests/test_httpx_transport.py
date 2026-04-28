from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

import pytest

from convert_sdk import TransportConfig
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    @property
    def content(self) -> bytes:
        if self._payload is None:
            return b""
        return b"payload"

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


@dataclass
class RecordingClient:
    get_payload: Any = None
    post_payload: Any = None
    get_calls: List[Dict[str, Any]] = field(default_factory=list)
    post_calls: List[Dict[str, Any]] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        self.get_calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
            }
        )
        return FakeResponse(self.get_payload)

    def post(
        self,
        url: str,
        *,
        json: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        self.post_calls.append(
            {
                "url": url,
                "json": dict(json or {}),
                "headers": dict(headers or {}),
            }
        )
        return FakeResponse(self.post_payload)


def test_httpx_transport_uses_expected_route_headers_and_query() -> None:
    client = RecordingClient(
        get_payload={"account_id": "1001", "project": {"id": "2002"}},
    )
    transport = HttpxTransport(client=client)

    payload = transport.fetch_config(
        ConfigRequest(
            sdk_key="sdk-key-1001",
            sdk_key_secret="secret-value",
            environment="staging",
            transport=TransportConfig(
                config_endpoint="https://config.example.com/api/v1",
                headers={"X-Test": "1"},
            ),
        )
    )

    assert payload["project"]["id"] == "2002"
    assert client.get_calls == [
        {
            "url": "https://config.example.com/api/v1/config/sdk-key-1001",
            "params": {"environment": "staging"},
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-value",
                "X-Test": "1",
            },
        }
    ]


def test_httpx_transport_posts_tracking_payload_to_sdk_key_route() -> None:
    client = RecordingClient(post_payload={"ok": True})
    transport = HttpxTransport(client=client)

    result = transport.send_tracking(
        TrackingRequest(
            sdk_key="sdk-key-1001",
            sdk_key_secret="secret-value",
            account_id="1001",
            project_id="2002",
            payload={"visitors": []},
            transport=TransportConfig(
                tracking_endpoint="https://track.example.com/v1",
                headers={"X-Test": "1"},
            ),
        )
    )

    assert result == {"ok": True}
    assert client.post_calls == [
        {
            "url": "https://track.example.com/v1/track/sdk-key-1001",
            "json": {"visitors": []},
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-value",
                "Content-Type": "application/json",
                "X-Test": "1",
            },
        }
    ]


def test_httpx_transport_uses_account_project_tracking_route_without_sdk_key() -> None:
    client = RecordingClient(post_payload=None)
    transport = HttpxTransport(client=client)

    result = transport.send_tracking(
        TrackingRequest(
            sdk_key=None,
            sdk_key_secret=None,
            account_id="1001",
            project_id="2002",
            payload={"visitors": []},
            transport=TransportConfig(
                tracking_endpoint="https://track.example.com/v1",
            ),
        )
    )

    assert result == {}
    assert client.post_calls == [
        {
            "url": "https://track.example.com/v1/track/1001/2002",
            "json": {"visitors": []},
            "headers": {
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        }
    ]


def test_httpx_transport_rejects_non_object_json_payloads() -> None:
    transport = HttpxTransport(client=RecordingClient(get_payload=[]))

    with pytest.raises(TypeError, match="non-object JSON payload"):
        transport.fetch_config(
            ConfigRequest(
                sdk_key="sdk-key-1001",
                sdk_key_secret=None,
                environment=None,
                transport=TransportConfig(
                    config_endpoint="https://config.example.com/api/v1",
                ),
            )
        )
