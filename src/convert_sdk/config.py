"""Public initialization configuration for the Convert Python SDK (Story 1.2).

Two small, dependency-free config types describe how the SDK is initialized:

* :class:`SDKConfig` — *what* to load: either a remote ``sdk_key`` (config is
  fetched over HTTPS) or direct ``data`` (a preloaded config dict, no network).
* :class:`TransportConfig` — *how* to reach the config endpoint: base URL,
  timeout, optional auth secret, and extra headers.

Boundary validation is intentionally lightweight and ``pydantic``-free so the
core package stays dependency-minimal and Python 3.9+ compatible (per the
story's Technical Specifics). The only runtime dependency the SDK declares is
``httpx`` (see ``pyproject.toml``; bound ``>=0.28,<1.0`` per qs-09 F-060).

NFR8 (TLS-only transport) is enforced here: a non-HTTPS ``base_url`` raises
:class:`~convert_sdk.errors.TransportError` at construction time, before any
network I/O is possible (AC #4).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from convert_sdk.errors import InvalidConfigError, TransportError

# JS parity: the FullStack config-serving host. The route ``/config/{sdkKey}``
# is appended by the transport adapter (Story 1.2 / SDK-3).
DEFAULT_CONFIG_BASE_URL = "https://cdn-4.convertexperiments.com"

#: Cache levels mirrored from the JS SDK. ``"low"`` appends ``_conv_low_cache=1``
#: to the config route (JS parity: api-manager.ts getConfig()).
_VALID_CACHE_LEVELS = (None, "low")


@dataclass(frozen=True)
class TransportConfig:
    """Transport settings for fetching config over HTTPS.

    Args:
        base_url: HTTPS base URL of the config-serving endpoint. Must use the
            ``https`` scheme — a non-HTTPS URL raises :class:`TransportError`
            (NFR8 / AC #4).
        timeout: Request timeout in seconds.
        auth_secret: Optional bearer secret injected as an ``Authorization``
            header for authenticated keys.
        headers: Optional extra headers to send with the config request.
        verify_tls: Whether to verify TLS certificates. Defaults to ``True``.
    """

    base_url: str = DEFAULT_CONFIG_BASE_URL
    timeout: float = 10.0
    auth_secret: Optional[str] = None
    headers: Mapping[str, str] = field(default_factory=dict)
    verify_tls: bool = True

    def __post_init__(self) -> None:
        scheme = urlsplit(self.base_url).scheme.lower()
        if scheme != "https":
            # Enforced before any network I/O — TLS-only transport (NFR8).
            raise TransportError(
                "transport base_url must use HTTPS (TLS-only transport, NFR8); "
                f"got scheme={scheme!r}"
            )


@dataclass(frozen=True)
class SDKConfig:
    """Top-level SDK initialization configuration.

    Exactly one of ``sdk_key`` or ``data`` must be provided:

    * ``sdk_key`` — fetch config from the Convert serving endpoint over HTTPS.
    * ``data`` — initialize from a preloaded config dict with no network call.

    Args:
        sdk_key: The Convert SDK key used to fetch config remotely.
        data: A preloaded config payload for direct (offline) initialization.
        environment: Optional non-default environment. When set, the config
            route appends ``environment={environment}`` (JS parity).
        cache_level: Optional cache level. ``"low"`` appends
            ``_conv_low_cache=1`` to the config route (JS parity).
        transport: Transport settings used for ``sdk_key`` initialization.
        batch_size: Number of queued tracking events that triggers a batch-size
            queue release. Defaults to ``10`` — the JS SDK ``DEFAULT_BATCH_SIZE``
            for the events queue (``api-manager.ts`` ``batchSize``). Must be a
            positive integer (Story 2.3).
        auto_flush_interval_ms: Opt-in periodic-flush interval in milliseconds.
            ``None`` (the default) keeps the lifecycle explicit-flush-only —
            safe in every runtime. When set, a daemonic ``threading.Timer``
            periodically releases the queue (Story 2.3 / qs-07). Never made the
            default because a timed flush silently loses events in short-lived
            runtimes.
        data_store: Optional shared persistence adapter implementing the
            :class:`~convert_sdk.ports.storage.DataStore` protocol. Used for
            deduplication state; ``None`` selects the per-process in-memory
            default. ``enrichData`` is computed as ``data_store is None`` at
            serialization time (Story 2.2 F-002). Story 3.1 owns the full
            persistence boundary; this is the minimal hook dedup needs.
    """

    sdk_key: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    environment: Optional[str] = None
    cache_level: Optional[str] = None
    transport: TransportConfig = field(default_factory=TransportConfig)
    batch_size: int = 10
    auto_flush_interval_ms: Optional[int] = None
    data_store: Optional[Any] = None

    def __post_init__(self) -> None:
        has_key = self.sdk_key is not None
        has_data = self.data is not None

        if not has_key and not has_data:
            raise InvalidConfigError(
                "SDKConfig requires exactly one of 'sdk_key' or 'data'; neither "
                "was provided"
            )
        if has_key and has_data:
            raise InvalidConfigError(
                "SDKConfig accepts exactly one of 'sdk_key' or 'data'; both were "
                "provided"
            )
        if has_key and not str(self.sdk_key).strip():
            raise InvalidConfigError("SDKConfig 'sdk_key' must be a non-empty string")
        if has_data and not isinstance(self.data, dict):
            raise InvalidConfigError("SDKConfig 'data' must be a mapping/dict")
        if self.cache_level not in _VALID_CACHE_LEVELS:
            raise InvalidConfigError(
                f"SDKConfig 'cache_level' must be one of {_VALID_CACHE_LEVELS}; "
                f"got {self.cache_level!r}"
            )
        if not isinstance(self.batch_size, int) or self.batch_size < 1:
            raise InvalidConfigError(
                "SDKConfig 'batch_size' must be a positive integer; "
                f"got {self.batch_size!r}"
            )
        if self.auto_flush_interval_ms is not None and (
            not isinstance(self.auto_flush_interval_ms, int)
            or self.auto_flush_interval_ms < 1
        ):
            raise InvalidConfigError(
                "SDKConfig 'auto_flush_interval_ms' must be a positive integer "
                f"or None; got {self.auto_flush_interval_ms!r}"
            )

    @property
    def is_direct_config(self) -> bool:
        """True when initialization uses preloaded data (no network)."""
        return self.data is not None
