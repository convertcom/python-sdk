"""Raw outbound tracking-payload assembly for the Convert Python SDK (Story 2.2).

This module is the SINGLE place that maps internal snake_case
:class:`~convert_sdk.domain.results.ConversionEvent` objects to the verbose
JS-SDK wire contract. Per the architecture data-boundary guardrail, the verbose
wire names (``accountId`` / ``projectId`` / ``goalId`` / ``goalData`` /
``bucketingData`` / ``enrichData`` / ``visitorId``) appear ONLY here — domain and
tracking-service code stay snake_case and never see raw transport dicts.

Wire contract (anchored against the JavaScript SDK reference types so NFR21
parity holds — Critical Warning #7):

* Envelope ``SendTrackingEventsRequestData``
  [`../javascript-sdk/packages/types/src/config/types.gen.ts:2428-2461`]::

      {
        "accountId": str,
        "projectId": str,
        "enrichData": bool,
        "source": str,
        "visitors": [ {visitorId, segments?, events} ]
      }

* Event wrapper ``VisitorTrackingEvents`` [`types.gen.ts:2467-2474`]::

      {"eventType": "conversion", "data": ConversionEvent}

* ``ConversionEvent`` [`types.gen.ts:2502-2530`]::

      {"goalId": str, "goalData"?: [{key, value}], "bucketingData"?: {expId: varId}}

Scope (Critical Warnings #1/#2): this module produces an in-memory serializable
structure only. It performs NO batching, deduplication, queue release, network
delivery, or ``force_multiple`` handling — those land in Stories 2.3 / 2.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional

from convert_sdk.domain.results import ConversionEvent

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


# F-002: the ``source`` value ``"python-sdk"`` is UNVERIFIED against the backend
# source allowlist; the JS/PHP SDKs default to ``"js-sdk"``. We ship the safe
# parity-anchored fallback as a module-level constant so a future flip (once the
# backend confirms a ``python-sdk`` allowlist entry) is a one-line change.
TRACKING_SOURCE: str = "js-sdk"

# The ``goalData`` key allowlist from the JS ``ConversionEvent`` type
# (`types.gen.ts:2509-2511`). Caller ``conversion_data`` keys outside this set
# are NOT part of the wire ``ConversionEvent`` contract and are dropped from the
# serialized payload (F-001: there is no free-form ``conversionData`` wire field).
_GOAL_DATA_KEYS = frozenset(
    {
        "amount",
        "productsCount",
        "transactionId",
        "customDimension1",
        "customDimension2",
        "customDimension3",
        "customDimension4",
        "customDimension5",
    }
)


def _build_goal_data(event: ConversionEvent) -> List[Dict[str, Any]]:
    """Build the ``goalData`` array of ``{key, value}`` entries for the wire.

    ``revenue`` maps to a ``{"key": "amount", "value": <revenue>}`` entry
    (matching the JS ``GoalData`` shape). Allowlisted ``conversion_data`` keys
    are emitted as their own entries; non-allowlisted keys are dropped (F-001 —
    the wire event has no free-form attribute field). ``revenue`` takes
    precedence over an ``amount`` supplied via ``conversion_data`` so a single
    ``amount`` entry is emitted.
    """
    entries: List[Dict[str, Any]] = []
    seen_amount = False

    if event.revenue is not None:
        entries.append({"key": "amount", "value": event.revenue})
        seen_amount = True

    if event.conversion_data:
        for key, value in event.conversion_data.items():
            if key not in _GOAL_DATA_KEYS:
                continue
            if key == "amount" and seen_amount:
                # revenue already produced the canonical amount entry.
                continue
            entries.append({"key": key, "value": value})
            if key == "amount":
                seen_amount = True

    return entries


def _build_conversion_event_data(event: ConversionEvent) -> Dict[str, Any]:
    """Serialize the internal event to the JS ``ConversionEvent`` wire shape.

    Emits ONLY ``goalId`` / ``goalData`` / ``bucketingData`` (F-001 / AC#2):
    no ``goalKey``, no ``timestamp``, no ``conversionData``. ``goalData`` and
    ``bucketingData`` are omitted entirely (never ``null`` / ``[]`` / ``{}``)
    when there is nothing to send (Critical Warning #4).
    """
    data: Dict[str, Any] = {"goalId": event.goal_id}

    goal_data = _build_goal_data(event)
    if goal_data:
        data["goalData"] = goal_data

    if event.bucketing_assignments:
        # experienceId -> variationId, a flat str->str map.
        data["bucketingData"] = {
            str(experience_id): str(variation_id)
            for experience_id, variation_id in event.bucketing_assignments.items()
        }

    return data


def _build_visitor_entry(event: ConversionEvent) -> Dict[str, Any]:
    """Build a single ``visitors[]`` entry: ``{visitorId, segments?, events}``."""
    visitor: Dict[str, Any] = {"visitorId": event.visitor_id}

    if event.segments:
        visitor["segments"] = dict(event.segments)

    visitor["events"] = [
        {
            "eventType": "conversion",
            "data": _build_conversion_event_data(event),
        }
    ]
    return visitor


def build_tracking_payload(
    snapshot: "ConfigSnapshot",
    event: ConversionEvent,
    *,
    data_store: Optional[Any] = None,
) -> Dict[str, Any]:
    """Assemble the verbose JS-SDK outbound tracking payload for one event.

    Args:
        snapshot: The immutable config snapshot supplying ``accountId`` /
            ``projectId``.
        event: The internal snake_case :class:`ConversionEvent` to serialize.
        data_store: The configured DataStore, if any. ``enrichData`` is COMPUTED
            as ``data_store is None`` (F-002), mirroring the JS SDK
            ``this._enrichData = !objectDeepValue(config, 'dataStore')``. No
            DataStore exists in the current stack (Story 3.1 owns it), so this
            computes to ``True`` today — but it is implemented as computed, not a
            literal, so the F-002 contract holds when 3.1 lands.

    Returns:
        A JSON-serializable ``dict`` matching ``SendTrackingEventsRequestData``.
        This is an in-memory structure only — no batching, queue, or network I/O
        happens here (Stories 2.3 / 2.4).
    """
    return {
        "accountId": snapshot.account_id,
        "projectId": snapshot.project_id,
        "enrichData": data_store is None,
        "source": TRACKING_SOURCE,
        "visitors": [_build_visitor_entry(event)],
    }
