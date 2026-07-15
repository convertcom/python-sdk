"""qs-04 PY-3 -- mutual-exclusion audience rule (`bucketed_into_experience_key`),
unit/local-evaluation-level RED tests.

Spec of record: ``_bmad-output/planning-artifacts/2026-04-06-convert-python-sdk/
qs-04-mutual-exclusion-rule.md``.

This file drives EVERY assertion through the real public/eval seams --
:func:`convert_sdk.evaluation.experiences.select_experience` (the same function
``Context.run_experience``/``run_experiences``/``run_feature``/
``diagnose_experience`` all delegate to), :class:`~convert_sdk.context.Context`,
and (for row 8's DataStore-only seeding) :class:`~convert_sdk.core.Core` -- never
a guessed/invented private helper name or a new ``qualifies()`` keyword argument.
``qualifies()``'s CURRENT signature (``experience, snapshot, *,
visitor_attributes=None, location_attributes=None``) is pinned verbatim by the
pre-existing ``tests/test_rules.py``; this file does not assume what parameter
name the GREEN implementation will use to thread the bucketing map into it.

Covers:

* AC1 -- the shared 8-row cross-SDK fixture (``tests/fixtures/mutual_exclusion.py``),
  parametrized, evaluated against a THIRD "experience under test" so its own
  bucketing state never collides with the fixture's exp-a/exp-b entries.
* AC6 -- ``matching_options.audiences`` ALL/ANY combination semantics (a
  sole-exclusion audience + a generic audience on the SAME experience).
* AC7 -- generic-rule / default-ANY zero-regression guards, plus the
  data-isolation structural guard (the exclusion rule must read ONLY the
  bucketing map, never ``visitor_attributes``).
* AC8 -- rows 6/7 (unresolvable target) emit the PY-1 warning naming the key.
* AC9 -- ``diagnose_experience`` reports the exclusion mismatch through the
  existing ``DiagnosticReason.AUDIENCE_MISMATCH`` / ``RESOLVED``.

GENUINE-RED discipline (see this task's decision-log entry for the full
rationale): today ``is_rule_matched`` fails closed on the
``bucketed_into_experience_key`` rule item -- it has no ``key`` field, so the
generic key/value walk returns ``False`` BEFORE negation is ever applied,
regardless of ``row.rule_value``/``row.negated``. That means rows 1, 4, 6, and 8
(``expected_matched is False``) can pass TODAY coincidentally, with no seam at
all. Every test below additionally asserts, via ``_spy_get_experience_by_key``,
that the audience-level resolver genuinely looked up its target experience by
key (``snapshot.get_experience_by_key(row.rule_value)`` per the spec's
resolution algorithm) -- a call that NEVER happens today (the generic
key/value walk never consults the snapshot at all), so this assertion fails for
EVERY row/case here regardless of whether the "matched" outcome happens to
coincide with the fail-closed default. This is deliberately a SINGLE mechanism
applied uniformly rather than special-cased per row.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping

import pytest

from convert_sdk import Core, InMemoryDataStore, SDKConfig
from convert_sdk.config_loader import load_snapshot
from convert_sdk.context import Context
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.domain.results import DiagnosticReason
from convert_sdk.evaluation.experiences import select_experience
from convert_sdk.evaluation.rules import RULE_TYPE_BUCKETED_INTO_EXPERIENCE_KEY
from convert_sdk.ports.storage import visitor_state_key

from tests.fixtures.mutual_exclusion import (
    EXCLUSION_FIXTURE_ROWS,
    EXP_A_ID,
    EXP_A_KEY,
    build_mutual_exclusion_config,
)

# --- a THIRD experience, distinct from exp-a/exp-b, carrying the audience/es
# under test (mirrors the PHP/JS "exp-under-test" isolation convention so its
# own bucketing state never collides with the fixture's exp-a/exp-b entries).

EXP_UNDER_TEST_ID = "100777"
EXP_UNDER_TEST_KEY = "exp-under-test"
VAR_UNDER_TEST_ID = "100778"

_EXCLUSION_AUDIENCE_ID = "aud-exclusion-under-test"
_GENERIC_AUDIENCE_ID = "aud-generic-under-test"
_GENERIC_KEY = "plan"
_GENERIC_VALUE = "pro"


def _exclusion_audience(rule_value: str, negated: bool) -> Dict[str, Any]:
    """A *sole-exclusion* audience: its entire rule tree is ONE
    ``bucketed_into_experience_key`` item (the spec's normative rule shape,
    verbatim), targeting ``rule_value`` with ``negated``.
    """
    return {
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
                                    "value": rule_value,
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }


def _generic_audience() -> Dict[str, Any]:
    """A generic key/value audience (unrelated to mutual exclusion) used by the
    AC6 combination table and the AC7 default-ANY regression guard.
    """
    return {
        "id": _GENERIC_AUDIENCE_ID,
        "key": _GENERIC_AUDIENCE_ID,
        "type": "transient",
        "status": "active",
        "rules": {
            "OR": [
                {
                    "AND": [
                        {
                            "OR_WHEN": [
                                {
                                    "matching": {"match_type": "equals", "negated": False},
                                    "key": _GENERIC_KEY,
                                    "value": _GENERIC_VALUE,
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }


def _config_for_under_test(
    audiences: List[Dict[str, Any]],
    audience_ids: List[str],
    matching_options: "str | None" = None,
) -> Dict[str, Any]:
    """Extend the PY-2 exp-a/exp-b fixture config with a THIRD
    ``exp-under-test`` experience (single 100%-traffic variation) carrying
    ``audience_ids`` and, optionally, ``settings.matching_options.audiences``.

    Built on :func:`build_mutual_exclusion_config` (which returns a fresh dict
    per call) rather than duplicating exp-a/exp-b's literal shape.
    """
    config = build_mutual_exclusion_config()
    config["audiences"] = list(audiences)
    exp_under_test: Dict[str, Any] = {
        "id": EXP_UNDER_TEST_ID,
        "key": EXP_UNDER_TEST_KEY,
        "type": "a/b_fullstack",
        "status": "active",
        "audiences": list(audience_ids),
        "variations": [
            {
                "id": VAR_UNDER_TEST_ID,
                "key": "only",
                "status": "running",
                "traffic_allocation": 100.0,
                "is_baseline": True,
            }
        ],
    }
    if matching_options is not None:
        exp_under_test["settings"] = {"matching_options": {"audiences": matching_options}}
    config["experiences"].append(exp_under_test)
    return config


def _spy_get_experience_by_key(monkeypatch: pytest.MonkeyPatch) -> List[str]:
    """Wrap ``ConfigSnapshot.get_experience_by_key`` to record every ``key`` it
    is called with, forwarding to the real implementation.

    Used as the GENUINE-RED forcing mechanism (see module docstring): the
    spec's resolution algorithm requires the exclusion resolver to look up
    ``target = config experience whose key == rule.value`` via this exact
    public accessor. Patching a real, already-existing public method (not a
    guessed private helper) keeps this test file honest about "public/eval API
    only".
    """
    calls: List[str] = []
    original = ConfigSnapshot.get_experience_by_key

    def _wrapper(self: ConfigSnapshot, key: str) -> Any:
        calls.append(key)
        return original(self, key)

    monkeypatch.setattr(ConfigSnapshot, "get_experience_by_key", _wrapper)
    return calls


# --- AC1 (+ AC8): the shared 8-row cross-SDK fixture -------------------------

_VISITOR_AC1 = "v-ac1-fixture"


@pytest.mark.parametrize(
    "row", EXCLUSION_FIXTURE_ROWS, ids=[f"row{row.row_number}" for row in EXCLUSION_FIXTURE_ROWS]
)
def test_ac1_fixture_rows_resolve_expected_matched(
    row: Any, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    config = _config_for_under_test(
        [_exclusion_audience(row.rule_value, row.negated)], [_EXCLUSION_AUDIENCE_ID]
    )
    calls = _spy_get_experience_by_key(monkeypatch)

    with caplog.at_level(logging.WARNING, logger="convert_sdk"):
        if row.store_only:
            # Row 8: the stored decision lives ONLY in the DataStore, never
            # in-memory -- seeded directly via the same envelope shape the
            # qs-03 sticky-bucketing tests use
            # (tests/integration/test_sticky_bucketing.py), then rehydrated by
            # a fresh Core.create_context() (verified on disk: Core._hydrate_visitor_state).
            store = InMemoryDataStore()
            store.set(
                visitor_state_key(_VISITOR_AC1),
                {"attributes": {}, "segments": {}, "bucketing": dict(row.stored_bucketing)},
            )
            core = Core(SDKConfig(data=config, data_store=store)).initialize()
            ctx = core.create_context(_VISITOR_AC1)
            assert dict(ctx._state.bucketing) == dict(row.stored_bucketing)
            result = ctx.run_experience(EXP_UNDER_TEST_KEY)
        else:
            snapshot = load_snapshot(config)
            result = select_experience(
                EXP_UNDER_TEST_KEY,
                snapshot,
                visitor_id=_VISITOR_AC1,
                visitor_attributes={},
                sticky_bucketing=dict(row.stored_bucketing),
            )

    assert (result is not None) == row.expected_matched, (
        f"row {row.row_number}: expected matched={row.expected_matched}, got result={result!r}"
    )

    # GENUINE-RED forcing (see module docstring + decision-log): independent of
    # whether "matched" happens to coincide with today's fail-closed default.
    assert row.rule_value in calls, (
        f"row {row.row_number}: exclusion resolution must call "
        f"snapshot.get_experience_by_key({row.rule_value!r})"
    )

    warning_messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "convert_sdk" and record.levelno == logging.WARNING
    ]
    if row.expects_warning:
        assert any(row.rule_value in msg for msg in warning_messages), (
            f"row {row.row_number} must warn naming the unresolved target key {row.rule_value!r}"
        )
    else:
        assert not any("mutual-exclusion target" in msg for msg in warning_messages), (
            f"row {row.row_number} must not warn (target key resolves)"
        )


# --- AC6: matching_options.audiences ALL/ANY combination semantics ----------


@dataclass(frozen=True)
class _Ac6Case:
    name: str
    matching_options: str
    ran_a_first: bool
    visitor_attributes: Mapping[str, str]
    expect_served: bool


# Canonical table (task-mandated labels). Cases requiring `expect_served=True`
# can ONLY be produced by a genuinely-resolved exclusion rule -- the pre-seam
# fail-closed fallback (always False) cannot serve those. `any_bothFail` is a
# negative control (both audiences genuinely fail under ALL semantics too) --
# it is expected to coincidentally match today's fail-closed outcome; the
# `_spy_get_experience_by_key` assertion below still forces genuine RED for it.
_AC6_CASES = (
    _Ac6Case("all_bothPass", "all", False, {_GENERIC_KEY: _GENERIC_VALUE}, True),
    _Ac6Case("all_genericFails", "all", False, {}, False),
    _Ac6Case("any_exclusionPasses", "any", False, {}, True),
    _Ac6Case("any_bothFail", "any", True, {}, False),
)


@pytest.mark.parametrize("case", _AC6_CASES, ids=[c.name for c in _AC6_CASES])
def test_ac6_combination_semantics(case: _Ac6Case, monkeypatch: pytest.MonkeyPatch) -> None:
    config = _config_for_under_test(
        [_generic_audience(), _exclusion_audience(EXP_A_KEY, negated=True)],
        [_GENERIC_AUDIENCE_ID, _EXCLUSION_AUDIENCE_ID],
        matching_options=case.matching_options,
    )
    snapshot = load_snapshot(config)
    visitor_id = f"v-ac6-{case.name}"
    calls = _spy_get_experience_by_key(monkeypatch)

    sticky_bucketing: Dict[str, str] = {}
    if case.ran_a_first:
        first = select_experience(EXP_A_KEY, snapshot, visitor_id=visitor_id, visitor_attributes={})
        assert first is not None
        sticky_bucketing[first.experience_id] = first.variation_id
        # The warm-up run above ALSO calls get_experience_by_key(EXP_A_KEY) (to
        # resolve exp-a itself) -- clear the spy so the assertion below only
        # counts calls made while resolving EXP_UNDER_TEST's own exclusion
        # audience, not this unrelated setup step (see decision-log: without
        # this, `any_bothFail` passes coincidentally for the wrong reason).
        calls.clear()

    result = select_experience(
        EXP_UNDER_TEST_KEY,
        snapshot,
        visitor_id=visitor_id,
        visitor_attributes=dict(case.visitor_attributes),
        sticky_bucketing=sticky_bucketing,
    )

    assert (result is not None) == case.expect_served, (
        f"{case.name}: expected served={case.expect_served}, got {result!r}"
    )
    assert EXP_A_KEY in calls, f"{case.name}: exclusion resolver must look up {EXP_A_KEY!r}"


# --- AC7: generic-rule / default-ANY zero-regression + data-isolation guard --


def test_ac7_default_any_when_matching_options_absent_is_zero_regression() -> None:
    """AC7: an experience with NO ``matching_options`` keeps today's ANY
    semantics (at least one referenced audience matches) -- every currently
    served config (none carry ``matching_options``) must keep qualifying
    bit-identically. This is a FORWARD regression guard: it already passes
    today (matching_options is inert/unread) and must keep passing after the
    seam lands (default stays ANY).
    """
    always_fails = {
        "id": "aud-always-fails",
        "key": "aud-always-fails",
        "type": "transient",
        "status": "active",
        "rules": {
            "OR": [
                {
                    "AND": [
                        {
                            "OR_WHEN": [
                                {
                                    "matching": {"match_type": "equals", "negated": False},
                                    "key": "never",
                                    "value": "matches",
                                }
                            ]
                        }
                    ]
                }
            ]
        },
    }
    config = _config_for_under_test(
        [_generic_audience(), always_fails],
        [_GENERIC_AUDIENCE_ID, "aud-always-fails"],
        matching_options=None,
    )
    snapshot = load_snapshot(config)

    result = select_experience(
        EXP_UNDER_TEST_KEY,
        snapshot,
        visitor_id="v-ac7-default-any",
        visitor_attributes={_GENERIC_KEY: _GENERIC_VALUE},
    )

    assert result is not None, "absent matching_options must default to ANY (today's sole policy)"


def test_ac7_exclusion_reads_only_bucketing_map_never_visitor_attributes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC7 structural guard: the ``bucketed_into_experience_key`` resolution
    must read ONLY the sticky-bucketing map -- never ``visitor_attributes`` (or
    any other key/value ``data`` mapping ``is_rule_matched`` reads). A decoy
    visitor attribute shaped like the target's key/id must not spuriously
    satisfy (or defeat) the rule.
    """
    config = _config_for_under_test(
        [_exclusion_audience(EXP_A_KEY, negated=False)], [_EXCLUSION_AUDIENCE_ID]
    )
    snapshot = load_snapshot(config)
    calls = _spy_get_experience_by_key(monkeypatch)

    decoy_attributes = {EXP_A_KEY: EXP_A_ID, "value": EXP_A_KEY, "rule_type": "bucketed_into_experience_key"}

    result = select_experience(
        EXP_UNDER_TEST_KEY,
        snapshot,
        visitor_id="v-ac7-data-isolation",
        visitor_attributes=decoy_attributes,
        sticky_bucketing={},  # visitor genuinely never ran exp-a
    )

    # negated=False, bucketed_raw=False (empty map, decoy attributes ignored) -> no qualify.
    assert result is None
    assert EXP_A_KEY in calls


