"""Story 1.3 — dedicated visitor-context creation & reuse tests.

These tests exercise the Story 1.3 acceptance criteria directly (rather than
incidentally through the 1-4/1-6 evaluation suites):

AC #1 — create a context with a visitor identifier and optional visitor
        attributes; the returned object is scoped to that visitor.
AC #2 — reuse the same context across multiple evaluations, and pass
        request-specific attributes at evaluation time without recreating the
        SDK and without mutating the stored context state.

They also pin the supporting guarantees from the Dev Notes: contexts are
caller-scoped (not cached by Core), creation requires an initialized SDK, the
context links to the current immutable snapshot, and stored visitor attributes
are read-only and defensively copied.
"""

from __future__ import annotations

import pytest

from convert_sdk import Context, Core, SDKConfig

CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "audiences": [
        {
            "id": "a1",
            "key": "us-only",
            "rules": {
                "OR": [
                    {
                        "AND": [
                            {
                                "OR_WHEN": [
                                    {
                                        "matching": {
                                            "match_type": "equals",
                                            "negated": False,
                                        },
                                        "key": "country",
                                        "value": "US",
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        }
    ],
    "experiences": [
        {
            "id": "e2",
            "key": "us-experience",
            "audiences": ["a1"],
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        }
    ],
}


def _ready_core() -> Core:
    return Core(SDKConfig(data=CONFIG)).initialize()


# --- AC #1: creation -------------------------------------------------------


def test_create_context_returns_visitor_scoped_context():
    ctx = _ready_core().create_context("visitor-1")
    assert isinstance(ctx, Context)
    assert ctx.visitor_id == "visitor-1"


def test_create_context_stores_visitor_attributes():
    ctx = _ready_core().create_context("visitor-1", visitor_attributes={"country": "US"})
    assert dict(ctx.visitor_attributes) == {"country": "US"}
    # Back-compat accessor exposes the same stored state.
    assert dict(ctx.attributes) == {"country": "US"}


def test_create_context_defaults_to_empty_attributes():
    ctx = _ready_core().create_context("visitor-1")
    assert dict(ctx.visitor_attributes) == {}


def test_stored_visitor_attributes_are_read_only():
    ctx = _ready_core().create_context("visitor-1", visitor_attributes={"country": "US"})
    with pytest.raises(TypeError):
        ctx.visitor_attributes["country"] = "DE"  # type: ignore[index]


def test_stored_visitor_attributes_copied_defensively():
    source = {"country": "US"}
    ctx = _ready_core().create_context("visitor-1", visitor_attributes=source)
    source["country"] = "DE"
    assert dict(ctx.visitor_attributes) == {"country": "US"}


def test_create_context_requires_initialized_sdk():
    core = Core(SDKConfig(data=CONFIG))  # not initialized
    with pytest.raises(RuntimeError):
        core.create_context("visitor-1")


# --- snapshot linkage ------------------------------------------------------


def test_context_links_to_current_snapshot():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    # The context evaluates against the Core's current immutable snapshot:
    # the experience declared in the Core's config resolves through the context.
    result = ctx.run_experience("us-experience")
    assert result is not None
    assert result.experience_key == "us-experience"
    # The Core still exposes that same immutable snapshot.
    assert core.current_config is not None
    assert any(
        exp.get("key") == "us-experience" for exp in core.current_config.experiences
    )


def test_two_contexts_share_snapshot_but_keep_separate_visitor_state():
    core = _ready_core()
    a = core.create_context("a", visitor_attributes={"country": "US"})
    b = core.create_context("b", visitor_attributes={"country": "CA"})
    # Distinct caller-scoped contexts with independent visitor state...
    assert a is not b
    assert a.visitor_id != b.visitor_id
    assert dict(a.visitor_attributes) != dict(b.visitor_attributes)
    # ...both evaluating against the same shared config (a qualifies, b does not),
    # proving the snapshot is shared, not duplicated or diverging per visitor.
    assert a.run_experience("us-experience") is not None
    assert b.run_experience("us-experience") is None


# --- AC #2: reuse across evaluations --------------------------------------


def test_context_reused_across_multiple_evaluations():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    # Same instance, repeated evaluations — no need to recreate Core or Context.
    first = ctx.run_experience("us-experience")
    second = ctx.run_experience("us-experience")
    assert first is not None and second is not None
    assert first.variation_id == second.variation_id  # deterministic + reusable


def test_core_does_not_cache_contexts():
    core = _ready_core()
    a = core.create_context("visitor-1")
    b = core.create_context("visitor-1")
    # Reuse comes from the caller holding the returned Context, not a Core cache.
    assert a is not b


# --- AC #2: request-time overlay does not mutate stored state -------------


def test_request_attributes_overlay_without_mutating_stored_state():
    core = _ready_core()
    # Stored attributes do NOT qualify for the US audience.
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "CA"})
    assert ctx.run_experience("us-experience") is None

    # A request-time overlay qualifies for this call only.
    overlaid = ctx.run_experience("us-experience", attributes={"country": "US"})
    assert overlaid is not None

    # The stored baseline is unchanged after the overlay call.
    assert dict(ctx.visitor_attributes) == {"country": "CA"}
    # A subsequent call without the overlay reverts to the stored (non-qualifying) state.
    assert ctx.run_experience("us-experience") is None


def test_request_overlay_merges_with_stored_attributes():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"plan": "pro", "country": "CA"})
    # Overlay overrides only the provided key; stored `plan` is still available
    # to evaluation, and the stored baseline remains intact afterwards.
    result = ctx.run_experience("us-experience", attributes={"country": "US"})
    assert result is not None
    assert dict(ctx.visitor_attributes) == {"plan": "pro", "country": "CA"}


# --- Story 3.2 AC #1: ContextState immutable update (with_attributes) -------


def test_context_state_with_attributes_returns_new_merged_state():
    from convert_sdk.domain.context_state import ContextState

    core = _ready_core()
    snapshot = core.current_config
    state = ContextState(
        visitor_id="v1",
        snapshot=snapshot,
        visitor_attributes={"country": "CA", "plan": "pro"},
    )
    updated = state.with_attributes({"country": "US", "tier": "gold"})
    # A NEW state object is returned (immutable update, not in-place).
    assert updated is not state
    # New keys override; untouched keys persist (deep/shallow key-merge).
    assert dict(updated.visitor_attributes) == {
        "country": "US",
        "plan": "pro",
        "tier": "gold",
    }
    # The ORIGINAL state is unchanged.
    assert dict(state.visitor_attributes) == {"country": "CA", "plan": "pro"}
    # Identity + snapshot carry over by reference (snapshot never copied).
    assert updated.visitor_id == "v1"
    assert updated.snapshot is state.snapshot


def test_context_state_with_attributes_does_not_touch_overlay_seam():
    from convert_sdk.domain.context_state import ContextState

    core = _ready_core()
    state = ContextState(
        visitor_id="v1",
        snapshot=core.current_config,
        visitor_attributes={"country": "CA"},
    )
    updated = state.with_attributes({"country": "US"})
    # with_overlay (the Story 1.3 ephemeral request-time seam) is unchanged and
    # distinct: it overlays per-call values onto the (now-updated) baseline
    # without mutating it.
    merged = updated.with_overlay({"country": "DE"})
    assert dict(merged) == {"country": "DE"}
    assert dict(updated.visitor_attributes) == {"country": "US"}


def test_context_state_with_attributes_noop_is_content_equal():
    from convert_sdk.domain.context_state import ContextState

    core = _ready_core()
    state = ContextState(
        visitor_id="v1",
        snapshot=core.current_config,
        visitor_attributes={"country": "US"},
    )
    same = state.with_attributes({"country": "US"})
    # A no-op update yields a state equal in content (determinism, AC #4).
    assert dict(same.visitor_attributes) == dict(state.visitor_attributes)


# --- Story 3.2 AC #1: Context.set_attributes public surface -----------------


def test_set_attributes_updates_stored_state_for_subsequent_evaluation():
    core = _ready_core()
    # Stored attributes do NOT qualify for the US audience.
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "CA"})
    assert ctx.run_experience("us-experience") is None

    # Persist a visitor-attribute update.
    result = ctx.set_attributes({"country": "US"})
    assert result is None  # returns None (AC #1 signature)

    # Subsequent evaluations on the SAME context use the UPDATED state.
    assert ctx.run_experience("us-experience") is not None
    assert dict(ctx.visitor_attributes) == {"country": "US"}


