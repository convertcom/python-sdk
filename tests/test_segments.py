from __future__ import annotations

from typing import Any, Mapping

from convert_sdk import Core, SDKConfig

from test_experience_evaluation import sample_config_payload


def segment_config_payload() -> Mapping[str, Any]:
    payload = dict(sample_config_payload())
    payload["segments"] = [
        {
            "id": "seg-vip",
            "key": "vip-users",
            "name": "VIP Users",
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
        },
        {
            "id": "seg-pk",
            "key": "pakistan-visitors",
            "name": "Pakistan Visitors",
            "rules": {
                "OR": [
                    {
                        "AND": [
                            {
                                "OR_WHEN": [
                                    {
                                        "rule_type": "generic_text_key_value",
                                        "key": "country",
                                        "value": "PK",
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
        },
    ]
    return payload


def build_segment_context(
    visitor_id: str = "visitor-123",
    visitor_attributes: Mapping[str, Any] | None = None,
):
    core = Core(
        SDKConfig(
            config_data=segment_config_payload(),
            environment="production",
        )
    )
    return core.create_context(visitor_id, visitor_attributes or {"country": "US"})


def test_default_segments_persist_for_recreated_contexts() -> None:
    core = Core(
        SDKConfig(
            config_data=segment_config_payload(),
            environment="production",
        )
    )
    context = core.create_context("visitor-123", {"country": "US"})

    context.set_default_segments(["vip-users", "pakistan-visitors", "vip-users"])
    reloaded = core.create_context("visitor-123")

    assert context.default_segments == ("vip-users", "pakistan-visitors")
    assert reloaded.default_segments == ("vip-users", "pakistan-visitors")


def test_run_custom_segments_returns_matched_segment_keys() -> None:
    context = build_segment_context(visitor_attributes={"country": "US"})

    context.update_visitor_properties({"tier": "premium"})

    assert context.run_custom_segments(["vip-users", "pakistan-visitors"]) == (
        "vip-users",
    )
    assert context.run_custom_segments(
        ["vip-users", "pakistan-visitors"],
        rule_data={"country": "PK"},
    ) == ("vip-users", "pakistan-visitors")


def test_get_config_entity_helpers_support_key_id_variation_and_no_result() -> None:
    context = build_segment_context(visitor_attributes={"country": "PK", "tier": "premium"})

    experience = context.get_config_entity("experience", "checkout-flow")
    segment = context.get_config_entity("segments", "vip-users")
    variation = context.get_config_entity("variation", "free-shipping")

    assert experience is not None
    assert experience["id"] == "exp-checkout"
    assert segment is not None
    assert segment["id"] == "seg-vip"
    assert variation is not None
    assert variation["id"] == "var-treatment"

    assert context.get_config_entity_by_id("goal", "goal-1")["key"] == "purchase"
    assert context.get_config_entity_by_id("segment", "seg-pk")["key"] == "pakistan-visitors"
    assert context.get_config_entity_by_id("variation", "var-control")["key"] == "control"
    assert context.get_config_entity("feature", "missing-feature") is None
    assert context.get_config_entity_by_id("audience", "missing-audience") is None
