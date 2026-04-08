from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping

import pytest

from convert_sdk import TransportConfig
from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.ports.transport import ConfigRequest


class FakeResponse:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


@dataclass
class RecordingClient:
    payload: Any
    calls: List[Dict[str, Any]] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> FakeResponse:
        self.calls.append(
            {
                "url": url,
                "params": dict(params or {}),
                "headers": dict(headers or {}),
            }
        )
        return FakeResponse(self.payload)


def test_httpx_transport_uses_expected_route_headers_and_query() -> None:
    client = RecordingClient(
        payload={"account_id": "1001", "project": {"id": "2002"}},
    )
    transport = HttpxTransport(client=client)

    payload = transport.fetch_config(
        ConfigRequest(
            sdk_key="1001/2002",
            sdk_key_secret="secret-value",
            environment="staging",
            transport=TransportConfig(
                config_endpoint="https://config.example.com/api/v1",
                headers={"X-Test": "1"},
            ),
        )
    )

    assert payload["project"]["id"] == "2002"
    assert client.calls == [
        {
            "url": "https://config.example.com/api/v1/config/1001/2002",
            "params": {"environment": "staging"},
            "headers": {
                "Accept": "application/json",
                "Authorization": "Bearer secret-value",
                "X-Test": "1",
            },
        }
    ]


def test_httpx_transport_rejects_non_object_json_payloads() -> None:
    transport = HttpxTransport(client=RecordingClient(payload=[]))

    with pytest.raises(TypeError, match="non-object JSON payload"):
        transport.fetch_config(
            ConfigRequest(
                sdk_key="1001/2002",
                sdk_key_secret=None,
                environment=None,
                transport=TransportConfig(
                    config_endpoint="https://config.example.com/api/v1",
                ),
            )
        )