def test_set_attributes_merges_new_keys_over_existing():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"plan": "pro", "country": "CA"})
    ctx.set_attributes({"country": "US", "tier": "gold"})
    # New keys override touched keys; untouched keys persist.
    assert dict(ctx.visitor_attributes) == {
        "plan": "pro",
        "country": "US",
        "tier": "gold",
    }


def test_set_attributes_rebinds_state_without_in_place_mutation():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "CA"})
    original_state = ctx._state  # noqa: SLF001 — internal rebind assertion
    ctx.set_attributes({"country": "US"})
    # set_attributes rebinds the context's state to a NEW ContextState; it does
    # NOT mutate the original frozen instance in place (Critical Warning #2).
    assert ctx._state is not original_state  # noqa: SLF001
    assert dict(original_state.visitor_attributes) == {"country": "CA"}


def test_set_attributes_does_not_mutate_config_snapshot():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "CA"})
    snapshot_before = ctx._state.snapshot  # noqa: SLF001
    exp_keys_before = [e.get("key") for e in core.current_config.experiences]
    ctx.set_attributes({"country": "US"})
    # The shared immutable snapshot is never mutated or rebound by an attribute
    # update (Critical Warning #1) — same object, same contents.
    assert ctx._state.snapshot is snapshot_before  # noqa: SLF001
    assert [e.get("key") for e in core.current_config.experiences] == exp_keys_before
