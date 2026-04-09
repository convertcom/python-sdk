"""Local experience selection against the immutable config snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..domain.config_snapshot import ConfigSnapshot
from ..domain.results import ExperienceResult
from .bucketing import select_variation
from .rules import evaluate_rules


@dataclass(frozen=True)
class SelectedVariation:
    """Internal selected variation details used by experience/feature evaluation."""

    experience: Mapping[str, Any]
    variation: Mapping[str, Any]
    bucket_value: int


def evaluate_experience(
    snapshot: ConfigSnapshot,
    *,
    experience_key: str,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
) -> ExperienceResult | None:
    """Return the typed result for a single experience or ``None``."""

    selected = select_experience(
        snapshot,
        experience_key=experience_key,
        visitor_id=visitor_id,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
    )
    if selected is None:
        return None
    return _build_experience_result(selected)


def evaluate_experiences(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
) -> list[ExperienceResult]:
    """Return all applicable typed experience results for a visitor."""

    return [
        _build_experience_result(selected)
        for selected in select_experiences(
            snapshot,
            visitor_id=visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location_attributes,
            environment=environment,
        )
    ]


def select_experience(
    snapshot: ConfigSnapshot,
    *,
    experience_key: str,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
) -> SelectedVariation | None:
    """Return the internal selected variation details for a single experience."""

    experience = snapshot.experiences_by_key.get(experience_key)
    if experience is None:
        return None
    if not _experience_qualifies(
        snapshot,
        experience,
        visitor_attributes=visitor_attributes,
        location_attributes=location_attributes,
        environment=environment,
    ):
        return None

    variations = tuple(_iter_mappings(experience.get("variations")))
    if not variations:
        return None

    bucketed = select_variation(
        variations,
        visitor_id=visitor_id,
        experience_id=str(experience.get("id", experience_key)),
        bucketing_config=_as_mapping(snapshot.raw_data.get("bucketing")),
    )
    if bucketed is None:
        return None

    variation, bucket_value = bucketed
    return SelectedVariation(
        experience=experience,
        variation=variation,
        bucket_value=bucket_value,
    )


def select_experiences(
    snapshot: ConfigSnapshot,
    *,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
) -> list[SelectedVariation]:
    """Return internal selected variation details for all applicable experiences."""

    selected_variations: list[SelectedVariation] = []
    for experience in _iter_mappings(snapshot.raw_data.get("experiences")):
        experience_key = experience.get("key")
        if experience_key in (None, ""):
            continue
        selected = select_experience(
            snapshot,
            experience_key=str(experience_key),
            visitor_id=visitor_id,
            visitor_attributes=visitor_attributes,
            location_attributes=location_attributes,
            environment=environment,
        )
        if selected is not None:
            selected_variations.append(selected)
    return selected_variations


def _build_experience_result(selected: SelectedVariation) -> ExperienceResult:
    experience = selected.experience
    variation = selected.variation
    return ExperienceResult(
        experience_id=str(experience.get("id", "")),
        experience_key=str(experience.get("key", "")),
        experience_name=_as_optional_string(experience.get("name")),
        variation_id=str(variation.get("id", "")),
        variation_key=str(variation.get("key", "")),
        variation_name=_as_optional_string(variation.get("name")),
        bucket_value=selected.bucket_value,
    )


def _experience_qualifies(
    snapshot: ConfigSnapshot,
    experience: Mapping[str, Any],
    *,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None,
) -> bool:
    status = experience.get("status")
    if status not in (None, "", "active"):
        return False

    if not _environment_matches(experience, environment):
        return False

    if not _location_matches(experience, location_attributes):
        return False

    return _audiences_match(snapshot, experience, visitor_attributes)


def _environment_matches(experience: Mapping[str, Any], environment: str | None) -> bool:
    if environment in (None, ""):
        return True

    environments = tuple(str(value) for value in experience.get("environments", ()) if value not in (None, ""))
    if not environments:
        return True
    return environment in environments


def _location_matches(
    experience: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
) -> bool:
    site_area = _as_mapping(experience.get("site_area"))
    if site_area is None:
        return True
    return evaluate_rules(site_area, location_attributes)


def _audiences_match(
    snapshot: ConfigSnapshot,
    experience: Mapping[str, Any],
    visitor_attributes: Mapping[str, Any],
) -> bool:
    audience_ids = tuple(str(value) for value in experience.get("audiences", ()) if value not in (None, ""))
    if not audience_ids:
        return True

    results = []
    for audience_id in audience_ids:
        audience = snapshot.audiences_by_id.get(audience_id)
        if audience is None:
            results.append(False)
            continue
        audience_status = audience.get("status")
        if audience_status not in (None, "", "active"):
            results.append(False)
            continue
        results.append(evaluate_rules(_as_mapping(audience.get("rules")), visitor_attributes))

    match_mode = (
        _as_mapping(experience.get("settings")) or {}
    ).get("matching_options", {})
    if isinstance(match_mode, Mapping):
        audiences_mode = str(match_mode.get("audiences", "any"))
    else:
        audiences_mode = "any"

    return all(results) if audiences_mode == "all" else any(results)


def _iter_mappings(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _as_mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    return None


def _as_optional_string(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)
