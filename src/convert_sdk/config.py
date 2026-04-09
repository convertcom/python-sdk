"""Public configuration types for SDK initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional


DEFAULT_CONFIG_ENDPOINT = "https://cdn-4.convertexperiments.com/api/v1"
DEFAULT_TRACKING_ENDPOINT = "https://metrics.convertexperiments.com/v1"


@dataclass(frozen=True)
class TransportConfig:
    """Network configuration for config-fetch and tracking behavior."""

    config_endpoint: str = DEFAULT_CONFIG_ENDPOINT
    tracking_endpoint: str = DEFAULT_TRACKING_ENDPOINT
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 5.0
    verify_tls: bool = True


@dataclass(frozen=True)
class TrackingConfig:
    """Queue configuration for conversion delivery behavior."""

    batch_size: int = 10
    source: str = "python-sdk"
    enrich_data: bool = True


@dataclass(frozen=True)
class SDKConfig:
    """Pythonic SDK initialization config."""

    environment: Optional[str] = None
    sdk_key: Optional[str] = None
    sdk_key_secret: Optional[str] = None
    config_data: Optional[Mapping[str, Any]] = None
    transport: TransportConfig = field(default_factory=TransportConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
