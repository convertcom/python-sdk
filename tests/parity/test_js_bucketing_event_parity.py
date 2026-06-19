"""JS wire-parity tests for the bucketing event payload (Story 2.5, AC#1).

Asserts that the Python ``build_bucketing_payload`` event bytes for a given
``(experienceId, variationId)`` pair match the JS ``VisitorTrackingEvents`` /
``BucketingEvent`` wire output frozen in the architecture spec.

Wire contract from ``architecture.md §"Bucketing Event Tracking Format"`` and
``../javascript-sdk/packages/types/src/config/types.gen.ts:2467-2497``:

    BucketingEvent:
        {"eventType": "bucketing", "data": {"experienceId": <str>, "variationId": <str>}}

    VisitorTrackingEvents wrapper (``types.gen.ts:2467-2473``):
        {eventType: "bucketing", data: BucketingEvent}

Invariants (negative assertions, ALL must hold):
- No ``timestamp`` at any level.
- No keys other than ``eventType`` and ``data`` on the event object.
- No keys other than ``experienceId`` and ``variationId`` inside ``data``.
- ``experienceId`` and ``variationId`` are string-typed (JS ``.toString()``).

These vectors are the frozen wire contract from the spec — they are authoritative
regardless of what the current Python implementation produces. If the impl drifts,
these tests fail. The fixture lives in
``tests/parity/fixtures/bucketing_event_vectors.json`` (alongside ``bucketing_vectors.json``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convert_sdk.config_loader import load_snapshot

# --- New symbols that don't exist yet (RED phase) ---------------------------
# Imported lazily inside helpers so pytest can collect tests and they fail with
# ImportError at run time rather than at collection time.


def _import_bucketing_event():
    """Lazy import of Story 2.5 BucketingEvent domain type."""
    from convert_sdk.domain.results import BucketingEvent
    return BucketingEvent


def _import_build_bucketing_payload():
    """Lazy import of Story 2.5 build_bucketing_payload serializer."""
    from convert_sdk.tracking.payloads import build_bucketing_payload
    return build_bucketing_payload


# Minimal snapshot stub — experienceId / variationId in the bucketing payload
# come from the event, not the snapshot, so the account/project fields are all
# that matters for this parity test.
_SNAPSHOT_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [],
    "features": [],
    "goals": [],
    "audiences": [],
    "segments": [],
}

_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / "bucketing_event_vectors.json").read_text(
        encoding="utf-8"
    )
)["vectors"]


@pytest.fixture(scope="module")
def snap():
    """Module-scoped snapshot — reused across all parametrized vector tests."""
    return load_snapshot(_SNAPSHOT_CONFIG)


def _serialize_event(vector, snap):
    """Serialize the bucketing event for one parity vector and return its wire dict.

    Shared by every parity test so the event-construction + payload-extraction
    setup lives in exactly one place (avoids the SonarCloud
    ``new_duplicated_lines_density`` gate — CPD is token-based, so each test body
    re-instantiating the builder would count as a duplicated block).
    """
    BucketingEvent = _import_bucketing_event()
    build_bucketing_payload = _import_build_bucketing_payload()
    event = BucketingEvent(
        visitor_id="test-visitor",
        experience_id=vector["experienceId"],
        variation_id=vector["variationId"],
    )
    payload = build_bucketing_payload(snap, event)
    return payload["visitors"][0]["events"][0]


# Single parametrize decorator reused by every vector test (one source of the
# vector list + id format, applied via the shared name below).
_over_vectors = pytest.mark.parametrize(
    "vector",
    _VECTORS,
    ids=[f"expId={v['experienceId']}:varId={v['variationId']}" for v in _VECTORS],
)


@_over_vectors
def test_bucketing_event_matches_js_wire_contract(vector, snap):
    """The Python-serialized bucketing event must match the JS wire contract exactly."""
    actual_event = _serialize_event(vector, snap)
    expected_event = vector["expected_event"]

    assert actual_event == expected_event, (
        f"bucketing event mismatch for "
        f"experienceId={vector['experienceId']!r} variationId={vector['variationId']!r}:\n"
        f"  python={actual_event!r}\n"
        f"  expected={expected_event!r}"
    )


@_over_vectors
def test_bucketing_event_has_no_extra_keys(vector, snap):
    """Negative parity: no timestamp, no extra keys beyond the frozen wire set."""
    actual_event = _serialize_event(vector, snap)

    assert set(actual_event.keys()) == {"eventType", "data"}
    assert set(actual_event["data"].keys()) == {"experienceId", "variationId"}
    assert "timestamp" not in actual_event
    assert "timestamp" not in actual_event["data"]


@_over_vectors
def test_bucketing_event_ids_are_string_typed(vector, snap):
    """experienceId and variationId on the wire must be str (JS .toString() parity)."""
    data = _serialize_event(vector, snap)["data"]

    assert isinstance(data["experienceId"], str)
    assert isinstance(data["variationId"], str)
