"""Lifecycle event model for the Convert Python SDK (Story 2.4, L0 domain).

This is a **leaf type module** (architecture layer L0): it defines the
``LifecycleEvent`` enum and the typed event payload structures the higher
layers emit, and it imports **stdlib only**. It must NOT import ``tracking/``,
``ports/``, or ``adapters/`` — the layering is CI-enforced by ``import-linter``
(Critical Warning #9). Higher layers (``tracking/`` L2, ``core.py`` L4) consume
these types; this module never reaches back into them.

Enum identifiers are frozen by the PRD (``prd.md#API-Surface``) and aligned with
the JS ``SystemEvents`` parity subset:

* ``READY`` / ``CONFIG_UPDATED`` / ``BUCKETING`` are defined for completeness and
  JS parity but are emitted by the initialization/config and evaluation layers —
  Story 2.4 does NOT emit them (Critical Warning #12).
* ``CONVERSION`` is emitted from the tracking enqueue path on a tracked
  (non-suppressed) conversion.
* ``API_QUEUE_RELEASED`` is emitted from the single shared release path on every
  actual queue release (success or failure).
* ``DATA_STORE_QUEUE_RELEASED`` is defined for JS parity/completeness but is out
  of MVP scope here — another layer owns it.

Member values use the dot-separated wire-parity strings (``"config.updated"``,
``"api.queue.released"``, ``"datastore.queue.released"``) matching the current
PRD and the JS ``SystemEvents`` enum.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:  # pragma: no cover - typing only; no runtime cross-layer import
    # ``ReleaseReason`` lives in tracking/queue.py (L2). Importing it for real
    # would violate the L0 layering rule, so it is referenced under
    # TYPE_CHECKING only. ``ReleaseReason`` is a ``str`` enum, so the actual
    # value carried on the payload at emission time is also a valid ``str``.
    from convert_sdk.tracking.queue import ReleaseReason


class LifecycleEvent(enum.Enum):
    """Known SDK lifecycle events (never raw string literals — FR40).

    Member names use ``UPPER_SNAKE_CASE``; values are the stable, documented,
    JS-parity wire strings frozen by the PRD.
    """

    READY = "ready"
    CONFIG_UPDATED = "config.updated"
    BUCKETING = "bucketing"
    CONVERSION = "conversion"
    API_QUEUE_RELEASED = "api.queue.released"
    DATA_STORE_QUEUE_RELEASED = "datastore.queue.released"


@dataclass(frozen=True)
class ConversionEventPayload:
    """Domain-relevant context for a ``CONVERSION`` lifecycle event.

    Carries ONLY internal snake_case domain identity fields — never raw visitor
    attributes, the wire payload, or any transport object (Critical Warning #7,
    Task 4.3). Built directly from the in-process conversion event, not from the
    Story 2.2 wire serializer, so emission stays off the serialization path.
    """

    visitor_id: str
    goal_id: str
    goal_key: str


@dataclass(frozen=True)
class QueueReleasedPayload:
    """Diagnostic context for an ``API_QUEUE_RELEASED`` lifecycle event.

    Emitted once per actual queue release. On success it carries the typed
    release ``reason`` (Story 2.3's frozen ``ReleaseReason`` enum — reused, never
    redefined: F-062), the ``batch_size`` delivered, and per-visitor/event
    counts. On failure it additionally carries privacy-safe error context:
    ``status_code`` (HTTP status, if any) and ``retry_attempts`` (the transport
    adapter's exhausted retry count, or ``0``/``None`` when the adapter performs
    no retry). It NEVER carries the SDK key, auth headers, raw transport response
    bodies, or raw visitor attributes (NFR23/NFR7, Critical Warning #7).
    """

    reason: "ReleaseReason"
    batch_size: int
    visitor_count: int
    event_count: int
    # Failure-only diagnostic context (privacy-safe; absent on success).
    status_code: Optional[int] = None
    retry_attempts: Optional[int] = None
