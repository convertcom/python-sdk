"""qs-04 PY-3 -- mutual-exclusion audience rule (`bucketed_into_experience_key`),
end-to-end RED tests through the public ``Context``/``Core`` API.

Spec of record: ``_bmad-output/planning-artifacts/2026-04-06-convert-python-sdk/
qs-04-mutual-exclusion-rule.md``.

Covers:

* AC2 -- end-to-end exclusion: exp-b carries a transient audience
  (``matching_options: ALL``) with the negated rule targeting exp-a. A fresh
  visitor buckets into A, then is excluded from B; a visitor who never ran A
  buckets into B normally.
* AC3 -- DataStore persistence: a decision written by ONE core/context excludes
  the visitor from B in a brand-new core/context sharing the SAME ``DataStore``
  (fixture row 8's end-to-end shape).
* AC4 -- no new inputs: driven with ``attributes={}`` throughout (folded into
  the AC2 test rather than a separate near-duplicate one).
* AC5 -- read-only: evaluating the exclusion rule triggers no re-bucketing of
  the target, no NEW store write, and no bucketing-event enqueue for the
  excluded experience.

Mirrors ``tests/integration/test_sticky_bucketing.py`` (``_core``/``_SpyDataStore``
conventions) and the JS oracle
(``javascript-sdk/packages/js-sdk/tests/integration/mutual-exclusion-rule.spec.ts``)
for the exact rule/audience/config shape and AC5's ``LifecycleEvent.BUCKETING``
recorder pattern (JS: ``SystemEvents.BUCKETING`` / ``recordBucketingEvents``).

All tests here currently FAIL: no seam resolves ``bucketed_into_experience_key``
yet, so exp-b's exclusion audience fails closed (never matches, regardless of
negation) -- exp-b never serves ANY visitor today, including the ones AC2/AC3
expect to bucket into it normally.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from convert_sdk import Core, InMemoryDataStore, SDKConfig
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.events import BucketingEventPayload, LifecycleEvent
from convert_sdk.evaluation.rules import RULE_TYPE_BUCKETED_INTO_EXPERIENCE_KEY

from tests.fixtures.mutual_exclusion import (
    EXP_A_ID,
    EXP_A_KEY,
    EXP_B_ID,
    EXP_B_KEY,
    VAR_A1,
    VAR_B1,
    build_mutual_exclusion_config,
)

_EXCLUSION_AUDIENCE_ID = "aud-exclusion-e2e"


def _exclusion_config(*, negated: bool = True, matching_options: str = "all") -> Dict[str, Any]:
    """The PY-2 exp-a/exp-b fixture, with exp-b additionally carrying a
    transient sole-exclusion audience (negated, targeting exp-a) combined via
    ``matching_options``. Mirrors the spec's AC2 setup verbatim.
    """
    config = build_mutual_exclusion_config()
    config["audiences"] = [
        {
            "id": _EXCLUSION_AUDIENCE_ID,
            "key": _EXCLUSION_AUDIENCE_ID,
            "type": "transient",
            "status": "active",
            "rules": {
                "OR": [
                    {
                        "AND": [
                            {
                                "OR_WHEN": [
                                    {
                                        "rule_type": RULE_TYPE_BUCKETED_INTO_EXPERIENCE_KEY,
                                        "matching": {"match_type": "equals", "negated": negated},
                                        "value": EXP_A_KEY,
                                    }
                                ]
                            }
                        ]
                    }
                ]
            },
        }
    ]
    for experience in config["experiences"]:
        if experience["key"] == EXP_B_KEY:
            experience["audiences"] = [_EXCLUSION_AUDIENCE_ID]
            experience["settings"] = {"matching_options": {"audiences": matching_options}}
    return config


def _core(store: InMemoryDataStore, config: Optional[Dict[str, Any]] = None) -> Core:
    return Core(SDKConfig(data=config or _exclusion_config(), data_store=store)).initialize()


class _SpyDataStore(InMemoryDataStore):
    """Records every ``set`` call so a test can assert write counts (AC5).

    Mirrors the established ``_SpyDataStore`` precedent in
    ``tests/integration/test_sticky_bucketing.py`` /
    ``tests/integration/test_context_preview_zero_trace.py``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.set_calls: List[Tuple[str, Any, Optional[float]]] = []

    def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        self.set_calls.append((key, value, ttl))
        super().set(key, value, ttl)


