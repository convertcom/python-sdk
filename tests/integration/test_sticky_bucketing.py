"""qs-03 PY-3 -- sticky-bucketing persistence wiring into ``run_experience``/
``run_experiences`` (RED phase).

PY-1 (``ContextState.bucketing`` + ``with_bucketing`` + the 3-key
``{"attributes","segments","bucketing"}`` persist/hydrate envelope) and PY-2
(``select_experience``'s pure ``sticky_bucketing`` read-back kwarg) are
substrate-only: neither wires a real decision into the evaluation call path.
This file exercises the NOT-YET-IMPLEMENTED PY-3 contract end to end through
the public ``Context`` surface:

* AC1 (row1) -- a fresh ``run_experience`` call hashes normally AND persists
  the bucketing decision (in-memory ``ContextState.bucketing`` AND the
  injected ``DataStore``, as the full 3-key envelope).
* AC2 (row2) -- a second call on the SAME context returns the SAME variation
  WITHOUT invoking the bucketing hash again and WITHOUT re-writing the store.
* AC3 (row3) -- the stored decision survives a traffic reallocation that would
  otherwise flip a fresh hash's outcome, as long as the stored variation id
  still resolves in the (re-served) config. There is no in-place "swap this
  context's snapshot" seam (a ``Context``'s ``ConfigSnapshot`` is immutable and
  captured once at construction; ``Core.refresh_now()`` is a documented no-op
  in direct-config/``data=`` mode -- see ``src/convert_sdk/core.py``
  ``refresh_now``). The closest faithful simulation is a SECOND ``Core``/
  ``Context`` sharing the SAME ``DataStore`` and visitor id but built from a
  reallocated config -- exactly the fallback the qs-03 spec calls out, and the
  same hydration seam PY-1 already wired (``Core._hydrate_visitor_state``).
  Logged as a decision-log entry (see the feature's ``decision-log.md``).
* AC5 (row5) -- once a preview is active on the context (targeting a
  DIFFERENT, non-run experience), a normal run of an unrelated experience
  decides normally but persists ZERO bucketing entries.
* AC6 (row6) -- ``enable_storage=False`` suppresses ONLY the bucketing
  persist for that call; an unrelated ``set_attributes`` write on the same
  context is unaffected.
* AC8 (row8) -- a stored decision does not resurrect a result for a visitor
  who no longer qualifies for the experience's audience (qualification gates
  ahead of the sticky read).

Rows 4 (unresolvable stored variation falls through to a fresh hash) and 7
(cross-request stickiness via a NEW Core/Context sharing the SAME DataStore
and an UNCHANGED config) are explicitly OUT of scope here -- PY-4's job.

All of these tests currently FAIL: ``run_experience``/``run_experiences`` do
not yet accept ``enable_storage``, and nothing is persisted after a bucketing
decision today (PY-1/PY-2 are substrate only).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from convert_sdk import Core, InMemoryDataStore, SDKConfig
from convert_sdk.evaluation.bucketing import get_bucket_value_for_visitor, select_bucket
from convert_sdk.ports.storage import visitor_state_key

# --- fixture config (module-level shared builders; qs-03 spec) --------------
#
# exp-a: id 100111, two RUNNING variations (100901 @ 50%, 100903 @ 50%).
# exp-b: id 100222, one RUNNING variation (100902 @ 100%).
# A fresh visitor deterministically hashes into whichever of exp-a's
# variations ``select_experience`` yields -- tests capture this from the
# FIRST run rather than hardcoding a winner.

EXP_A_ID = "100111"
EXP_A_KEY = "exp-a"
VAR_A1 = "100901"
VAR_A2 = "100903"

EXP_B_ID = "100222"
EXP_B_KEY = "exp-b"
VAR_B1 = "100902"

_VIP_AUDIENCE_ID = "aud-vip"
_VIP_AUDIENCE = {
    "id": _VIP_AUDIENCE_ID,
    "key": "vip-only",
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
                                "key": "vip",
                                "value": "yes",
                            }
                        ]
                    }
                ]
            }
        ]
    },
}


def _variation(
    variation_id: str,
    key: str,
    *,
    traffic_allocation: float = 50.0,
    status: str = "running",
) -> Dict[str, Any]:
    return {
        "id": variation_id,
        "key": key,
        "status": status,
        "traffic_allocation": traffic_allocation,
        "changes": {},
    }


def _build_config(
    *,
    exp_a_traffic: Tuple[float, float] = (50.0, 50.0),
    gate_exp_a_audience: bool = False,
) -> Dict[str, Any]:
    """Build the shared exp-a/exp-b fixture config.

    ``exp_a_traffic`` lets AC3 reallocate exp-a's split (e.g. to zero out the
    already-captured variation) without duplicating the whole config literal.
    ``gate_exp_a_audience`` attaches the VIP-only audience to exp-a for AC8,
    otherwise exp-a has no audience gate (every other row needs a visitor who
    qualifies unconditionally).
    """
    exp_a: Dict[str, Any] = {
        "id": EXP_A_ID,
        "key": EXP_A_KEY,
        "status": "running",
        "variations": [
            _variation(VAR_A1, "control", traffic_allocation=exp_a_traffic[0]),
            _variation(VAR_A2, "treatment", traffic_allocation=exp_a_traffic[1]),
        ],
    }
    if gate_exp_a_audience:
        exp_a["audiences"] = [_VIP_AUDIENCE_ID]

    exp_b: Dict[str, Any] = {
        "id": EXP_B_ID,
        "key": EXP_B_KEY,
        "status": "running",
        "variations": [_variation(VAR_B1, "only", traffic_allocation=100.0)],
    }

    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": [exp_a, exp_b],
        "features": [],
        "goals": [],
        "audiences": [_VIP_AUDIENCE] if gate_exp_a_audience else [],
        "segments": [],
    }


class _SpyDataStore(InMemoryDataStore):
    """Records every ``set`` call so a test can assert write counts/shape.

    Mirrors the established ``_SpyDataStore`` precedent in
    ``tests/test_config_by_experience_memo.py`` /
    ``tests/integration/test_context_preview_zero_trace.py`` rather than
    inventing a new spy shape.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_calls: List[Tuple[str, Any, Optional[float]]] = []

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self.set_calls.append((key, value, ttl))
        super().set(key, value, ttl)


