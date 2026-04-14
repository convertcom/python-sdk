from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from convert_sdk import Core, ExperienceResult, FeatureResult, SDKConfig


FIXTURES_DIR = Path(__file__).resolve().parent / "parity" / "fixtures"


def load_fixture_bundle(name: str) -> Mapping[str, Any]:
    return json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))


def build_context(bundle: Mapping[str, Any], scenario: Mapping[str, Any]):
    core = Core(
        SDKConfig(
            config_data=bundle["config_data"],
            environment=bundle["environment"],
        )
    )
    return core.create_context(
        scenario["visitor_id"],
        scenario.get("context_visitor_attributes") or {},
    )


def normalize_experience_result(result: ExperienceResult | None) -> Mapping[str, Any] | None:
    if result is None:
        return None
    return {
        "experience_id": result.experience_id,
        "experience_key": result.experience_key,
        "variation_id": result.variation_id,
        "variation_key": result.variation_key,
    }


def normalize_feature_result(result: FeatureResult | None) -> Mapping[str, Any]:
    if result is None:
        return {"matched": False}
    return {
        "matched": True,
        "experience_id": result.experience_id,
        "experience_key": result.experience_key,
        "feature_id": result.feature_id,
        "feature_key": result.feature_key,
        "status": result.status.value,
        "variables": to_plain_data(result.variables),
    }


def normalize_entity(entity: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    if entity is None:
        return None
    return {
        "id": str(entity.get("id", "")),
        "key": str(entity.get("key", "")),
    }


def to_plain_data(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [to_plain_data(item) for item in value]
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    return value


def assert_parity(name: str, actual: Any, expected: Any) -> None:
    assert actual == expected, (
        f"Parity drift for scenario {name!r}\n"
        f"expected: {json.dumps(expected, indent=2, sort_keys=True)}\n"
        f"actual:   {json.dumps(actual, indent=2, sort_keys=True)}"
    )
