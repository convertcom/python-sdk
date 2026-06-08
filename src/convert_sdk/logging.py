"""Privacy-safe logging helpers for the Convert Python SDK (Stories 2.4 + 4.1).

Provides the SDK's configured stdlib :mod:`logging` logger and small, stable,
event-oriented log call sites (architecture #Logging-Patterns). The phrasing is
deliberately stable and keyed off the :class:`~convert_sdk.events.LifecycleEvent`
vocabulary; the operational context is restricted to the NFR6 allowlist of
non-sensitive fields (lifecycle event name, config version, entity key, redacted
endpoint host, HTTP status code, batch size, retry count, queue release reason,
and a hashed/fingerprinted visitor reference).

Story 4.1 adds :func:`log_safe`, the single wrapper every SDK log call site uses.
It routes every value through the centralized
:mod:`convert_sdk._internal.redaction` primitives so redaction is applied
STRUCTURALLY at record-construction time — never relying on log level or a
downstream ``logging.Filter`` to gate sensitive data (qs-08 frozen decision).
The Story 2.4 helpers (:func:`log_queue_release_success`,
:func:`log_tracking_delivery_failure`, :func:`log_event_handler_error`) are
preserved unchanged; prior suites depend on them.

Privacy rule (NFR6/NFR7/NFR23): NO log line at any level may contain the SDK key,
full auth headers, raw visitor attributes, or the raw ``visitor_id``. Credentials
are OMITTED entirely from default output (NFR7 reconciliation); the only key
reference that may ever appear is the :func:`~convert_sdk._internal.redaction.redact_key`
masked shape, and even that is not routed through normal-flow logs.

Layering (architecture #Module-Dependency-Layering-enforced): this module may
import the L0 leaf ``_internal/`` utilities and the L0 ``LifecycleEvent`` enum,
but must NOT import ``adapters/``, transport, ``evaluation/``, ``tracking/``,
``context.py``, or ``core.py`` — logging is a low-level cross-cutting utility
consumed by higher layers; it must not pull the composition root inward.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from convert_sdk._internal.redaction import SafeContext, redact_key, redact_url
from convert_sdk.events import LifecycleEvent

#: The SDK's package logger. Applications configure handlers/levels on the
#: ``convert_sdk`` logger (or its parent) per standard stdlib logging.
logger = logging.getLogger("convert_sdk")

#: Kwarg names whose values are structurally redacted by :func:`log_safe` before
#: they ever reach a log record. A raw value passed under one of these names is
#: masked at record-construction time (defense in depth — never level-gated).
_URL_KWARGS = frozenset({"url", "endpoint"})
_KEY_KWARGS = frozenset({"key", "sdk_key", "auth", "authorization", "token", "secret"})
#: Field names that could carry raw PII if passed by mistake. They are
#: structurally replaced with ``[REDACTED]`` at record-construction time so a
#: raw ``visitor_id``/attribute value can never leak through ``log_safe`` even if
#: a future call site passes one under a PII-like name (NFR6 defense in depth —
#: correct call sites pass a hashed ``visitor`` reference instead).
_PII_KWARGS = frozenset(
    {"visitor_id", "attributes", "visitor_attributes", "email", "name"}
)
#: The structural PII placeholder (qs-08).
_REDACTED = "[REDACTED]"


def log_safe(
    event: LifecycleEvent,
    *,
    level: int = logging.INFO,
    target: Optional[logging.Logger] = None,
    context: Optional[SafeContext] = None,
    **fields: Any,
) -> None:
    """Emit one privacy-safe, event-oriented SDK log record.

    Builds a stable record from the ``event`` name (keyed off the
    :class:`~convert_sdk.events.LifecycleEvent` vocabulary — never a raw string
    literal) plus an optional :class:`SafeContext` and/or already-redacted
    ``fields`` kwargs. Every value is routed through the centralized redaction
    primitives BEFORE the record is constructed, so the same structural
    redaction applies at ALL levels (DEBUG is not a license to emit secrets/PII).

    Args:
        event: The lifecycle moment this record corresponds to.
        level: The stdlib logging level (default ``INFO`` for operational
            milestones; pass ``DEBUG`` for fine-grained diagnostics or
            ``WARNING``/``ERROR`` for recoverable failures).
        target: Optional caller-supplied logger (e.g. ``SDKConfig.logger``). When
            ``None`` the package ``convert_sdk`` namespace logger is used. The SDK
            only ever *emits* through this logger — it never configures it.
        context: Optional allowlist-only :class:`SafeContext` of operational
            fields. Its rendered fields are merged into the record.
        **fields: Additional allowlisted fields. Values under URL/key-like names
            (``url``/``endpoint`` and ``key``/``auth``/``token``/...) are
            structurally redacted; all other values are emitted as-is and MUST
            already be allowlist-safe (the caller is responsible for passing only
            NFR6-approved fields — e.g. a hashed visitor reference, never a raw
            ``visitor_id`` or attribute dict).
    """
    log = target if target is not None else logger
    # Cheap level guard: skip all field assembly if the record would be dropped.
    if not log.isEnabledFor(level):
        return

    parts = [f"event={event.value}"]
    if context is not None:
        for k, v in context.as_log_fields().items():
            parts.append(f"{k}={v}")
    for name, value in fields.items():
        parts.append(f"{name}={_redact_field(name, value)}")
    log.log(level, " ".join(parts))


def _redact_field(name: str, value: Any) -> Any:
    """Structurally redact a single ``log_safe`` field by its name.

    URL/endpoint values lose their query string (and any route key segment);
    key/secret/auth values are masked to the qs-08 shape. Everything else is
    returned unchanged (the caller must only pass allowlisted values).
    """
    if value is None:
        return value
    lname = name.lower()
    if lname in _URL_KWARGS:
        return redact_url(str(value))
    if lname in _KEY_KWARGS:
        return redact_key(str(value))
    if lname in _PII_KWARGS:
        return _REDACTED
    return value


def log_queue_release_success(*, reason: str, batch_size: int) -> None:
    """Log a successful queue release at DEBUG (stable event-oriented phrasing).

    Carries only the release ``reason`` and ``batch_size`` — no PII, no secrets.
    """
    logger.debug("queue release succeeded (reason=%s, batch_size=%d)", reason, batch_size)


def log_tracking_delivery_failure(
    *,
    reason: str,
    batch_size: int,
    status_code: Optional[int] = None,
    retry_attempts: Optional[int] = None,
) -> None:
    """Log a tracking-delivery failure at ERROR with privacy-safe context.

    Includes only ``reason``, ``batch_size``, the HTTP ``status_code`` (if any),
    and the ``retry_attempts`` count (NFR23). It NEVER includes the SDK key, auth
    headers, or raw visitor attributes (NFR7).
    """
    logger.error(
        "tracking delivery failure (reason=%s, batch_size=%d, status=%s, retry_attempts=%s)",
        reason,
        batch_size,
        status_code if status_code is not None else "n/a",
        retry_attempts if retry_attempts is not None else "n/a",
    )


def log_event_handler_error(*, event: str) -> None:
    """Log (at ERROR) that a lifecycle-event handler raised and was swallowed.

    Logs only the event name and the traceback (via ``exc_info``); it does not
    log the handler's arguments, so no payload PII or secrets leak. Used by the
    in-process EventBus to isolate a buggy integrator handler (Critical Warning
    #6 — parity with the JS ``EventManager.fire`` per-listener try/catch).
    """
    logger.error("lifecycle event handler raised and was swallowed (event=%s)", event, exc_info=True)
