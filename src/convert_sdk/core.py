"""Public SDK entry point for initialization and readiness state."""

from __future__ import annotations

from typing import Optional

from .adapters.transport.httpx_transport import HttpxTransport
from .config import SDKConfig
from .config_loader.loader import load_config_snapshot
from .domain.config_snapshot import ConfigSnapshot
from .ports.transport import Transport

class Core:
    """Stable root export for SDK initialization and config access."""

    def __init__(
        self,
        config: SDKConfig,
        transport: Optional[Transport] = None,
    ) -> None:
        self._config = config
        self._snapshot: Optional[ConfigSnapshot] = None
        self._transport = transport
        self._initialize()

    def _initialize(self) -> None:
        self._snapshot = load_config_snapshot(
            self._config,
            transport=self._transport or HttpxTransport(),
        )

    @property
    def config(self) -> SDKConfig:
        """Return the initialization config used for the SDK instance."""

        return self._config

    @property
    def is_ready(self) -> bool:
        """Return whether the SDK has a current immutable config snapshot."""

        return self._snapshot is not None

    @property
    def snapshot(self) -> ConfigSnapshot:
        """Expose the current immutable config snapshot."""

        if self._snapshot is None:
            raise RuntimeError("Core is not ready")
        return self._snapshot

    @property
    def current_snapshot(self) -> ConfigSnapshot:
        """Alias for the current immutable config snapshot."""

        return self.snapshot

    def __repr__(self) -> str:
        return f"Core(is_ready={self.is_ready})"