def _core(store: InMemoryDataStore, config: Optional[Dict[str, Any]] = None) -> Core:
    return Core(SDKConfig(data=config or _build_config(), data_store=store)).initialize()


class _HashCallSpy:
    """A call-counting stand-in for the bucketing hash entry point.

    Used only where a test asserts the hash was NEVER invoked (AC2's sticky
    read-back) -- it never needs to compute a real value.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, *args: Any, **kwargs: Any) -> int:
        self.calls += 1
        return 0


# --- AC1 (row1): fresh run persists in-memory AND through the DataStore -----


def test_ac1_fresh_run_persists_bucketing_decision_in_memory_and_store() -> None:
    store = _SpyDataStore()
    core = _core(store)
    ctx = core.create_context("v-ac1")

    result = ctx.run_experience(EXP_A_KEY)

    assert result is not None
    assert result.experience_id == EXP_A_ID
    captured = result.variation_id
    assert captured in {VAR_A1, VAR_A2}

    # In-memory ContextState carries the decision immediately.
    assert dict(ctx._state.bucketing) == {EXP_A_ID: captured}

    # The DataStore holds the full 3-key envelope under the visitor-scoped key.
    own_calls = [call for call in store.set_calls if call[0] == visitor_state_key("v-ac1")]
    assert len(own_calls) >= 1
    _, persisted, _ = own_calls[-1]
    assert set(persisted.keys()) == {"attributes", "segments", "bucketing"}
    assert persisted["bucketing"] == {EXP_A_ID: captured}


# --- AC2 (row2): sticky read-back skips the hash and does not re-persist ----


def test_ac2_second_run_same_context_is_sticky_no_rehash_no_rewrite(monkeypatch) -> None:
    store = _SpyDataStore()
    core = _core(store)
    ctx = core.create_context("v-ac2")

    first = ctx.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id
    set_calls_after_row1 = len(store.set_calls)

    spy = _HashCallSpy()
    monkeypatch.setattr(
        "convert_sdk.evaluation.experiences.get_bucket_value_for_visitor", spy
    )

    second = ctx.run_experience(EXP_A_KEY)

    assert second is not None
    assert second.variation_id == captured
    assert spy.calls == 0
    assert len(store.set_calls) == set_calls_after_row1


# --- AC3 (row3): stored decision survives a traffic reallocation ------------


def test_ac3_stored_decision_survives_traffic_reallocation() -> None:
    store = _SpyDataStore()
    core_a = _core(store)
    ctx_a = core_a.create_context("v-ac3")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    # Reallocate so a FRESH hash would have to pick the other variation (the
    # captured one is zeroed out and therefore excluded from the packed-layout
    # bucket walk entirely) -- yet the sticky read-back does not depend on
    # traffic/status at all (`_find_variation` resolves by id only), so it must
    # still win.
    reallocated = (
        _build_config(exp_a_traffic=(0.0, 100.0))
        if captured == VAR_A1
        else _build_config(exp_a_traffic=(100.0, 0.0))
    )
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac3")  # rehydrates bucketing via the shared store

    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    result = ctx_b.run_experience(EXP_A_KEY)

    assert result is not None
    assert result.variation_id == captured


# --- AC5 (row5): preview active on the context suppresses ALL persistence --


def test_ac5_preview_active_on_context_suppresses_bucketing_persist() -> None:
    store = _SpyDataStore()
    core = _core(store)
    ctx = core.create_context("v-ac5")

    # Control (BEFORE any preview is set): a normal run of exp-a DOES persist
    # its bucketing decision. This control assertion is what makes the test
    # fail TODAY -- nothing is persisted yet (PY-3 is unwired) -- and pins the
    # write-after-hash contract the suppression below is relative to.
    control = ctx.run_experience(EXP_A_KEY)
    assert control is not None
    assert dict(ctx._state.bucketing) == {EXP_A_ID: control.variation_id}
    assert len(store.set_calls) >= 1
    calls_before_preview = len(store.set_calls)

    # Preview targets exp-a; exp-b is run normally (non-previewed) below, but
    # ONCE a preview is active anywhere on this context, ALL persistence is
    # suppressed -- including for an unrelated, normally-decided experience.
    ctx.set_preview(EXP_A_ID, VAR_A1)

    result = ctx.run_experience(EXP_B_KEY)

    assert result is not None
    assert result.variation_id == VAR_B1
    # No NEW bucketing entry recorded for exp-b, and no additional store write.
    assert EXP_B_ID not in ctx._state.bucketing
    assert len(store.set_calls) == calls_before_preview


# --- AC6 (row6): enable_storage=False gates ONLY the bucketing write -------


def test_ac6_enable_storage_false_suppresses_only_bucketing_write() -> None:
    store = _SpyDataStore()
    core = _core(store)
    ctx = core.create_context("v-ac6")

    result = ctx.run_experience(EXP_A_KEY, enable_storage=False)

    assert result is not None
    assert dict(ctx._state.bucketing) == {}
    assert store.set_calls == []

    # An UNRELATED set_attributes persist on the SAME context is unaffected --
    # enable_storage gates only the bucketing write, never persistence overall.
    ctx.set_attributes({"plan": "pro"})
    assert len(store.set_calls) == 1
    _, persisted, _ = store.set_calls[-1]
    assert persisted["attributes"] == {"plan": "pro"}


# --- AC8 (row8): stored decision does not resurrect a non-qualifying visitor


def _natural_bucket_winner(visitor_id: str, experience_id: str) -> str:
    """Compute which of exp-a's two 50/50 variations a FRESH hash would pick
    for ``visitor_id``, using the SAME pure bucketing primitives
    ``select_experience`` calls internally.

    Used only to seed AC8's pre-existing stored decision with the OPPOSITE
    variation id, so the control assertion in
    :func:`test_ac8_audience_mismatch_gates_stored_decision_returns_none`
    deterministically FAILS today (no sticky read-back is wired yet, so
    ``run_experience`` would return the natural fresh-hash winner instead of
    the stored one) and deterministically PASSES once PY-3 wires the
    read-back -- regardless of which variation this visitor id naturally
    hashes into.
    """
    value = get_bucket_value_for_visitor(visitor_id, experience_id=experience_id)
    winner = select_bucket({VAR_A1: 50.0, VAR_A2: 50.0}, value)
    assert winner is not None
    return winner


def test_ac8_audience_mismatch_gates_stored_decision_returns_none() -> None:
    store = _SpyDataStore()
    natural = _natural_bucket_winner("v-ac8", EXP_A_ID)
    stored_decision = VAR_A2 if natural == VAR_A1 else VAR_A1
    # Pre-seed a stored decision for exp-a BEFORE the context is created, so
    # Core._hydrate_visitor_state (PY-1, already wired) rehydrates it onto the
    # fresh ContextState. Deliberately the OPPOSITE of the natural fresh-hash
    # winner (see _natural_bucket_winner) so a control run below can prove
    # the sticky read-back is genuinely being consulted.
    store.set(
        visitor_state_key("v-ac8"),
        {"attributes": {}, "segments": {}, "bucketing": {EXP_A_ID: stored_decision}},
    )

    # Control: WITHOUT the audience gate, the pre-seeded decision must be
    # honored verbatim via the sticky read-back.
    core_ungated = _core(store, _build_config(gate_exp_a_audience=False))
    ctx_control = core_ungated.create_context("v-ac8")
    assert dict(ctx_control._state.bucketing) == {EXP_A_ID: stored_decision}
    control = ctx_control.run_experience(EXP_A_KEY)
    assert control is not None
    assert control.variation_id == stored_decision

    # With the SAME pre-seeded decision but the audience gate ON, the visitor
    # (no "vip" attribute) no longer qualifies -- stickiness must NOT
    # resurrect a result.
    core_gated = _core(store, _build_config(gate_exp_a_audience=True))
    ctx_gated = core_gated.create_context("v-ac8")
    assert dict(ctx_gated._state.bucketing) == {EXP_A_ID: stored_decision}

    result = ctx_gated.run_experience(EXP_A_KEY)

    assert result is None
