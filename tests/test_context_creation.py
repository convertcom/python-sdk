from __future__ import annotations

from typing import Any, Mapping

import pytest

from convert_sdk import Context, Core, SDKConfig


def sample_config_payload() -> Mapping[str, Any]:
    return {
        "account_id": "1001",
        "project": {"id": "2002", "name": "Demo"},
        "experiences": [{"id": "3003", "key": "exp-home"}],
        "features": [{"id": "4004", "key": "feature-checkout"}],
        "goals": [{"id": "5005", "key": "purchase"}],
        "audiences": [{"id": "6006", "key": "vip-users"}],
    }


def build_core() -> Core:
    return Core(SDKConfig(config_data=sample_config_payload()))


def test_create_context_returns_a_scoped_context_with_visitor_attributes() -> None:
    core = build_core()

    context = core.create_context(
        "visitor-123",
        {
            "country": "US",
            "profile": {"plan": "pro"},
        },
    )

    assert isinstance(context, Context)
    assert context.visitor_id == "visitor-123"
    assert context.visitor_attributes["country"] == "US"
    assert context.visitor_attributes["profile"]["plan"] == "pro"
    assert context._snapshot is core.snapshot

    with pytest.raises(TypeError):
        context.visitor_attributes["country"] = "CA"

    with pytest.raises(TypeError):
        context.visitor_attributes["profile"]["plan"] = "basic"


def test_context_can_be_reused_across_multiple_overlay_preparations() -> None:
    context = build_core().create_context(
        "visitor-123",
        {"country": "US"},
    )

    first_overlay = context._resolve_visitor_attributes({"request_id": "one"})
    second_overlay = context._resolve_visitor_attributes({"request_id": "two"})

    assert first_overlay["country"] == "US"
    assert second_overlay["country"] == "US"
    assert first_overlay["request_id"] == "one"
    assert second_overlay["request_id"] == "two"
    assert context.visitor_attributes == {"country": "US"}


def test_request_specific_attributes_override_stored_values_without_mutation() -> None:
    context = build_core().create_context(
        "visitor-123",
        {"country": "US", "plan": "free"},
    )

    resolved_attributes = context._resolve_visitor_attributes(
        {"plan": "pro", "city": "Karachi"},
    )

    assert resolved_attributes == {
        "country": "US",
        "plan": "pro",
        "city": "Karachi",
    }
    assert context.visitor_attributes == {
        "country": "US",
        "plan": "free",
    }

    with pytest.raises(TypeError):
        resolved_attributes["plan"] = "enterprise"
