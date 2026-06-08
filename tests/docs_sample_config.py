"""Shared offline config for the Story 4.5 documentation samples.

The advanced topic guides import this so each runnable sample can focus on the
API call under discussion rather than rebuilding a fixture. It is a superset of
the Story 1.6 ``examples/_sample_config.py`` payload: experiences with a
fullStack feature change, declared goals (for the tracking guide), and segments
with a simple country rule (for the evaluation guide's custom-segment sample).

There are no secrets here — every identifier is a placeholder, and the
``sdk_key`` flow in the guides reads its key from ``CONVERT_SDK_KEY``.
"""

from __future__ import annotations

from typing import Any, Dict


def _rule_country(value: str) -> dict:
    """A single-condition rule matching ``country == value`` (segments guide)."""
    return {
        "OR": [
            {
                "AND": [
                    {
                        "OR_WHEN": [
                            {
                                "matching": {"match_type": "equals", "negated": False},
                                "key": "country",
                                "value": value,
                            }
                        ]
                    }
                ]
            }
        ]
    }


SAMPLE_CONFIG: Dict[str, Any] = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "features": [
        {
            "id": "10024",
            "key": "checkout-banner",
            "name": "Checkout Banner",
            "variables": [
                {"key": "enabled", "type": "boolean"},
                {"key": "headline", "type": "string"},
                {"key": "max_items", "type": "integer"},
            ],
        }
    ],
    "goals": [
        {"id": "g1", "key": "purchase_completed"},
        {"id": "g2", "key": "signup"},
    ],
    "segments": [
        {"id": "s_us", "key": "us-visitors", "rules": _rule_country("US")},
        {"id": "s_de", "key": "de-visitors", "rules": _rule_country("DE")},
    ],
    "audiences": [],
    "experiences": [
        {
            "id": "e1",
            "key": "checkout-experiment",
            "variations": [
                {
                    "id": "v1",
                    "key": "control",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c1",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "false",
                                    "headline": "Standard checkout",
                                    "max_items": "3",
                                },
                            },
                        }
                    ],
                },
                {
                    "id": "v2",
                    "key": "treatment",
                    "traffic_allocation": 50.0,
                    "changes": [
                        {
                            "id": "c2",
                            "type": "fullStackFeature",
                            "data": {
                                "feature_id": "10024",
                                "variables_data": {
                                    "enabled": "true",
                                    "headline": "Free shipping over $50!",
                                    "max_items": "5",
                                },
                            },
                        }
                    ],
                },
            ],
        }
    ],
}
