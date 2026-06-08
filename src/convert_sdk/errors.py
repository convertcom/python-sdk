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

NFR23 redaction (qs-08 Reconciliation Note): ``ConfigLoadError`` /
``TrackingDeliveryError`` reduce endpoint URLs to ``host + path`` with the
entire query string elided and any config/tracking-route SDK key masked. Story
1.2 shipped this as a minimal INLINE shim; Story 4.1 (Task 3) REPOINTS those
call sites onto the centralized :func:`convert_sdk._internal.redaction.redact_url`
so there is exactly ONE redaction implementation in the codebase. This is a
behavior-preserving (equal-or-stricter) swap of the masking mechanism only —
the exception public contract is unchanged here (the full ``SafeContext``-based
message enrichment is Story 4.2).
"""

from __future__ import annotations

from typing import Optional

# Single source of redaction logic (qs-08): errors.py (L0) is permitted to
# import the L0 leaf ``_internal/`` utilities. Story 4.1 Task 3 replaces the
# former inline ``_redact_key``/``_redact_url`` shim with this primitive.
from convert_sdk._internal.redaction import redact_url as _redact_url


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
