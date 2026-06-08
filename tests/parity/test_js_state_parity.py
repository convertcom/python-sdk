"""Cross-SDK value-exact parity tests for Epic-3 state / entity-lookup + custom
segments (Story 3.5 / NFR20).

Each vector in ``fixtures/state_vectors.json`` pairs a config + a lookup or
custom-segment operation with the JS reference ``expected`` result,
machine-derived by ``scripts/generate_parity_fixtures.py`` from the JS
``DataManager.getEntity``/``getEntityById``/``getEntities`` and
``SegmentsManager`` reference. Each vector is fed through the Python SDK's REAL
surfaces:

* entity lookup via the public ``Context.get_config_entity`` /
  ``get_config_entities`` / ``get_config_entity_by_id`` (Story 3.4), and
* custom-segment selection via ``evaluation.segments.select_custom_segments``
  (Story 3.3).

The no-match contract is the Story-3.4 shipped form: JS ``null`` -> Python
``None`` (single) / empty ``list`` (multi); multi-key/id skips unknowns. This is
NOT the deferred FR50 typed-reason object.

Runs OFFLINE and JS-runtime-free: loads only the checked-in JSON (via the
``state_vectors`` conftest loader) and exercises the pure-Python SDK. On failure
the assertion names the fixture, entry id, expected-JS, actual-Python (AC #3).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.evaluation.segments import select_custom_segments

_FIXTURE = "state_vectors.json"
_VECTORS = json.loads(
    (Path(__file__).parent / "fixtures" / _FIXTURE).read_text(encoding="utf-8")
)["vectors"]


def _entity_id(entity):
    """Project a resolved Python entity to its id (or ``None`` for a miss)."""
    if entity is None:
        return None
    return str(entity["id"]) if entity.get("id") is not None else None


def _run_operation(vector):
    """Execute the vector's operation through the REAL Python surface."""
    snapshot = load_snapshot(vector["config"])
    op = vector["operation"]
    kind = op["op"]

    if kind in ("get_entity", "get_entity_by_id", "get_entities"):
        context = Context("visitor-state-parity", snapshot)
        if kind == "get_entity":
            return _entity_id(context.get_config_entity(op["entity_type"], op["key"]))
        if kind == "get_entity_by_id":
            return _entity_id(
                context.get_config_entity_by_id(op["entity_type"], op["id"])
            )
        # get_entities -> list of matched ids in order (skip-unknown)
        entities = context.get_config_entities(op["entity_type"], op["keys"])
        return [str(e["id"]) for e in entities]

    if kind == "select_custom_segments":
        return select_custom_segments(
            snapshot, op["segment_keys"], op["segment_rule"]
        )

    raise AssertionError(f"unknown operation in {_FIXTURE} [{vector['id']}]: {kind}")


@pytest.mark.parametrize("vector", _VECTORS, ids=[v["id"] for v in _VECTORS])
def test_state_and_entity_lookup_matches_js_reference(vector, state_vectors):
    """Python state/entity-lookup + segment output must equal the JS reference."""
    assert isinstance(state_vectors, list) and state_vectors

    actual = _run_operation(vector)
    assert actual == vector["expected"], (
        f"state parity divergence in {_FIXTURE} [{vector['id']}]: "
        f"op={vector['operation']!r} -> python={actual!r} != js={vector['expected']!r}"
    )
