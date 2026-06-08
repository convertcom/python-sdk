"""Conversion event creation from a visitor context (Story 2.1).

:func:`create_conversion` is the first tracking-domain operation: it resolves a
goal by key from the current immutable :class:`ConfigSnapshot` and builds an
in-process :class:`ConversionEvent` associated with the visitor and the resolved
goal identity. It returns a typed :class:`ConversionResult` for **both**
outcomes — a successful enqueue (``QUEUED``) and an unknown goal key
(``GOAL_NOT_FOUND``).

Audit-corrected behavior (F-052 / FR50): an unknown goal key is a *diagnosable
NON-EXCEPTION* outcome, not programmer misuse. The miss is distinguishable from
success purely via :attr:`ConversionResult.status` so callers never need
``try``/``except`` to tell them apart.

Story 2.1 guardrails honored here:

* Goal resolution goes through the snapshot's precomputed index
  (:meth:`ConfigSnapshot.get_goal_by_key`) — never an ad-hoc raw-config scan
  (Critical Warning #4).
* No raw outbound payload assembly (Story 2.2 owns ``tracking/payloads.py``).
* No network I/O, batching, deduplication, or flush (later Epic 2 stories).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Mapping, Optional

from convert_sdk.domain.results import (
    ConversionEvent,
    ConversionResult,
    ConversionStatus,
)
from convert_sdk.errors import ConversionDataError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


# JSON primitive types the backend tracking contract accepts as conversion-data
# values. Nested objects/arrays and arbitrary Python objects are programmer
# misuse and fail fast (AC#3). ``bool`` is intentionally allowed and is checked
# before ``int`` would matter because ``bool`` is a JSON primitive too.
_JSON_PRIMITIVES = (str, int, float, bool, type(None))


def _validate_conversion_data(conversion_data: Optional[Mapping[str, Any]]) -> None:
    """Reject non-JSON-primitive ``conversion_data`` values (AC#3 / NFR7).

    Allows only ``str``/number/``bool``/``None`` values. Nested mappings,
    sequences, and arbitrary objects raise a typed :class:`ConversionDataError`
    naming the offending key with a safe reason — never echoing the raw value,
    SDK keys, auth headers, or PII (NFR23).
    """
    if not conversion_data:
        return
    for key, value in conversion_data.items():
        if not isinstance(value, _JSON_PRIMITIVES):
            raise ConversionDataError(
                str(key),
                reason="value must be a JSON primitive (string, number, bool, or null)",
            )


def _compute_bucketing_assignments(
    snapshot: "ConfigSnapshot",
    *,
    visitor_id: str,
    visitor_attributes: Optional[Mapping[str, Any]],
) -> Dict[str, str]:
    """Derive the visitor's active variation assignments at conversion time.

    Computed on demand from the immutable snapshot (no persisted bucketing store
    exists yet — Story 3.2 will own one). Returns an ``{experience_id:
    variation_id}`` map for every experience the visitor currently buckets into,
    which is the attribution context the wire ``bucketingData`` is built from.
    Reads only the snapshot + caller attributes; performs no I/O.
    """
    # Local import keeps the tracking <-> evaluation dependency one-directional
    # at module-load time while still sharing the bucketing logic (the
    # architecture forbids evaluation importing tracking, not the reverse).
    from convert_sdk.evaluation.experiences import select_experience

    assignments: Dict[str, str] = {}
    for experience in snapshot.experiences:
        key = experience.get("key")
        if key is None:
            continue
        result = select_experience(
            str(key),
            snapshot,
            visitor_id=visitor_id,
            visitor_attributes=visitor_attributes,
        )
        if result is not None:
            assignments[result.experience_id] = result.variation_id
    return assignments


def create_conversion(
    snapshot: "ConfigSnapshot",
    *,
    visitor_id: str,
    goal_key: str,
    revenue: Optional[float] = None,
    conversion_data: Optional[Mapping[str, Any]] = None,
    visitor_attributes: Optional[Mapping[str, Any]] = None,
    default_segments: Optional[Mapping[str, Any]] = None,
) -> ConversionResult:
    """Create an in-process conversion event for ``goal_key`` and ``visitor_id``.

    Story 2.2 extends Story 2.1's goal-key-only service with optional
    ``revenue``, caller-supplied ``conversion_data``, and the visitor's
    attribution context (active segments from ``visitor_attributes`` + active
    variation assignments computed from the snapshot at conversion time, FR34).

    ``conversion_data`` is validated FIRST — before goal resolution — so a bad
    value (non-JSON-primitive / nested) fails fast with a typed
    :class:`ConversionDataError` regardless of whether the goal exists.
    Programmer misuse is never silently downgraded to a no-result (Critical
    Warning #5).

    On a goal hit, builds a :class:`ConversionEvent` carrying the visitor, the
    stable goal identity, revenue/conversion_data, and the attribution context,
    and returns a ``QUEUED`` :class:`ConversionResult`. On a goal miss, returns
    a ``GOAL_NOT_FOUND`` result with no event (FR50) — never raises. Only the
    requested ``goal_key`` and the visitor's own id are echoed back, so the
    result is diagnosable without leaking config secrets or unrelated data.

    No wire-name mapping, payload serialization, batching, dedup, or network I/O
    happens here (those land in the serializer and later Epic 2 stories).
    """
    # Fail fast on programmer misuse before any goal resolution (AC#3).
    _validate_conversion_data(conversion_data)

    goal = snapshot.get_goal_by_key(goal_key)
    if goal is None:
        # FR50: typed, diagnosable, NON-EXCEPTION miss — distinguishable from
        # a successful enqueue purely by status.
        return ConversionResult(
            status=ConversionStatus.GOAL_NOT_FOUND,
            goal_key=goal_key,
            goal_id=None,
            visitor_id=visitor_id,
            event=None,
        )

    # Goals are indexed by key, so a resolved goal is guaranteed to have a key
    # but may (defensively) lack an id. Preserve the real id as a string; never
    # coerce a missing id into the literal "None", which would poison
    # downstream attribution and diagnosability.
    raw_goal_id = goal.get("id")
    goal_id = str(raw_goal_id) if raw_goal_id is not None else ""

    # Attribution context (FR34): active variation assignments computed from the
    # snapshot, and the visitor's active segments (its stored attributes — the
    # data segments are derived from in the current stack). Both are optional;
    # an empty bucketing map is preserved as ``None`` so the serializer omits it.
    bucketing_assignments = _compute_bucketing_assignments(
        snapshot, visitor_id=visitor_id, visitor_attributes=visitor_attributes
    )
    # Attribution segments: the visitor's attributes provide the legacy
    # attribute-derived segments; the visitor's associated DEFAULT segments
    # (Story 3.3 / FR14) are layered on top so the wire ``segments`` field
    # reflects the active default segments at conversion time. Default segments
    # are the explicit association, so they win on a key conflict. The serializer
    # (Story 2.2) filters the merged map to the VisitorSegments allowlist.
    merged_segments: Dict[str, Any] = {}
    if visitor_attributes:
        merged_segments.update(visitor_attributes)
    if default_segments:
        merged_segments.update(default_segments)
    segments = merged_segments or None

    event = ConversionEvent(
        visitor_id=visitor_id,
        goal_id=goal_id,
        goal_key=goal_key,
        revenue=revenue,
        conversion_data=conversion_data,
        segments=segments,
        bucketing_assignments=bucketing_assignments or None,
    )
    return ConversionResult(
        status=ConversionStatus.QUEUED,
        goal_key=goal_key,
        goal_id=goal_id,
        visitor_id=visitor_id,
        event=event,
    )
