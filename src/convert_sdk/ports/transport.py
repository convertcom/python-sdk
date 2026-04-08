"""Transport protocol for config-loading behavior."""

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


class Transport(Protocol):
    """Protocol for SDK transport adapters."""

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        """Fetch and return the project config payload."""
