from __future__ import annotations

import pytest

from parity_utils import assert_parity, build_context, load_fixture_bundle


FIXTURE_BUNDLE = load_fixture_bundle("rule_vectors.json")


@pytest.mark.parametrize(
    "scenario",
    FIXTURE_BUNDLE["scenarios"],
    ids=[scenario["name"] for scenario in FIXTURE_BUNDLE["scenarios"]],
)
def test_js_rule_parity(scenario) -> None:
    context = build_context(FIXTURE_BUNDLE, scenario)

    actual = {
        "matched_segment_keys": list(
            context.run_custom_segments(
                scenario["segment_keys"],
                rule_data=scenario.get("rule_data") or {},
            )
        )
    }

    assert_parity(
        scenario["name"],
        actual,
        scenario["expected"],
    )
