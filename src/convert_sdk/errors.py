"""Typed initialization and configuration errors for the Convert Python SDK.

Story 1.2 establishes a small, distinct exception hierarchy so that
initialization and config-fetch failures are *diagnosable* (NFR23) and clearly
*distinguishable* from the normal evaluation no-result outcomes that later
stories introduce. Per the Critical Warnings in the story, exceptions here are
only for initialization/config failures — never for future no-result
evaluation cases.

Hierarchy::

    ConvertSDKError                 (root for all SDK errors)
    ├── ConfigError                 (anything about config shape/loading)
    │   ├── InvalidConfigError      (malformed/invalid config data)
    │   └── ConfigLoadError         (a config *fetch* failed)
    └── TransportError              (transport/TLS configuration failures)

NFR23 redaction shim (qs-08 Reconciliation Note): until the centralized
``_internal/redaction.py`` primitives land in Story 4.1/4.2, ``ConfigLoadError``
applies a minimal inline redaction — endpoint URLs are reduced to ``host + path``
with the entire query string stripped, and raw SDK keys never appear in
messages. This is a deliberate forward-compatible bridge, not a violation of
NFR23.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import urlsplit

# Matches the config/tracking routes' key segment so it can be masked in
# diagnostics (the SDK key appears as the final path segment in both).
_CONFIG_ROUTE_RE = re.compile(r"(/(?:config|track)/)([^/?#]+)")


def _redact_key(key: str) -> str:
    """Mask an SDK key to ``first4***last4`` (qs-08 shape).

    Short keys (<= 8 chars) are fully masked to ``***`` so they cannot be
    reconstructed from the redacted form.
    """
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}***{key[-4:]}"


def _redact_url(url: Optional[str]) -> Optional[str]:
    """Reduce a URL to ``host/path`` with the query string stripped and any
    config-route SDK key masked.

    This is the Story 1.2 inline redaction shim (qs-08). Stripping the whole
    query string — rather than only named secret parameters — eliminates the
    risk of a new credential parameter leaking before an allowlist is updated.
    The ``/config/{sdkKey}`` path segment is additionally masked so a full SDK
    key never appears in an error message, even at DEBUG level.
    """
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.netloc or ""
    path = parts.path or ""
    if host or path:
        endpoint = f"{host}{path}"
    else:
        # Not a recognizable absolute URL; redact the raw value (no query).
        endpoint = url.split("?", 1)[0]
    # Mask any /config/{sdkKey} key segment.
    return _CONFIG_ROUTE_RE.sub(lambda m: f"{m.group(1)}{_redact_key(m.group(2))}", endpoint)


class ConvertSDKError(Exception):
    """Root for every error raised by the Convert Python SDK."""


class ConfigError(ConvertSDKError):
    """Base for configuration-shape and configuration-loading failures."""


class InvalidConfigError(ConfigError):
    """The provided initialization config or config payload is invalid.

    Raised for malformed direct-config data, missing/ambiguous initialization
    modes, or a config response that fails boundary validation.
    """


class ConfigLoadError(ConfigError):
    """A config *fetch* failed (network error, non-2xx response, bad body).

    The message uses a redacted endpoint (host + path, no query string) and an
    optional HTTP status code so failures are diagnosable without leaking
    secrets (NFR23 / qs-08 shim).
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.endpoint = _redact_url(endpoint)
        self.status_code = status_code
        detail_parts = []
        if self.endpoint is not None:
            detail_parts.append(f"endpoint={self.endpoint}")
        if self.status_code is not None:
            detail_parts.append(f"status={self.status_code}")
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        super().__init__(f"{message}{detail}")


class TransportError(ConvertSDKError):
    """A transport configuration or transport-layer failure.

    Notably raised when a non-HTTPS base URL is configured (AC #4 / NFR8):
    TLS-only transport is enforced at configuration time, before any network
    I/O is attempted.
    """


class TrackingDeliveryError(ConvertSDKError):
    """A tracking-events *delivery* attempt failed (Story 2.3).

    Raised by the transport adapter when a tracking POST fails (network error
    or non-2xx response). Distinct from :class:`TrackingError` — which is
    reserved for *programmer misuse* at enqueue time — because a delivery
    failure is an operational/transport condition. The message uses a redacted
    endpoint and optional status code (NFR23 / qs-08 shim), mirroring
    :class:`ConfigLoadError`, so a flush failure is diagnosable without leaking
    the SDK key or query string.

    This story does NOT add retry/backoff: the tracking layer calls the
    transport once per release and surfaces this error; the queue is left
    intact for a later explicit flush. Transport-level retries (if any) and
    delivery-outcome reporting are out of scope (Stories 2.4 / transport layer).
    """

    def __init__(
        self,
        message: str,
        *,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        self.endpoint = _redact_url(endpoint)
        self.status_code = status_code
        detail_parts = []
        if self.endpoint is not None:
            detail_parts.append(f"endpoint={self.endpoint}")
        if self.status_code is not None:
            detail_parts.append(f"status={self.status_code}")
        detail = f" ({', '.join(detail_parts)})" if detail_parts else ""
        super().__init__(f"{message}{detail}")


class TrackingError(ConvertSDKError):
    """Base for conversion-tracking *programmer-misuse* failures (Story 2.2).

    Tracking has two distinct failure modes that must never be conflated:

    * A *diagnosable no-result* — e.g. an unknown goal key — is **not** an
      exception. Story 2.1 models that as a typed ``GOAL_NOT_FOUND``
      :class:`~convert_sdk.domain.results.ConversionResult` (FR50) so callers
      tell it apart from success via ``status`` alone.
    * *Programmer misuse* — e.g. supplying conversion attributes the SDK cannot
      serialize — fails fast with a typed exception under this family, so it is
      diagnosable and distinguishable from a successful enqueue (NFR7/NFR23).

    Keeping a dedicated ``TrackingError`` base (separate from ``ConfigError``)
    means a caller can ``except TrackingError`` to catch tracking misuse without
    accidentally swallowing config/transport failures.
    """


class ConversionDataError(TrackingError):
    """A conversion attribute (``conversion_data`` value or revenue) is invalid.

    Raised at enqueue time when a ``conversion_data`` value is not a JSON
    primitive (nested objects/lists/arbitrary types are unsupported by the
    backend tracking contract). It is distinct from the Story 2.1 unknown-goal
    NON-EXCEPTION outcome (which is not an exception at all), so programmer
    misuse fails fast and is never mistaken for a successful conversion.

    NFR23 privacy: the error carries only the offending attribute *key* and a
    short safe *reason*. It deliberately never embeds the raw offending value,
    an SDK key, an auth header, or unrelated visitor PII — so the message and
    ``repr`` are safe to log at any level.
    """

    def __init__(self, key: str, *, reason: str) -> None:
        self.key = key
        self.reason = reason
        super().__init__(
            f"invalid conversion_data for key {key!r}: {reason}"
        )
