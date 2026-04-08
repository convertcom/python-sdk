"""Public configuration types for SDK initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


DEFAULT_CONFIG_ENDPOINT = "https://cdn-4.convertexperiments.com/api/v1"


@dataclass(frozen=True)
class TransportConfig:
    """Network configuration for config-fetch transport behavior."""

    config_endpoint: str = DEFAULT_CONFIG_ENDPOINT
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    verify_tls: bool = True


@dataclass(frozen=True)
class SDKConfig:
    """Pythonic SDK initialization config."""

    environment: Optional[str] = None
    sdk_key: Optional[str] = None
    sdk_key_secret: Optional[str] = None
    config_data: Optional[Mapping[str, Any]] = None
    transport: TransportConfig = field(default_factory=TransportConfig)
