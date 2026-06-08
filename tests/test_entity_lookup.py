"""Story 3.4 — entity-lookup unit tests (SDK-2 resolver + SDK-3 Context surface).

Covers the read-only config entity-lookup surface (FR28):

* the L2 resolver ``evaluation/entity_lookup.py`` (by-key / by-id / multi-key),
* the public ``Context.get_config_entity`` / ``get_config_entities`` /
  ``get_config_entity_by_id`` delegating to it.

AC #1: a by-key/by-id/multi-key HIT returns the matching TYPED domain entity
resolved from the snapshot's precomputed index (the snapshot's own immutable
entity mapping — NOT a freshly built raw transport dict), as a pure read with no
network I/O and no mutation of the snapshot.

AC #2: a MISS (unknown key/id, known key under the wrong ``entity_type``, or an
unknown/unsupported ``entity_type``) returns a TYPED non-exception no-result —
``None`` for single lookups, an empty ``list`` for multi-key — never a raised
exception on a normal miss, never a sentinel string. The single-entity miss is
the documented Story-3.4 ``None``; Story 4.2 will later enrich that miss into the
FR50 typed-reason result WITHOUT changing the hit return shape.
"""

from __future__ import annotations

import pytest

from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.evaluation import entity_lookup


_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {"id": "e1", "key": "exp-one", "variations": [{"id": "v1", "key": "var-one"}]},
        {"id": "e2", "key": "exp-two", "variations": []},
    ],
    "features": [{"id": "f1", "key": "feat-one", "variables": []}],
    "goals": [{"id": "g1", "key": "goal-one"}, {"id": "g2", "key": "goal-two"}],
    "audiences": [{"id": "a1", "key": "aud-one"}],
    "segments": [{"id": "s1", "key": "seg-one"}],
}


@pytest.fixture
def snapshot():
    return load_snapshot(_CONFIG)


@pytest.fixture
def context(snapshot):
    # A Context built directly (no Core/tracker/store) is sufficient: entity
    # lookup is a pure read over the held immutable snapshot.
    return Context("visitor-lookup", snapshot)


# --- resolver: by-key -------------------------------------------------------


@pytest.mark.parametrize(
    "entity_type,key,expected_id",
    [
        ("experiences", "exp-one", "e1"),
        ("features", "feat-one", "f1"),
        ("goals", "goal-one", "g1"),
        ("audiences", "aud-one", "a1"),
        ("segments", "seg-one", "s1"),
    ],
)
def test_resolve_entity_by_key_hit_returns_typed_entity(
    snapshot, entity_type, key, expected_id
):
    entity = entity_lookup.resolve_entity(snapshot, entity_type, key)
    assert entity is not None
    assert entity["id"] == expected_id


def test_resolve_entity_returns_the_snapshot_object_not_a_raw_dict(snapshot):
    # AC #1: the resolver returns the snapshot's own indexed entity object (the
    # normalized internal model), identical to the snapshot accessor — not a
    # freshly built / raw transport dict.
    entity = entity_lookup.resolve_entity(snapshot, "experiences", "exp-one")
    assert entity is snapshot.get_experience_by_key("exp-one")


def test_resolve_entity_by_key_miss_returns_none(snapshot):
    assert entity_lookup.resolve_entity(snapshot, "experiences", "nope") is None


def test_resolve_entity_known_key_wrong_type_returns_none(snapshot):
    # "exp-one" is an experience key, not a goal key.
    assert entity_lookup.resolve_entity(snapshot, "goals", "exp-one") is None


def test_resolve_entity_unknown_entity_type_returns_none_no_raise(snapshot):
    # An unsupported entity_type is the same diagnosable no-result, never a crash.
    assert entity_lookup.resolve_entity(snapshot, "widgets", "exp-one") is None


# --- resolver: by-id --------------------------------------------------------


@pytest.mark.parametrize(
    "entity_type,entity_id,expected_key",
    [
        ("experiences", "e2", "exp-two"),
        ("features", "f1", "feat-one"),
        ("goals", "g2", "goal-two"),
        ("audiences", "a1", "aud-one"),
        ("segments", "s1", "seg-one"),
    ],
)
def test_resolve_entity_by_id_hit(snapshot, entity_type, entity_id, expected_key):
    entity = entity_lookup.resolve_entity_by_id(snapshot, entity_type, entity_id)
    assert entity is not None
    assert entity["key"] == expected_key


def test_resolve_entity_by_id_miss_returns_none(snapshot):
    assert entity_lookup.resolve_entity_by_id(snapshot, "goals", "nope") is None


def test_resolve_entity_by_id_unknown_type_returns_none(snapshot):
    assert entity_lookup.resolve_entity_by_id(snapshot, "widgets", "e1") is None


# --- resolver: multi-key ----------------------------------------------------


def test_resolve_entities_skips_unknown_keys(snapshot):
    result = entity_lookup.resolve_entities(
        snapshot, "experiences", ["exp-one", "missing", "exp-two"]
    )
    assert [e["id"] for e in result] == ["e1", "e2"]


def test_resolve_entities_empty_when_none_resolve(snapshot):
    assert entity_lookup.resolve_entities(snapshot, "experiences", ["x", "y"]) == []


def test_resolve_entities_unknown_type_is_empty(snapshot):
    assert entity_lookup.resolve_entities(snapshot, "widgets", ["exp-one"]) == []


def test_resolve_entities_empty_keys_is_empty(snapshot):
    assert entity_lookup.resolve_entities(snapshot, "experiences", []) == []


# --- read-only / no mutation ------------------------------------------------


def test_lookups_do_not_mutate_the_snapshot(snapshot):
    before_exp = snapshot.get_experience_by_key("exp-one")
    entity_lookup.resolve_entity(snapshot, "experiences", "exp-one")
    entity_lookup.resolve_entity_by_id(snapshot, "goals", "g1")
    entity_lookup.resolve_entities(snapshot, "segments", ["seg-one", "missing"])
    # Same object identity afterwards — the index/entity is untouched.
    assert snapshot.get_experience_by_key("exp-one") is before_exp


# --- public Context surface (SDK-3) -----------------------------------------


def test_context_get_config_entity_hit(context):
    entity = context.get_config_entity("experiences", "exp-one")
    assert entity is not None
    assert entity["id"] == "e1"


def test_context_get_config_entity_miss_returns_none(context):
    # Story 3.4 documented no-result. NOTE (Story 4.2 forward-compat seam):
    # Story 4.2 will replace this None with the FR50 typed-reason result object
    # ("entity not found in config") WITHOUT changing the hit return above.
    assert context.get_config_entity("experiences", "missing") is None


def test_context_get_config_entity_wrong_and_unknown_type_return_none(context):
    assert context.get_config_entity("goals", "exp-one") is None  # wrong type
    assert context.get_config_entity("widgets", "exp-one") is None  # unknown type


def test_context_get_config_entity_by_id(context):
    entity = context.get_config_entity_by_id("goals", "g2")
    assert entity is not None
    assert entity["key"] == "goal-two"
    assert context.get_config_entity_by_id("goals", "nope") is None


def test_context_get_config_entities_skips_unknown(context):
    result = context.get_config_entities("goals", ["goal-one", "nope", "goal-two"])
    assert [e["id"] for e in result] == ["g1", "g2"]
    assert context.get_config_entities("goals", ["nope"]) == []
