"""Story 1.3 — typed context-state foundation tests (SDK-1).

Covers the :class:`~convert_sdk.domain.context_state.ContextState` typed model
that keeps per-visitor state (identity + stored visitor attributes + a link to
the current immutable snapshot) separate from the shared
:class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`.

The model is internal domain plumbing (not part of the public import boundary).
It must:

* Store ``visitor_id`` and a defensively-copied, read-only ``visitor_attributes``
  mapping so caller-side mutation cannot leak in.
* Hold a reference to the current snapshot without copying or mutating it.
* Keep visitor state and snapshot state strictly separate (mutating visitor
  attributes — were it possible — must never touch the snapshot, and the
  snapshot is shared by reference, not duplicated per context).
* Provide an overlay helper that combines stored visitor attributes with
  request-specific attributes without mutating the stored baseline.
"""

from __future__ import annotations

import pytest

from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.domain.context_state import ContextState


def _snapshot() -> ConfigSnapshot:
    return ConfigSnapshot(account_id="100123", project_id="200456")


def test_context_state_stores_visitor_identity_and_attributes():
    state = ContextState(
        visitor_id="visitor-1",
        visitor_attributes={"country": "US"},
        snapshot=_snapshot(),
    )
    assert state.visitor_id == "visitor-1"
    assert dict(state.visitor_attributes) == {"country": "US"}


def test_context_state_defaults_to_empty_attributes():
    state = ContextState(visitor_id="v", snapshot=_snapshot())
    assert dict(state.visitor_attributes) == {}


def test_context_state_links_to_the_shared_snapshot_by_reference():
    snap = _snapshot()
    state = ContextState(visitor_id="v", snapshot=snap)
    # The snapshot is shared by reference, not copied per visitor.
    assert state.snapshot is snap


def test_visitor_attributes_are_copied_defensively():
    source = {"country": "US"}
    state = ContextState(visitor_id="v", visitor_attributes=source, snapshot=_snapshot())
    source["country"] = "DE"  # mutate the caller's dict after construction
    assert dict(state.visitor_attributes) == {"country": "US"}


def test_visitor_attributes_view_is_read_only():
    state = ContextState(
        visitor_id="v", visitor_attributes={"country": "US"}, snapshot=_snapshot()
    )
    with pytest.raises(TypeError):
        state.visitor_attributes["country"] = "DE"  # type: ignore[index]


def test_with_overlay_merges_without_mutating_baseline():
    state = ContextState(
        visitor_id="v", visitor_attributes={"country": "US", "plan": "pro"}, snapshot=_snapshot()
    )
    merged = state.with_overlay({"country": "DE"})
    # Per-call override wins; untouched keys preserved.
    assert dict(merged) == {"country": "DE", "plan": "pro"}
    # Baseline stored state is untouched.
    assert dict(state.visitor_attributes) == {"country": "US", "plan": "pro"}


def test_with_overlay_none_returns_baseline_view():
    state = ContextState(
        visitor_id="v", visitor_attributes={"country": "US"}, snapshot=_snapshot()
    )
    merged = state.with_overlay(None)
    assert dict(merged) == {"country": "US"}


def test_visitor_state_is_separate_from_snapshot():
    snap = _snapshot()
    state_a = ContextState(visitor_id="a", visitor_attributes={"x": 1}, snapshot=snap)
    state_b = ContextState(visitor_id="b", visitor_attributes={"x": 2}, snapshot=snap)
    # Two visitors share the same snapshot but keep independent visitor state.
    assert state_a.snapshot is state_b.snapshot
    assert dict(state_a.visitor_attributes) != dict(state_b.visitor_attributes)


# --- Story 3.3: distinct default_segments field + with_segments ------------


def test_default_segments_defaults_to_empty_and_is_distinct_from_attributes():
    state = ContextState(
        visitor_id="v", visitor_attributes={"country": "US"}, snapshot=_snapshot()
    )
    # Default segments are a DISTINCT field, empty by default, NEVER merged into
    # visitor_attributes (Critical Warning #7).
    assert dict(state.default_segments) == {}
    assert dict(state.visitor_attributes) == {"country": "US"}


def test_default_segments_view_is_read_only():
    state = ContextState(
        visitor_id="v",
        default_segments={"browser": "chrome"},
        snapshot=_snapshot(),
    )
    with pytest.raises(TypeError):
        state.default_segments["browser"] = "firefox"  # type: ignore[index]


def test_default_segments_are_copied_defensively():
    source = {"browser": "chrome"}
    state = ContextState(
        visitor_id="v", default_segments=source, snapshot=_snapshot()
    )
    source["browser"] = "firefox"  # mutate caller dict after construction
    assert dict(state.default_segments) == {"browser": "chrome"}


def test_with_segments_returns_new_state_and_does_not_mutate_original():
    state = ContextState(
        visitor_id="v",
        default_segments={"browser": "chrome"},
        snapshot=_snapshot(),
    )
    updated = state.with_segments({"country": "US"})
    # A NEW frozen state is returned; the original is unchanged (immutable rebind).
    assert updated is not state
    assert dict(state.default_segments) == {"browser": "chrome"}
    # New keys are merged in; untouched keys persist (shallow-merge parity).
    assert dict(updated.default_segments) == {"browser": "chrome", "country": "US"}


def test_with_segments_new_keys_override_existing():
    state = ContextState(
        visitor_id="v",
        default_segments={"browser": "chrome", "country": "DE"},
        snapshot=_snapshot(),
    )
    updated = state.with_segments({"country": "US"})
    assert dict(updated.default_segments) == {"browser": "chrome", "country": "US"}


def test_with_segments_does_not_touch_visitor_attributes():
    state = ContextState(
        visitor_id="v",
        visitor_attributes={"plan": "pro"},
        default_segments={"browser": "chrome"},
        snapshot=_snapshot(),
    )
    updated = state.with_segments({"country": "US"})
    # Segment update leaves visitor attributes entirely alone.
    assert dict(updated.visitor_attributes) == {"plan": "pro"}
    assert dict(updated.default_segments) == {"browser": "chrome", "country": "US"}


def test_with_segments_empty_is_content_equal_noop():
    state = ContextState(
        visitor_id="v",
        default_segments={"browser": "chrome"},
        snapshot=_snapshot(),
    )
    noop = state.with_segments({})
    # A no-op association yields a content-equal state (FR25 determinism).
    assert dict(noop.default_segments) == {"browser": "chrome"}
    assert dict(noop.visitor_attributes) == dict(state.visitor_attributes)


def test_with_segments_preserves_visitor_id_and_snapshot_by_reference():
    snap = _snapshot()
    state = ContextState(visitor_id="v", snapshot=snap)
    updated = state.with_segments({"browser": "chrome"})
    assert updated.visitor_id == "v"
    # Snapshot is shared by reference, never copied/mutated per visitor.
    assert updated.snapshot is snap


def test_context_state_equality_includes_segments():
    snap = _snapshot()
    a = ContextState(visitor_id="v", default_segments={"x": "1"}, snapshot=snap)
    b = ContextState(visitor_id="v", default_segments={"x": "1"}, snapshot=snap)
    c = ContextState(visitor_id="v", default_segments={"x": "2"}, snapshot=snap)
    assert a == b
    assert a != c
