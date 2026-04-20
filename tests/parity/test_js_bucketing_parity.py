from __future__ import annotations

import pytest

from parity_utils import assert_parity, build_context, load_fixture_bundle, normalize_experience_result


FIXTURE_BUNDLE = load_fixture_bundle("bucketing_vectors.json")


@pytest.mark.parametrize(
    "scenario",
    FIXTURE_BUNDLE["scenarios"],
    ids=[scenario["name"] for scenario in FIXTURE_BUNDLE["scenarios"]],
)
def test_js_bucketing_parity(scenario) -> None:
    context = build_context(FIXTURE_BUNDLE, scenario)

    result = context.run_experience(
        scenario["experience_key"],
        visitor_attributes=scenario.get("request_visitor_attributes") or {},
        location_attributes=scenario.get("location_attributes") or {},
    )

    assert_parity(
        scenario["name"],
        normalize_experience_result(result),
        scenario["expected"],
    )
