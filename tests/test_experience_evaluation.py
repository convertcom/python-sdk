from __future__ import annotations

from typing import Any, Mapping

from convert_sdk import Core, ExperienceResult, SDKConfig


def sample_config_payload() -> Mapping[str, Any]:
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
            },
            {
                "id": "exp-global",
                "key": "sitewide-announcement",
                "name": "Sitewide Announcement",
                "status": "active",
                "variations": [
                    {
                        "id": "var-global",
                        "key": "announcement",
                        "name": "Announcement",
                        "status": "running",
                        "traffic_allocation": 100.0,
                        "changes": [],
                    }
                ],
            },
        ],
        "goals": [{"id": "goal-1", "key": "purchase"}],
    }


def build_context(visitor_id: str, visitor_attributes: Mapping[str, Any]) -> Any:
    core = Core(
        SDKConfig(
            config_data=sample_config_payload(),
            environment="production",
        )
    )
    return core.create_context(visitor_id, visitor_attributes)


def test_run_experience_returns_a_typed_result_for_a_qualified_visitor() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    result = context.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "checkout-flow"
    assert result.variation_key in {"control", "free-shipping"}
    assert 0 <= result.bucket_value < 10000


def test_run_experience_returns_none_for_missing_or_unqualified_results() -> None:
    unqualified_context = build_context("visitor-123", {"tier": "free"})

    assert (
        unqualified_context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        is None
    )
    assert unqualified_context.run_experience("missing-experience") is None


def test_run_experience_is_deterministic_for_the_same_visitor_and_snapshot() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    first = context.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )
    second = context.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    assert first == second


def test_run_experience_uses_updated_mutable_context_state() -> None:
    context = build_context("visitor-123", {"tier": "free"})

    assert (
        context.run_experience(
            "checkout-flow",
            location_attributes={"path": "/checkout"},
        )
        is None
    )

    context.update_visitor_properties({"tier": "premium"})

    result = context.run_experience(
        "checkout-flow",
        location_attributes={"path": "/checkout"},
    )

    assert isinstance(result, ExperienceResult)
    assert result.experience_key == "checkout-flow"


def test_run_experiences_returns_only_applicable_results() -> None:
    context = build_context("visitor-123", {"tier": "premium"})

    results = context.run_experiences(location_attributes={"path": "/checkout"})

    assert [result.experience_key for result in results] == [
        "checkout-flow",
        "sitewide-announcement",
    ]
