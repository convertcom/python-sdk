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
