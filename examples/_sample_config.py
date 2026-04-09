"""Shared direct-config payload used by Story 1.6 examples."""

from __future__ import annotations

from typing import Any, Mapping


def sample_config() -> Mapping[str, Any]:
    """Return a local config payload for runnable examples."""

    return {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "audiences": [
            {
                "id": "aud-premium",
                "key": "premium-visitors",
                "name": "Premium Visitors",
                "status": "active",
                "rules": {
                    "OR": [
                        {
                            "AND": [
                                {
                                    "OR_WHEN": [
                                        {
                                            "rule_type": "generic_text_key_value",
                                            "key": "tier",
                                            "value": "premium",
                                            "matching": {
                                                "match_type": "matches",
                                                "negated": False,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
            }
        ],
        "features": [
            {
                "id": "feature-banner",
                "key": "checkout-banner",
                "name": "Checkout Banner",
                "variables": [
                    {"key": "enabled", "type": "boolean"},
                    {"key": "title", "type": "string"},
                    {"key": "discount", "type": "integer"},
                    {"key": "payload", "type": "json"},
                ],
            }
        ],
        "experiences": [
            {
                "id": "exp-checkout",
                "key": "checkout-flow",
                "name": "Checkout Flow",
                "status": "active",
                "environments": ["production"],
                "audiences": ["aud-premium"],
                "site_area": {
                    "OR": [
                        {
                            "AND": [
                                {
                                    "OR_WHEN": [
                                        {
                                            "rule_type": "generic_text_key_value",
                                            "key": "path",
                                            "value": "/checkout",
                                            "matching": {
                                                "match_type": "matches",
                                                "negated": False,
                                            },
                                        }
                                    ]
                                }
                            ]
                        }
                    ]
                },
                "variations": [
                    {
                        "id": "var-control",
                        "key": "control",
                        "name": "Control",
                        "status": "running",
                        "traffic_allocation": 50.0,
                        "changes": [
                            {
                                "type": "fullStackFeature",
                                "data": {
                                    "feature_id": "feature-banner",
                                    "variables_data": {
                                        "enabled": "false",
                                        "title": "Standard checkout",
                                        "discount": "0",
                                        "payload": "{\"theme\":\"default\"}",
                                    },
                                },
                            }
                        ],
                    },
                    {
                        "id": "var-treatment",
                        "key": "free-shipping",
                        "name": "Free Shipping",
                        "status": "running",
                        "traffic_allocation": 50.0,
                        "changes": [
                            {
                                "type": "fullStackFeature",
                                "data": {
                                    "feature_id": "feature-banner",
                                    "variables_data": {
                                        "enabled": "true",
                                        "title": "Free shipping unlocked",
                                        "discount": "15",
                                        "payload": "{\"theme\":\"promo\"}",
                                    },
                                },
                            }
                        ],
                    },
                ],
            }
        ],
        "goals": [{"id": "goal-1", "key": "purchase"}],
    }
