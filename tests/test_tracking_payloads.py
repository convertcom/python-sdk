"""Story 2.2 (SDK-3) — raw outbound payload assembly (``tracking/payloads.py``).

These tests pin the serialized outbound tracking payload to the verbose JS-SDK
wire contract, anchored against the JavaScript SDK reference types:

* Envelope ``SendTrackingEventsRequestData``
  (``packages/types/src/config/types.gen.ts:2428-2461``):
  ``{accountId, projectId, enrichData, source, visitors: [{visitorId, segments?, events}]}``.
* Event wrapper ``VisitorTrackingEvents`` (``types.gen.ts:2467-2474``):
  ``{eventType: "conversion", data: ConversionEvent}``.
* ``ConversionEvent`` (``types.gen.ts:2502-2530``):
  ``{goalId, goalData?: [{key, value}], bucketingData?: {expId: varId}}``.

Mapping rules enforced (F-001 / F-002 / AC#2):

* The wire event carries ONLY ``goalId`` / ``goalData`` / ``bucketingData`` —
  there is NO ``goalKey``, NO ``timestamp``, and NO ``conversionData`` field on
  the wire (F-001). Internal snake_case domain objects may hold richer data; the
  serializer maps only allowlisted keys.
* ``revenue`` maps to a ``goalData`` entry ``{"key": "amount", "value": <revenue>}``.
* Allowlisted ``conversion_data`` keys (``amount``, ``productsCount``,
  ``transactionId``, ``customDimension1``–``customDimension5``) map into
  ``goalData`` ``{key, value}`` entries; non-allowlisted keys are dropped from
  the wire (they never become a ``conversionData`` field).
* ``goalData`` / ``bucketingData`` are OMITTED entirely when empty (never ``null``
  or ``{}``).
* ``source`` is the module-level constant defaulting to ``"js-sdk"`` (F-002 — the
  ``"python-sdk"`` value is unverified against the backend allowlist).
* ``enrichData`` is COMPUTED as ``data_store is None`` (F-002), so it is ``True``
  today (no DataStore exists in the current stack).
"""

import json

from convert_sdk.config_loader import load_snapshot
from convert_sdk.domain.results import ConversionEvent
from convert_sdk.tracking.payloads import (
    TRACKING_SOURCE,
    build_tracking_payload,
)


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [],
    "features": [],
    "goals": [{"id": "g1", "key": "purchase_completed"}],
    "audiences": [],
    "segments": [],
}


def _snapshot():
    return load_snapshot(CONFIG)


def _event(**overrides):
    base = dict(
        visitor_id="visitor-1",
        goal_id="g1",
        goal_key="purchase_completed",
    )
    base.update(overrides)
    return ConversionEvent(**base)


# --- source / enrichData envelope semantics (F-002) ----------------------


def test_source_constant_defaults_to_js_sdk():
    # F-002: "python-sdk" is unverified against the backend allowlist; the safe
    # parity-anchored fallback is "js-sdk".
    assert TRACKING_SOURCE == "js-sdk"


def test_envelope_carries_account_project_source_enrichdata():
    snap = _snapshot()
    payload = build_tracking_payload(snap, _event())
    assert payload["accountId"] == "100123"
    assert payload["projectId"] == "200456"
    assert payload["source"] == "js-sdk"
    # enrichData is computed from DataStore presence; no store in the current
    # stack -> True. It must be a bool, not a literal/string.
    assert payload["enrichData"] is True


def test_enrich_data_is_computed_from_data_store_presence():
    snap = _snapshot()
    # No store -> True
    assert build_tracking_payload(snap, _event(), data_store=None)["enrichData"] is True
    # A present store -> False (computed, not hardcoded)
    sentinel_store = object()
    assert (
        build_tracking_payload(snap, _event(), data_store=sentinel_store)["enrichData"]
        is False
    )


# --- visitors[] / event wrapper shape ------------------------------------


def test_visitors_array_carries_visitor_id_and_events():
    snap = _snapshot()
    payload = build_tracking_payload(snap, _event())
    assert isinstance(payload["visitors"], list)
    assert len(payload["visitors"]) == 1
    visitor = payload["visitors"][0]
    assert visitor["visitorId"] == "visitor-1"
    assert isinstance(visitor["events"], list)
    assert len(visitor["events"]) == 1


def test_event_is_conversion_wrapper_with_data():
    snap = _snapshot()
    event = build_tracking_payload(snap, _event())["visitors"][0]["events"][0]
    assert event["eventType"] == "conversion"
    assert "data" in event
    assert event["data"]["goalId"] == "g1"


# --- F-001: forbidden wire fields ----------------------------------------


def test_wire_event_has_no_goal_key_timestamp_or_conversion_data():
    snap = _snapshot()
    event = build_tracking_payload(
        snap,
        _event(conversion_data={"transactionId": "tx-9"}),
    )["visitors"][0]["events"][0]
    data = event["data"]
    # F-001 / AC#2: the wire ConversionEvent has only goalId/goalData/bucketingData.
    assert "goalKey" not in data
    assert "timestamp" not in data
    assert "conversionData" not in data
    assert set(data.keys()) <= {"goalId", "goalData", "bucketingData"}


