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

from typing import Optional
from urllib.parse import urlsplit


def _redact_url(url: Optional[str]) -> Optional[str]:
    """Reduce a URL to ``host/path`` with the entire query string stripped.

    This is the Story 1.2 inline redaction shim (qs-08). Stripping the whole
    query string — rather than only named secret parameters — eliminates the
    risk of a new credential parameter leaking before an allowlist is updated.
    """
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.netloc or ""
    path = parts.path or ""
    if host or path:
        return f"{host}{path}"
    # Not a recognizable absolute URL; return as-is (no query to leak).
    return url


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
