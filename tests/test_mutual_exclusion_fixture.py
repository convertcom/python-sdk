"""Sanity tests for the qs-04 mutual-exclusion fixture scaffolding (PY-2).

This file is NOT the qs-04 rule-engine test suite — that is PY-3's TDD work
(RED against the not-yet-implemented ``bucketed_into_experience_key``
dispatch, then GREEN). This file only asserts the DATA-ONLY fixture shape
itself (``tests/fixtures/mutual_exclusion.py``) is correct: the shared 8-row
table matches the spec's inline cross-SDK fixture shape, and the minimal
exp-a/exp-b config fixture has the right ids/keys with ``exp-zz`` deliberately
absent. Each test below asserts a single, distinct invariant.
"""

from __future__ import annotations

from convert_sdk.config_loader import load_snapshot

from tests.fixtures.mutual_exclusion import (
    EXCLUSION_FIXTURE_ROWS,
    EXP_A_ID,
    EXP_A_KEY,
    EXP_B_ID,
    EXP_B_KEY,
    EXP_ZZ_KEY,
    VAR_A1,
    VAR_B1,
    build_mutual_exclusion_config,
)


def test_fixture_has_exactly_eight_rows() -> None:
    assert len(EXCLUSION_FIXTURE_ROWS) == 8


def test_expects_warning_flag_set_on_rows_six_and_seven_only() -> None:
    flagged = {row.row_number for row in EXCLUSION_FIXTURE_ROWS if row.expects_warning}
    assert flagged == {6, 7}


def test_store_only_flag_set_on_row_eight_only() -> None:
    flagged = {row.row_number for row in EXCLUSION_FIXTURE_ROWS if row.store_only}
    assert flagged == {8}


def test_config_omits_exp_zz_target_key() -> None:
    snapshot = load_snapshot(build_mutual_exclusion_config())
    assert snapshot.get_experience_by_key(EXP_ZZ_KEY) is None


def test_config_carries_exp_a_and_exp_b_with_expected_ids_and_variations() -> None:
    snapshot = load_snapshot(build_mutual_exclusion_config())

    exp_a = snapshot.get_experience_by_key(EXP_A_KEY)
    exp_b = snapshot.get_experience_by_key(EXP_B_KEY)

    assert exp_a is not None
    assert exp_b is not None
    assert str(exp_a["id"]) == EXP_A_ID
    assert str(exp_b["id"]) == EXP_B_ID
    assert str(exp_a["variations"][0]["id"]) == VAR_A1
    assert str(exp_b["variations"][0]["id"]) == VAR_B1
