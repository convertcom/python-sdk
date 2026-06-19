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

from convert_sdk.domain.results import BucketingEvent, ConversionEvent

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


# F-002: the ``source`` value ``"python-sdk"`` is UNVERIFIED against the backend
# source allowlist; the JS/PHP SDKs default to ``"js-sdk"``. We ship the safe
# parity-anchored fallback as a module-level constant so a future flip (once the
# backend confirms a ``python-sdk`` allowlist entry) is a one-line change.
TRACKING_SOURCE: str = "js-sdk"

# The ``VisitorSegments`` key allowlist from the JS type
# (`types.gen.ts:2537-2573`). The wire ``segments`` field is a STRUCTURED object
# with this fixed key set — NOT a free-form dict of arbitrary visitor traits.
# Raw caller attributes carried on the internal event for attribution are
# filtered to this allowlist at the serializer boundary so non-segment traits
# never leak onto the wire and break NFR21 parity. (Proper segment derivation
# lands with the persisted segment store in Story 3.3.)
_VISITOR_SEGMENT_KEYS = frozenset(
    {
        "browser",
        "devices",
        "source",
        "campaign",
        "visitorType",
        "country",
        "customSegments",
    }
)

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


def event_has_goal_data(event: ConversionEvent) -> bool:
    """Whether the event would serialize any ``goalData`` entries on the wire.

    Public predicate (Story 2.3) so the tracker can decide the transaction-send
    branch (F-006) using EXACTLY the serializer's notion of "has goalData" —
    revenue or any allowlisted ``conversion_data`` key — without reaching into a
    private serializer helper.
    """
    return bool(_build_goal_data(event))


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


def _build_visitor_segments(event: ConversionEvent) -> Dict[str, Any]:
    """Filter the internal attribution segments to the wire ``VisitorSegments``.

    The internal ``event.segments`` may carry richer caller attributes for
    attribution, but the wire ``segments`` field is the structured JS
    ``VisitorSegments`` type with a fixed key set. Only allowlisted keys are
    emitted; non-segment traits are dropped so they never reach the backend.
    """
    if not event.segments:
        return {}
    return {
        key: value
        for key, value in event.segments.items()
        if key in _VISITOR_SEGMENT_KEYS
    }


def _build_visitor_entry(event: ConversionEvent) -> Dict[str, Any]:
    """Build a single ``visitors[]`` entry: ``{visitorId, segments?, events}``."""
    visitor: Dict[str, Any] = {"visitorId": event.visitor_id}

    segments = _build_visitor_segments(event)
    if segments:
        # Omit entirely (never {}) when no allowlisted segment key is present.
        visitor["segments"] = segments

    visitor["events"] = [
        {
            "eventType": "conversion",
            "data": _build_conversion_event_data(event),
        }
    ]
    return visitor


def build_bucketing_payload(
    snapshot: "ConfigSnapshot",
    event: BucketingEvent,
    *,
    data_store: Optional[Any] = None,
) -> Dict[str, Any]:
    """Assemble the JS-SDK outbound bucketing-event payload for one bucketing activation.

    Wire contract anchored against ``types.gen.ts:2467-2473`` (VisitorTrackingEvents
    wrapper) and ``types.gen.ts:2486-2497`` (BucketingEvent body) and
    ``architecture.md §"Bucketing Event Tracking Format"``:

        {eventType: "bucketing", data: {experienceId: str, variationId: str}}

    No ``timestamp``, no extra keys beyond ``eventType`` and ``data``, no ``segments``
    on the visitor entry (bucketing events carry no segment attribution). The stable
    envelope fields (``accountId`` / ``projectId`` / ``source`` / ``enrichData``) are
    computed identically to :func:`build_tracking_payload` so a mixed batch serializes
    coherently through :meth:`~convert_sdk.tracking.tracker.Tracker._build_batch_payload`.

    Args:
        snapshot: The immutable config snapshot supplying ``accountId`` /
            ``projectId``.
        event: The internal snake_case :class:`~convert_sdk.domain.results.BucketingEvent`
            to serialize.
        data_store: The configured DataStore, if any. ``enrichData`` is computed as
            ``data_store is None`` (F-002 parity with :func:`build_tracking_payload`).

    Returns:
        A JSON-serializable ``dict`` matching the JS-SDK ``SendTrackingEventsRequestData``
        envelope with a single bucketing event entry. In-memory only — no batching,
        queue, or network I/O happens here.
    """
    return {
        "accountId": snapshot.account_id,
        "projectId": snapshot.project_id,
        "enrichData": data_store is None,
        "source": TRACKING_SOURCE,
        "visitors": [
            {
                "visitorId": event.visitor_id,
                "events": [
                    {
                        "eventType": "bucketing",
                        "data": {
                            "experienceId": str(event.experience_id),
                            "variationId": str(event.variation_id),
                        },
                    }
                ],
            }
        ],
    }


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
