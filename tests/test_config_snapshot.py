"""Story 1.2 — immutable config snapshot ingestion tests (SDK-2).

Covers boundary normalization/validation (``config_loader``) and the immutable
``ConfigSnapshot`` (``domain.config_snapshot``):

* Malformed config raises a typed :class:`InvalidConfigError` (AC #3).
* Valid config normalizes into an immutable snapshot (AC #1, FR26/FR27).
* The snapshot precomputes minimal entity key indexes so later stories can
  read the current config without mutating it in place.
* The snapshot cannot be mutated after creation (atomic-replacement model).
"""

import pytest

from convert_sdk.config_loader import load_snapshot, normalize_config, validate_config
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.errors import InvalidConfigError


MINIMAL_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456", "key": "proj-key"},
    "experiences": [
        {"id": "e1", "key": "exp-one", "variations": [{"id": "v1", "key": "var-one"}]},
        {"id": "e2", "key": "exp-two", "variations": []},
    ],
    "features": [
        {"id": "f1", "key": "feat-one", "variables": []},
    ],
    "goals": [{"id": "g1", "key": "goal-one"}],
    "audiences": [{"id": "a1", "key": "aud-one"}],
    "segments": [{"id": "s1", "key": "seg-one"}],
}


def test_validate_rejects_non_dict():
    with pytest.raises(InvalidConfigError):
        validate_config(["not", "a", "dict"])


def test_validate_rejects_missing_account_id():
    bad = {k: v for k, v in MINIMAL_CONFIG.items() if k != "account_id"}
    with pytest.raises(InvalidConfigError):
        validate_config(bad)


def test_validate_rejects_missing_project():
    bad = {k: v for k, v in MINIMAL_CONFIG.items() if k != "project"}
    with pytest.raises(InvalidConfigError):
        validate_config(bad)


def test_validate_accepts_minimal_config():
    # Should not raise.
    validate_config(MINIMAL_CONFIG)


def test_normalize_returns_internal_structure_not_raw_dict():
    normalized = normalize_config(MINIMAL_CONFIG)
    # Normalization must not return the same object reference (boundary copy).
    assert normalized is not MINIMAL_CONFIG
    assert normalized["account_id"] == "100123"
    # Collections always present as lists even if absent in input.
    sparse = {"account_id": "1", "project": {"id": "2"}}
    norm_sparse = normalize_config(sparse)
    assert norm_sparse["experiences"] == []
    assert norm_sparse["features"] == []


def test_load_snapshot_builds_config_snapshot():
    snap = load_snapshot(MINIMAL_CONFIG)
    assert isinstance(snap, ConfigSnapshot)
    assert snap.account_id == "100123"
    assert snap.project_id == "200456"


def test_load_snapshot_rejects_malformed_config():
    with pytest.raises(InvalidConfigError):
        load_snapshot({"experiences": []})  # missing account_id + project


def test_snapshot_precomputes_entity_key_indexes():
    snap = load_snapshot(MINIMAL_CONFIG)
    # Experiences indexed by key and id for O(1) lookup by later stories.
    assert snap.get_experience_by_key("exp-one")["id"] == "e1"
    assert snap.get_experience_by_id("e2")["key"] == "exp-two"
    assert snap.get_feature_by_key("feat-one")["id"] == "f1"
    # Missing key returns None (not an exception — read accessor).
    assert snap.get_experience_by_key("missing") is None


def test_snapshot_precomputes_goal_key_index():
    """Story 2.1 (SDK-1): goals are indexed by key for O(1) resolution at
    track-conversion time without scanning raw config (Critical Warning #4)."""
    snap = load_snapshot(MINIMAL_CONFIG)
    goal = snap.get_goal_by_key("goal-one")
    assert goal is not None
    assert goal["id"] == "g1"
    assert goal["key"] == "goal-one"
    # Unknown goal key returns None (read accessor, never raises).
    assert snap.get_goal_by_key("does-not-exist") is None


def test_snapshot_precomputes_goal_id_index():
    """Story 3.4 (SDK-1): goals indexed by id at construction so the by-id
    entity-lookup surface can resolve a goal by its id in O(1)."""
    snap = load_snapshot(MINIMAL_CONFIG)
    goal = snap.get_goal_by_id("g1")
    assert goal is not None
    assert goal["key"] == "goal-one"
    assert snap.get_goal_by_id("does-not-exist") is None


def test_snapshot_precomputes_segment_key_and_id_indexes():
    """Story 3.4 (SDK-1): segments indexed by key AND id at construction so the
    entity-lookup surface can resolve segments by either identity in O(1)."""
    snap = load_snapshot(MINIMAL_CONFIG)
    by_key = snap.get_segment_by_key("seg-one")
    assert by_key is not None
    assert by_key["id"] == "s1"
    by_id = snap.get_segment_by_id("s1")
    assert by_id is not None
    assert by_id["key"] == "seg-one"
    # Unknown identity returns None (read accessor, never raises).
    assert snap.get_segment_by_key("missing") is None
    assert snap.get_segment_by_id("missing") is None


def test_snapshot_index_accessors_are_read_only_mappings():
    """The new goal/segment indexes are immutable MappingProxyType, built once
    at construction (no per-lookup rebuild, no parallel mutable index)."""
    from types import MappingProxyType

    snap = load_snapshot(MINIMAL_CONFIG)
    assert isinstance(snap._goals_by_id, MappingProxyType)
    assert isinstance(snap._segments_by_key, MappingProxyType)
    assert isinstance(snap._segments_by_id, MappingProxyType)


def test_snapshot_is_immutable():
    snap = load_snapshot(MINIMAL_CONFIG)
    # Frozen dataclass — assigning an attribute must fail.
    with pytest.raises(Exception):
        snap.account_id = "tampered"  # type: ignore[misc]


def test_snapshot_does_not_alias_input_dict():
    """Mutating the original input dict must not affect the stored snapshot
    (boundary normalization stores internal copies, not references)."""
    cfg = {
        "account_id": "1",
        "project": {"id": "2"},
        "experiences": [{"id": "e1", "key": "exp", "variations": []}],
    }
    snap = load_snapshot(cfg)
    cfg["experiences"].append({"id": "e2", "key": "injected", "variations": []})
    assert snap.get_experience_by_key("injected") is None
    assert snap.get_experience_by_key("exp")["id"] == "e1"
