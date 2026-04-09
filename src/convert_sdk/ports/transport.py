"""Transport protocol for config-loading and tracking behavior."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional, Protocol

from ..config import TransportConfig


@dataclass(frozen=True)
class ConfigRequest:
    """Request details for remote config loading."""

    sdk_key: str
    sdk_key_secret: Optional[str]
    environment: Optional[str]
    transport: TransportConfig


@dataclass(frozen=True)
class TrackingRequest:
    """Request details for tracking delivery."""

    sdk_key: Optional[str]
    sdk_key_secret: Optional[str]
    account_id: Optional[str]
    project_id: Optional[str]
    payload: Mapping[str, Any]
    transport: TransportConfig


class Transport(Protocol):
    """Protocol for SDK transport adapters."""

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        """Fetch and return the project config payload."""

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        """Send a tracking payload and return the transport response."""
