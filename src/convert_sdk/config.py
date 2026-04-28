"""Public configuration types for SDK initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional


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
class RefreshConfig:
    """Opt-in policy for background config refresh in long-running services.

    Defaults are tuned for typical web-service deployments: refresh every
    5 minutes with up to 30s of jitter to avoid herding multiple instances
    onto the same fetch tick. Failures back off exponentially up to a 10
    minute cap; the worker never gives up but never tight-loops either.

    Setting ``SDKConfig.refresh`` to a ``RefreshConfig`` enables a daemon
    thread inside ``Core``. The default ``SDKConfig.refresh = None``
    preserves MVP behaviour byte-for-byte: no background activity runs.

    Refresh requires an ``sdk_key``-initialised ``Core``; an instance
    initialised from ``config_data`` is local-only and has no remote
    endpoint to refresh from.
    """

    interval_seconds: float = 300.0
    jitter_seconds: float = 30.0
    backoff_initial_seconds: float = 30.0
    backoff_max_seconds: float = 600.0
    backoff_factor: float = 2.0
    on_terminal_failure: Optional[Callable[[Exception], None]] = None


@dataclass(frozen=True)
class SDKConfig:
    """Pythonic SDK initialization config."""

    environment: Optional[str] = None
    sdk_key: Optional[str] = None
    sdk_key_secret: Optional[str] = None
    config_data: Optional[Mapping[str, Any]] = None
    transport: TransportConfig = field(default_factory=TransportConfig)
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    refresh: Optional[RefreshConfig] = None
