"""Privacy-safe logging helpers for the Convert Python SDK (Story 2.4).

Provides the SDK's configured stdlib :mod:`logging` logger and small, stable,
event-oriented log call sites for delivery outcomes (architecture
#Logging-Patterns). The phrasing is deliberately stable ("queue release",
"tracking delivery failure") and the operational context is restricted to
non-sensitive fields (release reason, batch size, HTTP status code, retry
count).

Privacy rule (NFR7/NFR23, Critical Warning #7): NO log line at any level may
contain the SDK key, full auth headers, or raw visitor attributes. These helpers
only ever accept and emit the safe fields above; they never receive a secret to
begin with. The centralized redaction primitives land in Story 4.1/4.2 — this
module must not regress that contract.
"""

from __future__ import annotations

import logging
from typing import Optional

#: The SDK's package logger. Applications configure handlers/levels on the
#: ``convert_sdk`` logger (or its parent) per standard stdlib logging.
logger = logging.getLogger("convert_sdk")


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