def _spy_get_experience_by_key(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Wrap ``ConfigSnapshot.get_experience_by_key`` to record every ``key`` it
    is called with (mirrors ``tests/test_mutual_exclusion.py``'s identical
    helper -- the GENUINE-RED forcing mechanism, see that module's docstring).

    Several assertions below (``decision_b is None`` for an ALREADY-excluded
    visitor) coincidentally hold TODAY too, since exp-b's exclusion audience
    fails closed for every visitor regardless of negation/bucketing state --
    a visitor who is genuinely excluded and one the seam merely hasn't wired
    yet both currently resolve to ``None``. This spy independently proves the
    resolver genuinely consulted the target (``EXP_A_KEY``) while evaluating
    exp-b, which never happens today.
    """
    calls: List[str] = []
    original = ConfigSnapshot.get_experience_by_key

    def _wrapper(self: ConfigSnapshot, key: str) -> Any:
        calls.append(key)
        return original(self, key)

    monkeypatch.setattr(ConfigSnapshot, "get_experience_by_key", _wrapper)
    return calls


# --- AC2 (+ AC4): end-to-end exclusion, empty attributes throughout ----------


def test_ac2_fresh_visitor_bucketed_into_a_is_excluded_from_b(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _exclusion_config()
    store = InMemoryDataStore()
    core = _core(store, config)
    ctx = core.create_context("visitor-ac2-excluded")

    decision_a = ctx.run_experience(EXP_A_KEY, attributes={})
    assert decision_a is not None
    assert decision_a.variation_id == VAR_A1

    # GENUINE-RED forcing (see _spy_get_experience_by_key docstring): only
    # patched AFTER the warm-up run-A call so it isolates the lookup(s) made
    # while resolving exp-b's exclusion audience.
    calls = _spy_get_experience_by_key(monkeypatch)

    decision_b = ctx.run_experience(EXP_B_KEY, attributes={})
    assert decision_b is None
    assert EXP_A_KEY in calls, "exclusion resolver must look up exp-a while evaluating exp-b"


def test_ac2_visitor_who_never_ran_a_buckets_into_b_normally() -> None:
    config = _exclusion_config()
    store = InMemoryDataStore()
    core = _core(store, config)
    ctx = core.create_context("visitor-ac2-fresh-never-ran-a")

    decision_b = ctx.run_experience(EXP_B_KEY, attributes={})

    assert decision_b is not None
    assert decision_b.variation_id == VAR_B1


# --- AC3: DataStore persistence across a brand-new Core/Context -------------


def test_ac3_shared_datastore_decision_excludes_visitor_in_new_core(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _exclusion_config()
    store = InMemoryDataStore()
    visitor_id = "visitor-ac3-datastore"

    core_a = _core(store, config)
    ctx_a = core_a.create_context(visitor_id)
    decision_a = ctx_a.run_experience(EXP_A_KEY, attributes={})
    assert decision_a is not None

    # A brand-new Core/Context, sharing only the DataStore.
    core_b = _core(store, config)
    ctx_b = core_b.create_context(visitor_id)

    # GENUINE-RED forcing (see _spy_get_experience_by_key docstring): patched
    # on the SECOND Core/Context only, so it isolates the lookup(s) made while
    # resolving exp-b's exclusion audience from the DataStore-rehydrated map.
    calls = _spy_get_experience_by_key(monkeypatch)

    decision_b = ctx_b.run_experience(EXP_B_KEY, attributes={})

    assert decision_b is None
    assert EXP_A_KEY in calls, "exclusion resolver must look up exp-a while evaluating exp-b"


def test_ac3_control_visitor_who_never_ran_a_still_buckets_into_b() -> None:
    """A THIRD Core/Context, sharing the same DataStore but a visitor who never
    ran A, must still bucket into B normally -- proves the exclusion is keyed
    off the visitor's actual stored decision, not a blanket "exp-b never
    serves" fallback.
    """
    config = _exclusion_config()
    store = InMemoryDataStore()

    core_a = _core(store, config)
    ctx_a = core_a.create_context("visitor-ac3-datastore-primary")
    assert ctx_a.run_experience(EXP_A_KEY, attributes={}) is not None

    core_control = _core(store, config)
    ctx_control = core_control.create_context("visitor-ac3-control-never-ran-a")
    decision_b_control = ctx_control.run_experience(EXP_B_KEY, attributes={})

    assert decision_b_control is not None
    assert decision_b_control.variation_id == VAR_B1


# --- AC5: read-only -- no re-bucketing, no new store write, no tracking -----


def test_ac5_evaluating_exclusion_rule_is_read_only(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _exclusion_config()
    store = _SpyDataStore()
    core = _core(store, config)

    bucketing_events: List[BucketingEventPayload] = []
    core.on(LifecycleEvent.BUCKETING, lambda payload, error=None: bucketing_events.append(payload))

    ctx = core.create_context("visitor-ac5-read-only")

    decision_a = ctx.run_experience(EXP_A_KEY, attributes={})
    assert decision_a is not None
    assert [e.experience_id for e in bucketing_events if e.experience_id == EXP_A_ID] == [EXP_A_ID]

    calls_before = len(store.set_calls)
    # GENUINE-RED forcing (see _spy_get_experience_by_key docstring): every
    # OTHER assertion in this test (no re-bucketing, no new tracking event, no
    # new store write) coincidentally holds today regardless of the seam,
    # because a `None` result short-circuits tracking/persistence identically
    # whether it's a genuine exclusion or the current fail-closed default. This
    # spy is the one assertion that actually depends on the resolver running.
    calls = _spy_get_experience_by_key(monkeypatch)

    decision_b = ctx.run_experience(EXP_B_KEY, attributes={})

    assert decision_b is None
    assert EXP_A_KEY in calls, "exclusion resolver must look up exp-a while evaluating exp-b"
    # No second bucketing of the target (exp-a) as a side effect of evaluating
    # exp-b's exclusion audience, and exp-b itself is excluded (no event for it).
    assert [e.experience_id for e in bucketing_events if e.experience_id == EXP_A_ID] == [EXP_A_ID]
    assert [e for e in bucketing_events if e.experience_id == EXP_B_ID] == []
    # No NEW DataStore write from the read-only exclusion check.
    assert len(store.set_calls) == calls_before
