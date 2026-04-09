"""Local feature resolution from selected variations."""

from __future__ import annotations

import json
from typing import Any, Iterable, Mapping, Sequence

from ..domain.config_snapshot import ConfigSnapshot
from ..domain.config_snapshot import freeze_value
from ..domain.results import FeatureResult, FeatureStatus, freeze_variables
from .experiences import SelectedVariation, select_experiences


FULLSTACK_FEATURE_TYPES = {
    "fullstackfeature",
}


def evaluate_feature(
    snapshot: ConfigSnapshot,
    *,
    feature_key: str,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
    type_cast: bool = True,
) -> FeatureResult | None:
    """Return the first applicable feature result for a feature key."""

    feature_results = evaluate_features(
        snapshot,
        visitor_id=visitor_id,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
        type_cast=type_cast,
        feature_keys=(feature_key,),
    )
    return feature_results[0] if feature_results else None


def evaluate_features(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
    type_cast: bool = True,
    feature_keys: Sequence[str] | None = None,
) -> list[FeatureResult]:
    """Return all applicable feature results from the selected variations."""

    selected_feature_keys = set(feature_keys or ())
    results: list[FeatureResult] = []
    for selected in select_experiences(
        snapshot,
        visitor_id=visitor_id,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
    ):
        for feature_result in _feature_results_from_selection(
            snapshot,
            selected,
            type_cast=type_cast,
        ):
            if selected_feature_keys and feature_result.feature_key not in selected_feature_keys:
                continue
            results.append(feature_result)
    return results


def _feature_results_from_selection(
    snapshot: ConfigSnapshot,
    selected: SelectedVariation,
    *,
    type_cast: bool,
) -> Iterable[FeatureResult]:
    variation = selected.variation
    for change in _iter_mappings(variation.get("changes")):
        if not _is_feature_change(change):
            continue

        data = change.get("data")
        if not isinstance(data, Mapping):
            continue

        feature_id = data.get("feature_id")
        if feature_id in (None, ""):
            continue

        feature_definition = snapshot.features_by_id.get(str(feature_id))
        if feature_definition is None:
            continue

        variables = _cast_variables(
            feature_definition,
            data.get("variables_data"),
            type_cast=type_cast,
        )
        experience = selected.experience
        yield FeatureResult(
            feature_id=str(feature_definition.get("id", feature_id)),
            feature_key=str(feature_definition.get("key", "")),
            feature_name=_as_optional_string(feature_definition.get("name")),
            status=FeatureStatus.ENABLED,
            variables=variables,
            experience_id=str(experience.get("id", "")),
            experience_key=str(experience.get("key", "")),
            experience_name=_as_optional_string(experience.get("name")),
            variation_id=str(variation.get("id", "")),
            variation_key=str(variation.get("key", "")),
        )


def _cast_variables(
    feature_definition: Mapping[str, Any],
    variables: Any,
    *,
    type_cast: bool,
) -> Mapping[str, Any]:
    if not isinstance(variables, Mapping):
        return freeze_variables(None)

    variable_definitions = {
        str(variable.get("key")): str(variable.get("type"))
        for variable in _iter_mappings(feature_definition.get("variables"))
        if variable.get("key") not in (None, "") and variable.get("type") not in (None, "")
    }

    cast_variables: dict[str, Any] = {}
    for key, value in variables.items():
        variable_key = str(key)
        variable_type = variable_definitions.get(variable_key)
        cast_value = (
            _cast_feature_value(value, variable_type)
            if type_cast and variable_type is not None
            else freeze_value(value)
        )
        cast_variables[variable_key] = cast_value
    return freeze_variables(cast_variables)


def _cast_feature_value(value: Any, variable_type: str) -> Any:
    normalized_type = variable_type.lower()
    if normalized_type == "boolean":
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
    if normalized_type == "integer":
        return int(value)
    if normalized_type == "string":
        return str(value)
    if normalized_type == "json":
        if isinstance(value, str):
            try:
                return freeze_value(json.loads(value))
            except json.JSONDecodeError:
                return value
        return freeze_value(value)
    return freeze_value(value)


def _is_feature_change(change: Mapping[str, Any]) -> bool:
    change_type = str(change.get("type", "")).replace("-", "_").replace(" ", "_")
    normalized_type = change_type.replace("_", "").lower()
    return normalized_type in FULLSTACK_FEATURE_TYPES


def _iter_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _as_optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
