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

Row 4 (unresolvable stored variation falls through to a fresh hash) is
exercised above by ``test_ac4_unresolvable_stored_vid_falls_through_and_updates_map``.
Row 7 -- AC7 cross-request/cross-``Core`` durability via a shared
``DataStore``, plus the negative control proving an unshared store is NOT
sticky -- is exercised below by
``test_ac7_shared_store_across_cores_is_sticky_no_rehash`` and
``test_ac7_unshared_stores_across_cores_are_not_sticky`` (PY-4).

All of these tests currently FAIL: ``run_experience``/``run_experiences`` do
not yet accept ``enable_storage``, and nothing is persisted after a bucketing
decision today (PY-1/PY-2 are substrate only).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from convert_sdk import Core, InMemoryDataStore, SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.results import ConversionStatus
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

# AC11 (conversion attribution) needs a resolvable goal on the shared config.
GOAL_ID = "500444"
GOAL_KEY = "purchase_completed"

# AC12/AC13 (feature resolution / diagnostics sticky) need a fullStackFeature
# change whose variable VALUE differs per exp-a variation, so "resolved from
# the sticky variation" is observably distinguishable from "resolved from a
# fresh-hash variation" -- not just a resolved/not-resolved signal.
FEATURE_ID = "300333"
FEATURE_KEY = "banner-feature"
FEATURE_VAR_KEY = "headline"
FEATURE_VALUE_A1 = "control-headline"
FEATURE_VALUE_A2 = "treatment-headline"

