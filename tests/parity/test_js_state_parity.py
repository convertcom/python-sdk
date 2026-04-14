from __future__ import annotations

import pytest

from parity_utils import assert_parity, build_context, load_fixture_bundle, normalize_entity


FIXTURE_BUNDLE = load_fixture_bundle("state_vectors.json")


@pytest.mark.parametrize(
    "scenario",
    FIXTURE_BUNDLE["scenarios"],
    ids=[scenario["name"] for scenario in FIXTURE_BUNDLE["scenarios"]],
)
def test_js_state_parity(scenario) -> None:
    context = build_context(FIXTURE_BUNDLE, scenario)

    actual = {
        "lookups_by_key": [
            {
                "label": lookup["label"],
                "entity_type": lookup["entity_type"],
                "lookup_key": lookup["lookup_key"],
                "expected": normalize_entity(
                    context.get_config_entity(
                        lookup["entity_type"],
                        lookup["lookup_key"],
                    )
                ),
            }
            for lookup in scenario["lookups_by_key"]
        ],
        "lookups_by_id": [
            {
                "label": lookup["label"],
                "entity_type": lookup["entity_type"],
                "entity_id": lookup["entity_id"],
                "expected": normalize_entity(
                    context.get_config_entity_by_id(
                        lookup["entity_type"],
                        lookup["entity_id"],
                    )
                ),
            }
            for lookup in scenario["lookups_by_id"]
        ],
    }

    assert_parity(
        scenario["name"],
        actual,
        {
            "lookups_by_key": scenario["lookups_by_key"],
            "lookups_by_id": scenario["lookups_by_id"],
        },
    )
