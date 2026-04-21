from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, List, Mapping

import pytest

from convert_sdk import ConfigLoadError, ConfigValidationError, Core, SDKConfig, TransportConfig
from convert_sdk.ports.transport import ConfigRequest


def sample_config_payload() -> Mapping[str, Any]:
    return {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "experiences": [{"id": "3003", "key": "exp-home"}],
        "features": [{"id": "4004", "key": "feature-checkout"}],
        "goals": [{"id": "5005", "key": "purchase"}],
        "audiences": [{"id": "6006", "key": "vip-users"}],
    }


@dataclass
class FakeTransport:
    payload: Mapping[str, Any] | None = None
    error: Exception | None = None
    requests: List[ConfigRequest] = field(default_factory=list)

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        if self.payload is None:
            raise RuntimeError("No payload configured")
        return self.payload


def test_direct_config_initialization_avoids_transport_and_freezes_snapshot() -> None:
    transport = FakeTransport(payload=sample_config_payload())

    core = Core(SDKConfig(config_data=sample_config_payload()), transport=transport)

    assert core.is_ready is True
    assert transport.requests == []
    assert core.snapshot.project_id == "2002"
    assert "exp-home" in core.snapshot.experiences_by_key

    with pytest.raises(TypeError):
        core.snapshot.project["name"] = "changed"


def test_sdk_key_initialization_fetches_config_and_stores_snapshot() -> None:
    transport = FakeTransport(payload=sample_config_payload())
    config = SDKConfig(
        sdk_key="1001/2002",
        sdk_key_secret="secret-value",
        environment="staging",
        transport=TransportConfig(
            config_endpoint="https://config.example.com/api/v1",
            headers={"X-Request-Id": "story-1.2"},
            timeout_seconds=9.0,
        ),
    )

    core = Core(config, transport=transport)

    assert core.is_ready is True
    assert len(transport.requests) == 1
    request = transport.requests[0]
    assert request.sdk_key == "1001/2002"
    assert request.sdk_key_secret == "secret-value"
    assert request.environment == "staging"
    assert request.transport.config_endpoint == "https://config.example.com/api/v1"
    assert core.current_snapshot.features_by_key["feature-checkout"]["key"] == "feature-checkout"


def test_invalid_config_raises_typed_validation_error() -> None:
    with pytest.raises(
        ConfigValidationError,
        match="Provide exactly one of sdk_key or config_data",
    ):
        Core(SDKConfig())


def test_transport_failure_raises_typed_load_error() -> None:
    config = SDKConfig(
        sdk_key="1001/2002",
        transport=TransportConfig(config_endpoint="https://config.example.com/api/v1"),
    )
    transport = FakeTransport(error=RuntimeError("boom"))

    with pytest.raises(ConfigLoadError) as excinfo:
        Core(config, transport=transport)

    error = excinfo.value
    assert error.code == "config.fetch_failed"
    assert error.context["source"] == "sdk_key"
    assert error.context["endpoint_host"] == "config.example.com"
    assert "1001/2002" not in str(error)
