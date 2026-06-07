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
