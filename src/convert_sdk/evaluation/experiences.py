"""Local experience selection against the immutable config snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from ..domain.config_snapshot import ConfigSnapshot
from ..domain.results import ExperienceDiagnostic, ExperienceResult
from .bucketing import get_bucket_value, select_variation
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


def diagnose_experience(
    snapshot: ConfigSnapshot,
    *,
    experience_key: str,
    visitor_id: str,
    visitor_attributes: Mapping[str, Any],
    location_attributes: Mapping[str, Any],
    environment: str | None = None,
) -> ExperienceDiagnostic:
    """Return a typed diagnostic outcome for a single experience request."""

    experience = snapshot.experiences_by_key.get(experience_key)
    if experience is None:
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="experience_not_found",
            message="Experience was not found in the current config snapshot.",
            details={"entity_key": experience_key},
        )

    details = _experience_details(snapshot, experience, environment=environment)
    status = experience.get("status")
    if status not in (None, "", "active"):
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="experience_inactive",
            message="Experience exists but is not active.",
            details={**details, "status": str(status)},
        )

    if not _environment_matches(experience, environment):
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="environment_mismatch",
            message="Experience does not target the requested environment.",
            details=details,
        )

    if not _location_matches(experience, location_attributes):
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="location_mismatch",
            message="Experience location rules did not match the request.",
            details=details,
        )

    if not _audiences_match(snapshot, experience, visitor_attributes):
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="audience_mismatch",
            message="Visitor did not match the experience audiences.",
            details=details,
        )

    variations = tuple(_iter_mappings(experience.get("variations")))
    if not variations:
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="no_variations",
            message="Experience has no selectable variations.",
            details=details,
        )

    experience_id = str(experience.get("id", experience_key))
    bucket_value = get_bucket_value(
        visitor_id,
        experience_id,
        **_bucketing_options(snapshot),
    )
    bucketed = select_variation(
        variations,
        visitor_id=visitor_id,
        experience_id=experience_id,
        bucketing_config=_as_mapping(snapshot.raw_data.get("bucketing")),
    )
    if bucketed is None:
        return ExperienceDiagnostic(
            experience_key=experience_key,
            resolved=False,
            reason="no_variation_selected",
            message="Visitor was not allocated to a running variation.",
            details={**details, "bucket_value": bucket_value},
        )

    variation, selected_bucket_value = bucketed
    selected = SelectedVariation(
        experience=experience,
        variation=variation,
        bucket_value=selected_bucket_value,
    )
    result = _build_experience_result(selected)
    return ExperienceDiagnostic(
        experience_key=experience_key,
        resolved=True,
        reason="resolved",
        message="Experience resolved to a variation.",
        result=result,
        details={
            **details,
            "bucket_value": result.bucket_value,
            "variation_key": result.variation_key,
            "variation_id": result.variation_id,
        },
    )


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


def _experience_details(
    snapshot: ConfigSnapshot,
    experience: Mapping[str, Any],
    *,
    environment: str | None,
) -> Mapping[str, Any]:
    variations = tuple(_iter_mappings(experience.get("variations")))
    audience_ids = tuple(
        str(value) for value in experience.get("audiences", ()) if value not in (None, "")
    )
    return {
        "entity_key": str(experience.get("key", "")),
        "entity_id": str(experience.get("id", "")),
        "environment": environment,
        "has_account_id": snapshot.account_id is not None,
        "has_project_id": snapshot.project_id is not None,
        "audience_count": len(audience_ids),
        "variation_count": len(variations),
    }


def _bucketing_options(snapshot: ConfigSnapshot) -> Mapping[str, int]:
    bucketing_config = _as_mapping(snapshot.raw_data.get("bucketing"))
    if bucketing_config is None:
        return {}
    options: dict[str, int] = {}
    if bucketing_config.get("hash_seed") is not None:
        options["seed"] = int(bucketing_config["hash_seed"])
    if bucketing_config.get("max_traffic") is not None:
        options["max_traffic"] = int(bucketing_config["max_traffic"])
    return options


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