# --- AC9: diagnose_experience reports the exclusion mismatch/resolution -----


def test_ac9_diagnose_experience_reports_audience_mismatch_for_excluded_visitor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config_for_under_test(
        [_exclusion_audience(EXP_A_KEY, negated=False)], [_EXCLUSION_AUDIENCE_ID]
    )
    snapshot = load_snapshot(config)
    calls = _spy_get_experience_by_key(monkeypatch)
    # negated=False, visitor never ran exp-a -> bucketed_raw=False -> matched=False.
    ctx = Context("v-ac9-mismatch", snapshot)

    diagnostic = ctx.diagnose_experience(EXP_UNDER_TEST_KEY)

    assert diagnostic.reason is DiagnosticReason.AUDIENCE_MISMATCH
    assert EXP_A_KEY in calls


def test_ac9_diagnose_experience_reports_resolved_when_exclusion_passes() -> None:
    config = _config_for_under_test(
        [_exclusion_audience(EXP_A_KEY, negated=True)], [_EXCLUSION_AUDIENCE_ID]
    )
    snapshot = load_snapshot(config)
    # negated=True, visitor never ran exp-a -> bucketed_raw=False -> matched=True.
    ctx = Context("v-ac9-resolved", snapshot)

    diagnostic = ctx.diagnose_experience(EXP_UNDER_TEST_KEY)

    assert diagnostic.reason is DiagnosticReason.RESOLVED
