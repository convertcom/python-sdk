"""Public initialization configuration for the Convert Python SDK (Story 1.2).

Two small, dependency-free config types describe how the SDK is initialized:

* :class:`SDKConfig` — *what* to load: either a remote ``sdk_key`` (config is
  fetched over HTTPS) or direct ``data`` (a preloaded config dict, no network).
* :class:`TransportConfig` — *how* to reach the config endpoint and the
  separate metrics tracking endpoint: base URL (config CDN), track_base_url
  (metrics host template), timeout, optional auth secret, and extra headers.

Boundary validation is intentionally lightweight and ``pydantic``-free so the
core package stays dependency-minimal and Python 3.9+ compatible (per the
story's Technical Specifics). The only runtime dependency the SDK declares is
``httpx`` (see ``pyproject.toml``; bound ``>=0.28,<1.0`` per qs-09 F-060).

NFR8 (TLS-only transport) is enforced here: a non-HTTPS ``base_url`` or
``track_base_url`` raises :class:`~convert_sdk.errors.TransportError` at
construction time, before any network I/O is possible (AC #4).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Mapping, Optional
from urllib.parse import urlsplit

from convert_sdk.errors import InvalidConfigError, TransportError

# The production Convert config-serving CDN host. The transport adapter appends
# the full route ``/api/v1/config/{sdkKey}`` (Story 1.2 / SDK-3), so this value
# must remain a pure host with no path component. The staging counterpart is
# ``https://cdn-4-staging.convertexperiments.com`` (same path convention).
DEFAULT_CONFIG_BASE_URL = "https://cdn-4.convertexperiments.com"

# The production Convert metrics host template for tracking delivery.
# The literal ``[project_id]`` placeholder is substituted with the real project
# id AT REQUEST TIME (JS parity: api-manager.ts line 224-228 uses
# ``this._trackEndpoint.replace('[project_id]', this._projectId.toString())``;
# PHP parity: ApiManager.php line 322 uses ``str_replace``).
# The transport adapter appends the route ``/track/{sdkKey}`` to the resolved
# host. Both JS (.env.example line 13) and PHP (DefaultConfig.php line 22) use
# this same default template string.
#
# There is NO staging-specific metrics host — the serving spec lists only the
# live host (metrics.convertexperiments.com) and a dev host. Staging tracking
# uses the same prod metrics host with the project id substituted.
DEFAULT_TRACK_BASE_URL = "https://[project_id].metrics.convertexperiments.com/v1"

#: Cache levels mirrored from the JS SDK. ``"low"`` appends ``_conv_low_cache=1``
#: to the config route (JS parity: api-manager.ts getConfig()).
_VALID_CACHE_LEVELS = (None, "low")


@dataclass(frozen=True)
class TransportConfig:
    """Transport settings for fetching config and delivering tracking events.

    Args:
        base_url: HTTPS base URL of the config-serving CDN endpoint (pure host,
            no path). Must use the ``https`` scheme — a non-HTTPS URL raises
            :class:`TransportError` (NFR8 / AC #4).
        track_base_url: HTTPS base URL template for the metrics tracking
            endpoint. The literal ``[project_id]`` placeholder is substituted
            with the real project id at request time (JS/PHP parity). Defaults
            to ``DEFAULT_TRACK_BASE_URL``. Must use the ``https`` scheme after
            the placeholder is considered a non-scheme segment, so the raw
            template string is checked for an ``https`` scheme here and the
            substitution never changes the scheme.
        timeout: Request timeout in seconds (applied to both config and tracking
            requests).
        auth_secret: Optional bearer secret injected as an ``Authorization``
            header for config fetch requests.
        headers: Optional extra headers to send with the config request.
        verify_tls: Whether to verify TLS certificates. Defaults to ``True``.
    """

    base_url: str = DEFAULT_CONFIG_BASE_URL
    track_base_url: str = DEFAULT_TRACK_BASE_URL
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
        # The track_base_url may contain the ``[project_id]`` placeholder
        # template, which is not a valid URI component and causes Python 3.13+'s
        # stricter urlsplit to raise ValueError ("Invalid IPv6 URL") when it
        # misparses the brackets. We extract the scheme by splitting on "://"
        # directly rather than calling urlsplit, which is safe because we only
        # need to verify the scheme prefix (not parse the full URL).
        raw_track = self.track_base_url
        track_scheme = raw_track.split("://", 1)[0].lower() if "://" in raw_track else ""
        if track_scheme != "https":
            raise TransportError(
                "transport track_base_url must use HTTPS (TLS-only transport, "
                f"NFR8); got scheme={track_scheme!r}"
            )


@dataclass(frozen=True)
class RefreshConfig:
    """Opt-in policy for post-MVP automatic config refresh (Story 5.2, FR31).

    Supplying a ``RefreshConfig`` on :attr:`SDKConfig.refresh` opts a remote
    (``sdk_key``) SDK instance into a background daemon thread that periodically
    re-fetches and atomically swaps the config snapshot. The default
    (``SDKConfig.refresh=None``) is byte-for-byte MVP behavior: no daemon thread,
    no diagnostic events, and zero added cost.

    Every concrete numeric default below is ratified in
    ``docs/adr/0001-config-refresh-concurrency-and-backoff.md`` (audit F-028 —
    architecture defers backoff parameters to a Phase-2 ADR).

    Args:
        interval_seconds: Base period between successful refresh attempts.
            Default ``300.0`` (5 minutes) — mirrors the JS SDK's default
            ``dataRefreshInterval`` of 300_000 ms, expressed in seconds. Must be
            ``> 0``.
        jitter_seconds: Maximum uniform random jitter added to each scheduled
            wait so a fleet of processes does not synchronize ("thundering
            herd"). Default ``30.0``. Must satisfy ``0 <= jitter <= interval``.
        backoff_factor: Multiplier applied to the wait after each consecutive
            transient failure (exponential backoff). Default ``2.0``. Must be
            ``>= 1.0``.
        backoff_max_seconds: Ceiling on the backed-off wait so a persistently
            failing endpoint is retried at a bounded cadence rather than a tight
            loop (AC-3). Default ``600.0`` (10 minutes). Must be ``>= interval``.
    """

    interval_seconds: float = 300.0
    jitter_seconds: float = 30.0
    backoff_factor: float = 2.0
    backoff_max_seconds: float = 600.0

    def __post_init__(self) -> None:
        if not isinstance(self.interval_seconds, (int, float)) or self.interval_seconds <= 0:
            raise InvalidConfigError(
                "RefreshConfig 'interval_seconds' must be a positive number; "
                f"got {self.interval_seconds!r}"
            )
        if (
            not isinstance(self.jitter_seconds, (int, float))
            or self.jitter_seconds < 0
            or self.jitter_seconds > self.interval_seconds
        ):
            raise InvalidConfigError(
                "RefreshConfig 'jitter_seconds' must be a number in "
                f"[0, interval_seconds]; got {self.jitter_seconds!r}"
            )
        if not isinstance(self.backoff_factor, (int, float)) or self.backoff_factor < 1.0:
            raise InvalidConfigError(
                "RefreshConfig 'backoff_factor' must be a number >= 1.0; "
                f"got {self.backoff_factor!r}"
            )
        if (
            not isinstance(self.backoff_max_seconds, (int, float))
            or self.backoff_max_seconds < self.interval_seconds
        ):
            raise InvalidConfigError(
                "RefreshConfig 'backoff_max_seconds' must be a number "
                ">= interval_seconds; "
                f"got {self.backoff_max_seconds!r}"
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
        logger: Optional caller-supplied :class:`logging.Logger` the SDK's
            diagnostic-logging layer emits through (Story 4.1). ``None`` (the
            default) means the SDK uses the package ``convert_sdk`` namespace
            logger (``logging.getLogger("convert_sdk")``). The SDK only ever
            *gets/uses* this logger — it NEVER calls ``logging.basicConfig()``,
            adds handlers, or sets the level (library logging discipline); the
            application owns handler/level configuration.
        refresh: Optional :class:`RefreshConfig` opting a remote (``sdk_key``)
            instance into post-MVP automatic config refresh (Story 5.2 / FR31).
            ``None`` (the default) preserves MVP behavior byte-for-byte: no
            daemon thread, no refresh events, no added cost. Supplying a policy
            in direct-config (``data``) mode spins up no worker — there is no
            remote endpoint to poll — and the SDK emits a ``refresh.skipped``
            diagnostic rather than silently ignoring the misconfiguration.
    """

    sdk_key: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
    environment: Optional[str] = None
    cache_level: Optional[str] = None
    transport: TransportConfig = field(default_factory=TransportConfig)
    batch_size: int = 10
    auto_flush_interval_ms: Optional[int] = None
    data_store: Optional[Any] = None
    logger: Optional[logging.Logger] = None
    refresh: Optional[RefreshConfig] = None

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