# exp-a variation id -> its human-readable `key` / its feature headline value,
# shared by the AC11/12/13 tests so neither has to re-derive the mapping.
_VARIATION_KEYS = {VAR_A1: "control", VAR_A2: "treatment"}
_FEATURE_VALUES = {VAR_A1: FEATURE_VALUE_A1, VAR_A2: FEATURE_VALUE_A2}

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
    feature_value: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a single variation, optionally carrying a ``fullStackFeature``
    change for ``FEATURE_ID`` (AC12/AC13). ``feature_value`` is ``None`` for
    every pre-existing call site (AC1-AC10), so those variations still get an
    empty ``changes`` list, unchanged in effect from the previous ``{}``
    literal (``features.py`` treats both as falsy).
    """
    changes: List[Dict[str, Any]] = []
    if feature_value is not None:
        changes.append(
            {
                "id": f"fsf-{variation_id}",
                "type": "fullStackFeature",
                "data": {
                    "feature_id": FEATURE_ID,
                    "variables_data": {FEATURE_VAR_KEY: feature_value},
                },
            }
        )
    return {
        "id": variation_id,
        "key": key,
        "status": status,
        "traffic_allocation": traffic_allocation,
        "changes": changes,
    }


def _build_config(
    *,
    exp_a_traffic: Tuple[float, float] = (50.0, 50.0),
    gate_exp_a_audience: bool = False,
    include_feature: bool = False,
    feature_variation_ids: Optional[FrozenSet[str]] = None,
) -> Dict[str, Any]:
    """Build the shared exp-a/exp-b fixture config.

    ``exp_a_traffic`` lets AC3 (and the AC11/12/13 reallocation helper)
    reallocate exp-a's split (e.g. to zero out the already-captured variation)
    without duplicating the whole config literal. ``gate_exp_a_audience``
    attaches the VIP-only audience to exp-a for AC8, otherwise exp-a has no
    audience gate (every other row needs a visitor who qualifies
    unconditionally).

    ``include_feature`` (AC12/AC13) declares ``FEATURE_KEY`` and attaches its
    ``fullStackFeature`` change to exp-a's variations named in
    ``feature_variation_ids`` (default: BOTH ``VAR_A1``/``VAR_A2``, each with
    a DIFFERENT ``headline`` value, so a resolved feature's variable value
    itself proves which variation served it). Passing a narrower
    ``feature_variation_ids`` (e.g. just the sticky/captured variation) lets a
    test observe a resolved/not-resolved signal instead of a value diff --
    used by the diagnose_feature consistency check, where the typed
    diagnostic does not expose the resolved variation's variables.
    """
    feature_targets: FrozenSet[str] = (
        feature_variation_ids
        if feature_variation_ids is not None
        else frozenset({VAR_A1, VAR_A2})
    )

    def _feature_value_for(variation_id: str) -> Optional[str]:
        if not include_feature or variation_id not in feature_targets:
            return None
        return _FEATURE_VALUES[variation_id]

    exp_a: Dict[str, Any] = {
        "id": EXP_A_ID,
        "key": EXP_A_KEY,
        "status": "running",
        "variations": [
            _variation(
                VAR_A1,
                "control",
                traffic_allocation=exp_a_traffic[0],
                feature_value=_feature_value_for(VAR_A1),
            ),
            _variation(
                VAR_A2,
                "treatment",
                traffic_allocation=exp_a_traffic[1],
                feature_value=_feature_value_for(VAR_A2),
            ),
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

    features = (
        [
            {
                "id": FEATURE_ID,
                "key": FEATURE_KEY,
                "variables": [{"key": FEATURE_VAR_KEY, "type": "string"}],
            }
        ]
        if include_feature
        else []
    )

    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": [exp_a, exp_b],
        "features": features,
        "goals": [{"id": GOAL_ID, "key": GOAL_KEY}],
        "audiences": [_VIP_AUDIENCE] if gate_exp_a_audience else [],
        "segments": [],
    }


def _reallocate_away_from(captured: str, **config_kwargs: Any) -> Dict[str, Any]:
    """Build a config where a FRESH hash for exp-a would pick the variation
    OTHER than ``captured`` (the already-stored sticky decision), by zeroing
    out ``captured``'s traffic split -- the same reallocation shape
    ``test_ac3_stored_decision_survives_traffic_reallocation`` pins inline,
    shared here so AC11/AC12/AC13 do not each repeat the same conditional
    (SonarQube new-code-duplication discipline). Extra ``config_kwargs`` (e.g.
    ``include_feature``, ``feature_variation_ids``) are forwarded to
    :func:`_build_config` unchanged.
    """
    exp_a_traffic = (0.0, 100.0) if captured == VAR_A1 else (100.0, 0.0)
    return _build_config(exp_a_traffic=exp_a_traffic, **config_kwargs)


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
    # enable_storage gates ONLY the bucketing-decision envelope persist
    # (the qs-03 concern, keyed under visitor_state_key's "state:" namespace).
    # It does NOT suppress the pre-existing, unrelated Story 2.5
    # bucketing-activation dedup-marker write (keyed under a distinct
    # "bucketing:" namespace, see tracking/deduplication.py
    # bucketing_marker_key) -- that write is gated by enable_tracking (default
    # True here, untouched by this call), not enable_storage.
    own_calls = [call for call in store.set_calls if call[0] == visitor_state_key("v-ac6")]
    assert own_calls == []

    # An UNRELATED set_attributes persist on the SAME context is unaffected --
    # enable_storage gates only the bucketing write, never persistence overall.
    ctx.set_attributes({"plan": "pro"})
    own_calls_after_set_attributes = [
        call for call in store.set_calls if call[0] == visitor_state_key("v-ac6")
    ]
    assert len(own_calls_after_set_attributes) == 1
    _, persisted, _ = own_calls_after_set_attributes[-1]
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


# --- AC4 (row4): unresolvable stored variation falls through to fresh hash --


def test_ac4_unresolvable_stored_vid_falls_through_and_updates_map(monkeypatch) -> None:
    store = _SpyDataStore()
    # A stored id absent from exp-a's config (neither VAR_A1 nor VAR_A2).
    store.set(
        visitor_state_key("v-ac4"),
        {"attributes": {}, "segments": {}, "bucketing": {EXP_A_ID: "100999"}},
    )
    core = _core(store)
    ctx = core.create_context("v-ac4")
    assert dict(ctx._state.bucketing) == {EXP_A_ID: "100999"}

    # Unlike AC2's stub spy (never expected to be called), the fall-through
    # path must still exercise the REAL deterministic hash so the "falls
    # through to a resolvable variation" assertion is meaningful -- forward to
    # the real ``get_bucket_value_for_visitor`` while counting invocations.
    calls: List[int] = []

    def _forwarding_hash(*args: Any, **kwargs: Any) -> int:
        calls.append(1)
        return get_bucket_value_for_visitor(*args, **kwargs)

    monkeypatch.setattr(
        "convert_sdk.evaluation.experiences.get_bucket_value_for_visitor", _forwarding_hash
    )

    result = ctx.run_experience(EXP_A_KEY)

    assert result is not None
    assert result.variation_id in {VAR_A1, VAR_A2}
    assert result.variation_id != "100999"
    assert len(calls) >= 1

    # The in-memory map is updated to the fresh id, overwriting the stale one.
    assert ctx._state.bucketing[EXP_A_ID] == result.variation_id

    own_calls = [call for call in store.set_calls if call[0] == visitor_state_key("v-ac4")]
    assert len(own_calls) >= 1
    _, persisted, _ = own_calls[-1]
    assert persisted["bucketing"][EXP_A_ID] == result.variation_id


# --- AC7 (row7): cross-Core durability via a shared DataStore ---------------
#
# There is no in-place "swap this Core's transport/store" seam, so AC7 is
# exercised the same way AC3 already simulates cross-request durability: a
# SECOND, wholly separate ``Core``/``Context`` for the SAME visitor id. AC3
# holds the config fixed and reallocates traffic; AC7 holds the config fixed
# and instead varies whether the two ``Core``s are given the SAME injected
# ``DataStore`` instance (positive) or two independent ones (negative
# control) -- proving stickiness is a property of the shared store, not of
# reusing a single ``Core``/``Context``.


def test_ac7_shared_store_across_cores_is_sticky_no_rehash(monkeypatch) -> None:
    store = _SpyDataStore()
    core_a = _core(store)
    ctx_a = core_a.create_context("v-ac7")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    # A SECOND, separate Core -- built from the SAME shared DataStore instance
    # and the SAME unchanged config -- rehydrates the stored decision on
    # create_context (Core._hydrate_visitor_state, PY-1).
    core_b = _core(store)
    ctx_b = core_b.create_context("v-ac7")
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    spy = _HashCallSpy()
    monkeypatch.setattr(
        "convert_sdk.evaluation.experiences.get_bucket_value_for_visitor", spy
    )

    second = ctx_b.run_experience(EXP_A_KEY)

    assert second is not None
    assert second.variation_id == captured
    assert spy.calls == 0


def test_ac7_unshared_stores_across_cores_are_not_sticky(monkeypatch) -> None:
    store_a = _SpyDataStore()
    store_b = _SpyDataStore()
    core_a = _core(store_a)
    ctx_a = core_a.create_context("v-ac7-neg")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None

    # A SECOND, separate Core with its OWN, independent DataStore -- same
    # visitor id, same unchanged config -- has nothing to rehydrate: no
    # cross-request durability without a SHARED store.
    core_b = _core(store_b)
    ctx_b = core_b.create_context("v-ac7-neg")
    assert dict(ctx_b._state.bucketing) == {}

    spy = _HashCallSpy()
    monkeypatch.setattr(
        "convert_sdk.evaluation.experiences.get_bucket_value_for_visitor", spy
    )

    second = ctx_b.run_experience(EXP_A_KEY)

    assert second is not None
    assert spy.calls == 1


# --- AC11/AC12/AC13 (PY-5): the sticky read is a SHARED chokepoint ----------
#
# The qs-03 contract (spec section "The sticky read is a shared chokepoint
# (JS parity)", AC11/AC12/AC13) requires every variation-resolution path --
# not just `run_experience` -- to honor an already-stored bucketing decision:
# conversion attribution, feature resolution, and diagnostics. Today (PY-1..
# PY-4) only `run_experience`/`run_experiences` consult
# `self._state.bucketing`; `resolve_feature`/`resolve_features`
# (evaluation/features.py), `_compute_bucketing_assignments`/
# `create_conversion` (tracking/conversions.py), `Tracker.track`
# (tracking/tracker.py), and `diagnose_experience`/`diagnose_feature`
# (context.py) all call `select_experience` with NO `sticky_bucketing`
# argument, so each re-hashes fresh. All tests below build the SAME
# "reallocate away from the already-captured variation" setup AC3/AC7 already
# use (a SECOND Core/Context sharing the visitor id, from a config where a
# fresh hash would flip to the OTHER exp-a variation) and therefore currently
# FAIL: the sibling paths return the fresh-hash variation's outcome instead of
# the sticky one `run_experience` already served and persisted.


def test_ac11_conversion_attribution_sticky_after_reallocation_tracker_path() -> None:
    """AC11, tracker-backed path (``Core``-constructed context, PY-6's shared
    ``Tracker.track``). Also asserts the read-only invariant: attributing a
    conversion writes NO new bucketing-decision envelope entry -- only
    ``run_experience``'s original write is present.
    """
    store = _SpyDataStore()
    core_a = _core(store)
    ctx_a = core_a.create_context("v-ac11-tracker")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    reallocated = _reallocate_away_from(captured)
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac11-tracker")
    # Rehydrated via the shared store (PY-1); pins that the sticky decision is
    # genuinely available to be consulted before the assertion below.
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    key = visitor_state_key("v-ac11-tracker")
    calls_before = len([call for call in store.set_calls if call[0] == key])

    result = ctx_b.track_conversion(GOAL_KEY)

    assert result.status is ConversionStatus.QUEUED
    assert result.event is not None
    # Attribution must name the STICKY variation, not the reallocated
    # config's fresh-hash winner (the other variation, since `captured`'s
    # traffic was zeroed out by `_reallocate_away_from`). exp-b (100% alloc,
    # always resolves) is also a real active assignment for this visitor and
    # must still be present -- attribution is computed over EVERY experience
    # the visitor buckets into, not just the one under sticky-bucketing test.
    assert result.event.bucketing_assignments == {EXP_A_ID: captured, EXP_B_ID: VAR_B1}

    # Read-only: no NEW "state:"-keyed envelope write from tracking a
    # conversion (a dedup-marker write under a distinct key prefix is
    # unaffected and out of scope for this count).
    calls_after = len([call for call in store.set_calls if call[0] == key])
    assert calls_after == calls_before


def test_ac11_conversion_attribution_sticky_after_reallocation_stateless_fallback_path() -> (
    None
):
    """AC11, the stateless ``create_conversion`` fallback (a ``Context`` built
    directly, with no shared ``Tracker`` -- ``context.py``'s ``track_conversion``
    ``else`` branch, ~context.py:898). Mirrors the no-tracker construction
    precedent in ``tests/test_conversion_tracking.py`` (``Context(visitor_id,
    snap)``) rather than going through ``Core``, since ``Core.create_context``
    always attaches a tracker.
    """
    initial_snapshot = load_snapshot(_build_config())
    ctx_initial = Context("v-ac11-fallback", initial_snapshot)
    assert ctx_initial._tracker is None

    first = ctx_initial.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    reallocated_snapshot = load_snapshot(_reallocate_away_from(captured))
    # No Core/DataStore in this path -- the sticky decision is carried forward
    # by constructing the second, reallocated-config Context directly with
    # the SAME captured decision pre-seeded via ``bucketing=``, the identical
    # rehydration shape ``Core._hydrate_visitor_state`` performs elsewhere in
    # this file from a shared store.
    ctx_reallocated = Context(
        "v-ac11-fallback", reallocated_snapshot, bucketing={EXP_A_ID: captured}
    )
    assert ctx_reallocated._tracker is None

    result = ctx_reallocated.track_conversion(GOAL_KEY)

    assert result.status is ConversionStatus.QUEUED
    assert result.event is not None
    # exp-b (100% alloc, always resolves) is also a real active assignment for
    # this visitor and must still be present alongside the sticky exp-a entry.
    assert result.event.bucketing_assignments == {EXP_A_ID: captured, EXP_B_ID: VAR_B1}


# --- AC12: feature resolution is sticky -------------------------------------


def test_ac12_run_feature_sticky_after_reallocation() -> None:
    store = _SpyDataStore()
    core_a = _core(store, _build_config(include_feature=True))
    ctx_a = core_a.create_context("v-ac12-single")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id
    expected_headline = _FEATURE_VALUES[captured]

    reallocated = _reallocate_away_from(captured, include_feature=True)
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac12-single")
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    key = visitor_state_key("v-ac12-single")
    calls_before = len([call for call in store.set_calls if call[0] == key])

    feature_result = ctx_b.run_feature(FEATURE_KEY)

    assert feature_result is not None
    # Resolved from the STICKY variation's headline, not the reallocated
    # config's fresh-hash winner's (different) headline.
    assert feature_result.variables[FEATURE_VAR_KEY] == expected_headline

    # Read-only: resolving a feature persists no new bucketing decision.
    calls_after = len([call for call in store.set_calls if call[0] == key])
    assert calls_after == calls_before


def test_ac12_run_features_sticky_after_reallocation() -> None:
    store = _SpyDataStore()
    core_a = _core(store, _build_config(include_feature=True))
    ctx_a = core_a.create_context("v-ac12-all")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id
    expected_headline = _FEATURE_VALUES[captured]

    reallocated = _reallocate_away_from(captured, include_feature=True)
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac12-all")
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    key = visitor_state_key("v-ac12-all")
    calls_before = len([call for call in store.set_calls if call[0] == key])

    results = ctx_b.run_features()

    matches = [result for result in results if result.feature_key == FEATURE_KEY]
    assert len(matches) == 1
    assert matches[0].variables[FEATURE_VAR_KEY] == expected_headline

    calls_after = len([call for call in store.set_calls if call[0] == key])
    assert calls_after == calls_before


# --- AC13: diagnostics are sticky --------------------------------------------


def test_ac13_diagnose_experience_sticky_after_reallocation() -> None:
    store = _SpyDataStore()
    core_a = _core(store)
    ctx_a = core_a.create_context("v-ac13-exp")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    reallocated = _reallocate_away_from(captured)
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac13-exp")
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    key = visitor_state_key("v-ac13-exp")
    calls_before = len([call for call in store.set_calls if call[0] == key])

    diagnostic = ctx_b.diagnose_experience(EXP_A_KEY)

    assert diagnostic.resolved
    # Consistent with what run_experience already served (the sticky
    # variation), not the reallocated config's fresh-hash winner.
    assert diagnostic.details["variation_key"] == _VARIATION_KEYS[captured]

    calls_after = len([call for call in store.set_calls if call[0] == key])
    assert calls_after == calls_before


def test_ac13_diagnose_feature_sticky_consistent_with_run_feature() -> None:
    """AC13, ``diagnose_feature``. Unlike ``diagnose_experience``,
    ``FeatureDiagnostic.details`` carries no variation identity (only
    ``{"feature_key": ...}``), so a value-diff fixture (both variations
    carrying the feature, as AC12 uses) cannot distinguish sticky vs
    fresh-hash from the diagnostic's return shape alone. This test therefore
    attaches the feature change ONLY to the sticky/captured variation
    (``feature_variation_ids={captured}``) so the two paths diverge on
    RESOLVED vs FEATURE_NOT_IN_SELECTED_VARIATIONS, and directly cross-checks
    the diagnostic against ``run_feature`` on the SAME context so the two
    stay provably consistent with each other.
    """
    store = _SpyDataStore()
    core_a = _core(store, _build_config())
    ctx_a = core_a.create_context("v-ac13-feat")

    first = ctx_a.run_experience(EXP_A_KEY)
    assert first is not None
    captured = first.variation_id

    reallocated = _reallocate_away_from(
        captured, include_feature=True, feature_variation_ids=frozenset({captured})
    )
    core_b = _core(store, reallocated)
    ctx_b = core_b.create_context("v-ac13-feat")
    assert dict(ctx_b._state.bucketing) == {EXP_A_ID: captured}

    # Ground the diagnostic expectation in what run_feature ACTUALLY serves on
    # this context (AC12 parity), not a re-derivation of the config.
    feature_result = ctx_b.run_feature(FEATURE_KEY)
    assert feature_result is not None
    assert feature_result.variables[FEATURE_VAR_KEY] == _FEATURE_VALUES[captured]

    key = visitor_state_key("v-ac13-feat")
    calls_before = len([call for call in store.set_calls if call[0] == key])

    diagnostic = ctx_b.diagnose_feature(FEATURE_KEY)

    assert diagnostic.resolved

    calls_after = len([call for call in store.set_calls if call[0] == key])
    assert calls_after == calls_before
