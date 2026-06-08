"""Centralized privacy-safe redaction primitives (Story 4.1, qs-08 — L0 leaf).

This module is the SINGLE source of redaction logic for the whole SDK. Every log
call site (via :mod:`convert_sdk.logging`) and every typed exception that
formats operational context (:mod:`convert_sdk.errors`) routes through these
primitives — no other module reimplements masking (qs-08 Critical Warning #3).

Layering (architecture #Module-Dependency-Layering-enforced): this is the L0
leaf utility. It imports **stdlib only** (``dataclasses``, ``typing``,
``urllib.parse``, ``hashlib``) and must NOT import ``errors.py``, ``logging.py``,
``ports/``, ``evaluation/``, ``tracking/``, ``adapters/``, ``context.py``, or
``core.py``. Everything else may import this module inward; it reaches back into
nothing.

Frozen qs-08 contract (do not weaken):

* :func:`redact_key` → first 4 + ``****`` + last 4 (``sdk_key_abcdef1234567890``
  → ``sdk_****_7890``); keys ≤ 8 chars collapse to a fully-masked ``****`` so a
  short key cannot be reconstructed from its mask.
* :func:`redact_url` → host + path with the ENTIRE query string elided (stricter
  than per-parameter stripping, so a newly-added credential parameter cannot
  leak before an allowlist is updated). Any ``/config/{key}`` or ``/track/{key}``
  path segment is additionally masked via :func:`redact_key`.
* :class:`SafeContext` carries ONLY the six approved operational fields and
  renders an allowlist-only mapping — it physically cannot hold a raw secret or
  PII field because none is defined on it.
* :func:`fingerprint_visitor` → a stable hashed reference (SHA-256 hex prefix),
  NEVER the raw ``visitor_id`` (NFR6 permits a hashed visitor reference and
  forbids the raw id).
"""

from __future__ import annotations

import dataclasses
import hashlib
import re
from dataclasses import dataclass
from typing import Dict, Optional
from urllib.parse import urlsplit

#: Matches the config/tracking routes' key segment so it can be masked in
#: diagnostics (the SDK key appears as the final path segment in both routes).
_CONFIG_ROUTE_RE = re.compile(r"(/(?:config|track)/)([^/?#]+)")

#: The fully-masked placeholder used for short/empty/absent keys.
_FULLY_MASKED = "****"

#: Length of the SHA-256 hex prefix used as a stable visitor fingerprint. A
#: 16-hex-char (64-bit) prefix is compact for logs while keeping collisions
#: vanishingly unlikely for diagnostic correlation.
_FINGERPRINT_LEN = 16


def redact_key(key: Optional[str]) -> str:
    """Mask an SDK key/secret to the frozen ``first4****last4`` shape.

    Keys of 8 characters or fewer (and ``None``/empty) collapse to ``****`` so
    the mask never reveals a majority of a short key. Long keys keep only their
    first and last four characters; the secret middle is replaced by ``****``.

    This is the canonical masked-shape primitive. Per the NFR7 reconciliation,
    default log/error output OMITS credentials entirely — this exists for the
    rare, deliberate case where a key reference must be shown, and is always
    equal-or-stricter than emitting the raw key.
    """
    if not key or len(key) <= 8:
        return _FULLY_MASKED
    # qs-08 frozen shape: first 4 + "****_" + last 4 (e.g.
    # "sdk_key_abcdef1234567890" -> "sdk_****_7890").
    return f"{key[:4]}{_FULLY_MASKED}_{key[-4:]}"


def redact_url(url: Optional[str]) -> Optional[str]:
    """Reduce a URL to ``host/path`` with the entire query string elided.

    Eliding the whole query string (rather than only named secret parameters)
    eliminates the risk of a new credential parameter leaking before an
    allowlist is updated (qs-08 stricter NFR23 interpretation). Any
    ``/config/{sdkKey}`` or ``/track/{sdkKey}`` path segment is additionally
    masked via :func:`redact_key` so a full SDK key never appears even at DEBUG.

    ``None`` passes through unchanged; a non-absolute value still has any query
    suffix stripped (defense in depth).
    """
    if not url:
        return url
    parts = urlsplit(url)
    host = parts.netloc or ""
    path = parts.path or ""
    # A recognizable absolute URL keeps host+path; otherwise strip any query
    # suffix from the raw value rather than emitting it verbatim.
    endpoint = f"{host}{path}" if host or path else url.split("?", 1)[0]
    return _CONFIG_ROUTE_RE.sub(
        lambda m: f"{m.group(1)}{redact_key(m.group(2))}", endpoint
    )


def fingerprint_visitor(visitor_id: str) -> str:
    """Return a stable hashed reference to a visitor — never the raw id.

    Computes a SHA-256 of the ``visitor_id`` and returns a stable hex prefix.
    NFR6's allowlist explicitly permits a hashed/fingerprinted visitor reference
    for log correlation and FORBIDS the raw ``visitor_id``. The result is
    deterministic (same input → same fingerprint) so diagnostic records for one
    visitor can be correlated without exposing identity.
    """
    digest = hashlib.sha256((visitor_id or "").encode("utf-8")).hexdigest()
    return digest[:_FINGERPRINT_LEN]


@dataclass(frozen=True)
class SafeContext:
    """Allowlist-only operational context for a log record or error message.

    Carries ONLY the six qs-08-approved operational fields — there is no field
    on this dataclass that could hold a raw secret or PII value, so it is
    structurally impossible to leak one through a ``SafeContext``. All fields
    are optional and default to ``None``; rendering omits the ``None`` fields.

    Approved fields (NFR6 allowlist subset for failure/diagnostic context):

    * ``endpoint`` — redacted host + path (no query); callers MUST pass an
      already-:func:`redact_url`-ed value.
    * ``status_code`` — HTTP status code.
    * ``config_version`` — the loaded config version identifier.
    * ``entity_key`` — experience/feature/goal key.
    * ``batch_size`` — number of events in a tracking batch.
    * ``retry_count`` — transport retry attempt count.
    """

    endpoint: Optional[str] = None
    status_code: Optional[int] = None
    config_version: Optional[str] = None
    entity_key: Optional[str] = None
    batch_size: Optional[int] = None
    retry_count: Optional[int] = None

    def as_log_fields(self) -> Dict[str, object]:
        """Render to a compact, allowlist-only field mapping (omits ``None``)."""
        fields: Dict[str, object] = {}
        for f in dataclasses.fields(self):
            value = getattr(self, f.name)
            if value is not None:
                fields[f.name] = value
        return fields

    def __str__(self) -> str:
        """Compact ``key=value`` rendering of the non-``None`` approved fields."""
        return ", ".join(f"{k}={v}" for k, v in self.as_log_fields().items())
