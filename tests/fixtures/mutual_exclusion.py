"""qs-04 mutual-exclusion rule (`bucketed_into_experience_key`) — shared,
data-only fixture consumed by the rule-engine tests (PY-3, a separate task).

This module is PY-2's entire deliverable: DATA, not production code. It
provides:

* :data:`EXCLUSION_FIXTURE_ROWS` — the spec's inline 8-row cross-SDK fixture
  table (``qs-04-mutual-exclusion-rule.md``, "Inline cross-SDK fixture"),
  copied VERBATIM as a single ``@pytest.mark.parametrize`` data source (AC1).
  Row values are the cross-SDK contract shared by every sibling SDK spec —
  they must never be recomputed or "improved" here.
* :func:`build_mutual_exclusion_config` — the minimal served config the
  fixture rows are evaluated against: ``exp-a`` (id ``100111``, one RUNNING
  variation ``100901`` @ 100%) and ``exp-b`` (id ``100222``, one RUNNING
  variation ``100902`` @ 100%), both ``a/b_fullstack`` / ``active``.
  ``exp-zz`` (rows 6/7's unresolvable target) is deliberately ABSENT.

This fixture wires NO exclusion audience / ``matching_options`` onto ``exp-b``
— attaching the ``bucketed_into_experience_key`` rule is PY-3's seam work
(qs-04 PY-3), not this data-only scaffolding task (PY-2).

Field names are grounded in the real served-config shape (verified against
``javascript-sdk/packages/experience/tests/test-config.json``, the JS SDK's
own fixture for the same experience/variation entities: experience-level
``type``/``status``, variation-level ``status``/``traffic_allocation``/
``is_baseline``) and cross-checked against what this SDK's own evaluator
reads (``src/convert_sdk/evaluation/experiences.py`` ``_is_running`` /
``_has_traffic`` / ``_build_buckets`` — variation ``status``/
``traffic_allocation``; ``domain/config_snapshot.py`` — experience ``id``/
``key``), not invented ad hoc.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, NamedTuple, Tuple

EXP_A_KEY = "exp-a"
EXP_A_ID = "100111"
VAR_A1 = "100901"

EXP_B_KEY = "exp-b"
EXP_B_ID = "100222"
VAR_B1 = "100902"

#: Rows 6/7 target this key. It is deliberately absent from
#: :func:`build_mutual_exclusion_config`'s served experiences — the whole
#: point of those rows is an unresolvable ``bucketed_into_experience_key``
#: target.
EXP_ZZ_KEY = "exp-zz"


class MutualExclusionFixtureRow(NamedTuple):
    """One row of the qs-04 spec's inline cross-SDK fixture table.

    Field order mirrors the spec table's columns (``stored bucketing map``,
    ``rule value``, ``negated``, ``expected matched``). ``expects_warning``
    and ``store_only`` are additive per-row flags this task adds (they are
    not spec table columns) so one parametrize source can also drive AC8
    (the rows-6/7 warning assertion) and AC3 (row 8's DataStore-only
    persistence assertion) without a second, near-duplicate table.
    """

    row_number: int
    stored_bucketing: Mapping[str, str]
    rule_value: str
    negated: bool
    expected_matched: bool
    expects_warning: bool = False
    store_only: bool = False


#: The spec's inline 8-row table, copied verbatim (do NOT recompute — see
#: module docstring). Each row is a single-line ``MutualExclusionFixtureRow``
#: call, so there is no >=10-line near-duplicate block across rows.
EXCLUSION_FIXTURE_ROWS: Tuple[MutualExclusionFixtureRow, ...] = (
    MutualExclusionFixtureRow(1, {}, EXP_A_KEY, False, False),
    MutualExclusionFixtureRow(2, {}, EXP_A_KEY, True, True),
    MutualExclusionFixtureRow(3, {EXP_A_ID: VAR_A1}, EXP_A_KEY, False, True),
    MutualExclusionFixtureRow(4, {EXP_A_ID: VAR_A1}, EXP_A_KEY, True, False),
    MutualExclusionFixtureRow(5, {EXP_B_ID: VAR_B1}, EXP_A_KEY, True, True),
    MutualExclusionFixtureRow(6, {}, EXP_ZZ_KEY, False, False, expects_warning=True),
    MutualExclusionFixtureRow(7, {}, EXP_ZZ_KEY, True, True, expects_warning=True),
    MutualExclusionFixtureRow(
        8, {EXP_A_ID: VAR_A1}, EXP_A_KEY, True, False, store_only=True
    ),
)


def _variation(variation_id: str) -> Dict[str, Any]:
    """A single 100%-traffic RUNNING baseline variation.

    Both ``exp-a`` and ``exp-b`` need exactly this shape (spec: "one running
    variation each (100% traffic, is_baseline)"); factored into a one-line-
    per-call helper so the two experience literals below don't duplicate this
    5-key dict (SonarQube new-code-duplication discipline).
    """
    return {
        "id": variation_id,
        "key": "original",
        "status": "running",
        "traffic_allocation": 100.0,
        "is_baseline": True,
    }


def _experience(experience_id: str, key: str, variation_id: str) -> Dict[str, Any]:
    """A minimal ``a/b_fullstack`` / ``active`` experience with one variation."""
    return {
        "id": experience_id,
        "key": key,
        "type": "a/b_fullstack",
        "status": "active",
        "variations": [_variation(variation_id)],
    }


def build_mutual_exclusion_config() -> Dict[str, Any]:
    """Build the minimal exp-a/exp-b served config the fixture rows assume.

    ``exp-zz`` (rows 6/7) is deliberately absent — the whole point of those
    rows is an unresolvable target key. No exclusion audience /
    ``matching_options`` is wired onto either experience; that is PY-3's seam
    (qs-04 PY-3), not this data-only fixture.
    """
    return {
        "account_id": "100123",
        "project": {"id": "200456"},
        "experiences": [
            _experience(EXP_A_ID, EXP_A_KEY, VAR_A1),
            _experience(EXP_B_ID, EXP_B_KEY, VAR_B1),
        ],
        "features": [],
        "goals": [],
        "audiences": [],
        "segments": [],
    }