# --- goalData mapping -----------------------------------------------------


def test_revenue_maps_to_amount_goal_data_entry():
    snap = _snapshot()
    data = build_tracking_payload(snap, _event(revenue=42.5))["visitors"][0]["events"][
        0
    ]["data"]
    assert {"key": "amount", "value": 42.5} in data["goalData"]


def test_allowlisted_conversion_data_keys_map_into_goal_data():
    snap = _snapshot()
    data = build_tracking_payload(
        snap,
        _event(
            conversion_data={
                "transactionId": "tx-9",
                "productsCount": 3,
                "customDimension1": "blue",
            }
        ),
    )["visitors"][0]["events"][0]["data"]
    entries = {e["key"]: e["value"] for e in data["goalData"]}
    assert entries["transactionId"] == "tx-9"
    assert entries["productsCount"] == 3
    assert entries["customDimension1"] == "blue"


def test_non_allowlisted_conversion_data_keys_are_dropped_from_wire():
    snap = _snapshot()
    data = build_tracking_payload(
        snap,
        _event(conversion_data={"unknownKey": "x", "transactionId": "tx-1"}),
    )["visitors"][0]["events"][0]["data"]
    keys = {e["key"] for e in data["goalData"]}
    assert "unknownKey" not in keys
    assert "transactionId" in keys


def test_goal_data_omitted_entirely_when_no_revenue_or_attributes():
    snap = _snapshot()
    data = build_tracking_payload(snap, _event())["visitors"][0]["events"][0]["data"]
    # Omit (not null/[]/{}) when there is nothing to send.
    assert "goalData" not in data


# --- bucketingData mapping ------------------------------------------------


def test_bucketing_data_maps_experience_to_variation():
    snap = _snapshot()
    data = build_tracking_payload(
        snap,
        _event(bucketing_assignments={"e1": "v1", "e2": "v9"}),
    )["visitors"][0]["events"][0]["data"]
    assert data["bucketingData"] == {"e1": "v1", "e2": "v9"}


def test_bucketing_data_omitted_when_empty():
    snap = _snapshot()
    data = build_tracking_payload(
        snap, _event(bucketing_assignments=None)
    )["visitors"][0]["events"][0]["data"]
    assert "bucketingData" not in data


# --- segments on the visitor entry ---------------------------------------
#
# The wire ``segments`` field is the structured JS ``VisitorSegments`` type
# (types.gen.ts:2537-2573) with a FIXED key set — not a free-form dict of
# arbitrary visitor traits. The serializer filters to the allowlist so that
# non-segment attributes (e.g. an app-specific "plan" trait) never leak onto the
# wire and break NFR21 parity.


def test_visitor_segments_serialized_when_present():
    snap = _snapshot()
    visitor = build_tracking_payload(
        snap, _event(segments={"country": "US"})
    )["visitors"][0]
    assert visitor["segments"] == {"country": "US"}


def test_visitor_segments_filtered_to_visitor_segments_allowlist():
    # Non-VisitorSegments keys (raw visitor traits) are dropped from the wire.
    snap = _snapshot()
    visitor = build_tracking_payload(
        snap, _event(segments={"country": "US", "plan": "pro"})
    )["visitors"][0]
    assert visitor["segments"] == {"country": "US"}
    assert "plan" not in visitor["segments"]


def test_visitor_segments_omitted_when_no_allowlisted_key():
    # All-non-segment attributes -> the wire segments field is omitted entirely.
    snap = _snapshot()
    visitor = build_tracking_payload(
        snap, _event(segments={"plan": "pro"})
    )["visitors"][0]
    assert "segments" not in visitor


def test_visitor_segments_omitted_when_absent():
    snap = _snapshot()
    visitor = build_tracking_payload(snap, _event(segments=None))["visitors"][0]
    assert "segments" not in visitor


# --- NFR21 parity-style structural assertion -----------------------------


def test_payload_is_json_serializable_and_matches_js_sdk_field_set():
    snap = _snapshot()
    payload = build_tracking_payload(
        snap,
        _event(
            revenue=10.0,
            conversion_data={"transactionId": "tx-1"},
            bucketing_assignments={"e1": "v1"},
            segments={"country": "US"},
        ),
    )
    # Round-trips through JSON unchanged (no non-serializable values leak).
    assert json.loads(json.dumps(payload)) == payload

    # Envelope field set matches SendTrackingEventsRequestData.
    assert set(payload.keys()) == {"accountId", "projectId", "enrichData", "source", "visitors"}

    visitor = payload["visitors"][0]
    assert set(visitor.keys()) == {"visitorId", "segments", "events"}

    data = visitor["events"][0]["data"]
    # ConversionEvent: goalId + goalData (array of {key,value}) + bucketingData.
    assert data["goalId"] == "g1"
    assert all(set(entry.keys()) == {"key", "value"} for entry in data["goalData"])
    assert isinstance(data["bucketingData"], dict)
