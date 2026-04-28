"""Public configuration types for SDK initialization."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional

from .errors import ConfigValidationError


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

    def __post_init__(self) -> None:
        # Misconfigured policies silently corrupt long-running services.
        # Reject at construction time so the host gets a clean
        # ConfigValidationError instead of a worker that mysteriously
        # hammers the upstream, alerts immediately, or never alerts.
        #
        # Strict inequalities on backoff_max > backoff_initial and
        # backoff_factor > 1.0 are deliberate: equality on either field
        # makes the backoff cap unreachable in finite failures (factor=1)
        # or reachable on the very first failure (max=initial), both of
        # which break the terminal-callback contract the worker exposes.
        if self.interval_seconds < 1.0:
            # Sub-second refresh intervals hammer the upstream CDN at
            # near-loop speed and trigger rate-limiting; reject at
            # construction so the worker is never started this way.
            raise ConfigValidationError(
                "RefreshConfig.interval_seconds must be >= 1.0",
                code="refresh.invalid_interval",
                context={"interval_seconds": self.interval_seconds},
            )
        if self.jitter_seconds < 0:
            raise ConfigValidationError(
                "RefreshConfig.jitter_seconds must be >= 0",
                code="refresh.invalid_jitter",
                context={"jitter_seconds": self.jitter_seconds},
            )
        if self.jitter_seconds > self.interval_seconds:
            raise ConfigValidationError(
                "RefreshConfig.jitter_seconds must not exceed interval_seconds",
                code="refresh.invalid_jitter",
                context={
                    "jitter_seconds": self.jitter_seconds,
                    "interval_seconds": self.interval_seconds,
                },
            )
        if self.backoff_initial_seconds <= 0:
            raise ConfigValidationError(
                "RefreshConfig.backoff_initial_seconds must be > 0",
                code="refresh.invalid_backoff",
                context={"backoff_initial_seconds": self.backoff_initial_seconds},
            )
        if self.backoff_max_seconds <= self.backoff_initial_seconds:
            raise ConfigValidationError(
                "RefreshConfig.backoff_max_seconds must be > backoff_initial_seconds",
                code="refresh.invalid_backoff",
                context={
                    "backoff_initial_seconds": self.backoff_initial_seconds,
                    "backoff_max_seconds": self.backoff_max_seconds,
                },
            )
        if self.backoff_factor <= 1.0:
            raise ConfigValidationError(
                "RefreshConfig.backoff_factor must be > 1.0",
                code="refresh.invalid_backoff",
                context={"backoff_factor": self.backoff_factor},
            )


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
