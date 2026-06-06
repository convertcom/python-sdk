"""The SDK core orchestration surface (Story 1.2).

``Core`` is the public entry point for initialization, readiness, and current
config access. Story 1.1 froze the ``from convert_sdk import Core`` boundary as
an empty placeholder; Story 1.2 implements the first real behavior on top of it
without renaming the public surface.

Scope (Story 1.2): initialization (direct-config or ``sdkKey``), immutable
snapshot loading, and authoritative readiness state. ``Core`` does NOT implement
visitor-context creation, evaluation, bucketing, or tracking — those land in
later stories. The public API is sync-first for MVP.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional

from convert_sdk.config import SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.config_snapshot import ConfigSnapshot

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.ports.transport import Transport


class Core:
    """Public entry point and orchestration surface for the Convert Python SDK.

    Args:
        config: The :class:`~convert_sdk.config.SDKConfig` describing how to
            initialize (direct ``data`` or remote ``sdk_key``).
        transport: Optional transport implementation. When omitted and an
            ``sdk_key`` is configured, an httpx-backed transport is created
            lazily at initialization time. Direct-config initialization never
            constructs or uses a transport.
    """

    def __init__(self, config: SDKConfig, *, transport: Optional["Transport"] = None) -> None:
        self._config = config
        self._transport = transport
        self._owns_transport = False
        self._snapshot: Optional[ConfigSnapshot] = None
        self._ready = False

    # --- readiness & config access ----------------------------------------

    @property
    def is_ready(self) -> bool:
        """Authoritative readiness state. True only after a snapshot is loaded."""
        return self._ready

    @property
    def current_config(self) -> Optional[ConfigSnapshot]:
        """The current immutable config snapshot, or ``None`` if not ready."""
        return self._snapshot

    # --- initialization ----------------------------------------------------

    def initialize(self) -> "Core":
        """Initialize the SDK from direct config data or by fetching via sdkKey.

        Direct-config initialization makes no network call. ``sdkKey``
        initialization fetches config over HTTPS through the transport.

        Raises:
            InvalidConfigError: if the (direct or fetched) config is malformed.
            ConfigLoadError: if the config fetch fails.
            TransportError: if a transport cannot be established (e.g. a
                non-HTTPS base URL — though that is enforced earlier, at
                ``TransportConfig`` construction).
        """
        raw = self._load_raw_config()
        # load_snapshot validates + normalizes; any failure leaves us not-ready.
        self._snapshot = load_snapshot(raw)
        self._ready = True
        return self

    def _load_raw_config(self) -> Dict[str, Any]:
        if self._config.is_direct_config:
            # Direct config: no transport involved at all (AC #1).
            assert self._config.data is not None  # guaranteed by SDKConfig
            return self._config.data
        return self._fetch_via_transport()

    def _fetch_via_transport(self) -> Dict[str, Any]:
        transport = self._ensure_transport()
        return transport.fetch_config(self._config)

    def _ensure_transport(self) -> "Transport":
        if self._transport is None:
            # Lazy import keeps httpx out of the import path for direct-config
            # initialization.
            from convert_sdk.adapters.transport.httpx_transport import HttpxTransport

            self._transport = HttpxTransport(self._config.transport)
            self._owns_transport = True
        return self._transport

    # --- lifecycle ---------------------------------------------------------

    def close(self) -> None:
        """Release resources. Closes the transport only if Core created it."""
        if self._transport is not None and self._owns_transport:
            self._transport.close()
            self._transport = None
            self._owns_transport = False

    def __enter__(self) -> "Core":
        return self

    def __exit__(self, *exc: Any) -> bool:
        self.close()
        return False
