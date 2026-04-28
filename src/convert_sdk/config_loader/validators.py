"""Validation helpers for SDK initialization and config ingestion."""

from __future__ import annotations

from typing import Any, Mapping

from ..config import SDKConfig
from ..errors import ConfigValidationError


def validate_sdk_config(config: SDKConfig) -> None:
    has_sdk_key = bool(config.sdk_key)
    has_config_data = config.config_data is not None

    if has_sdk_key == has_config_data:
        raise ConfigValidationError(
            "Provide exactly one of sdk_key or config_data when initializing Core",
            code="config.invalid_source",
            context={
                "reason": "exactly_one_config_source_required",
                "has_sdk_key": has_sdk_key,
                "has_config_data": has_config_data,
            },
        )

    if config.sdk_key_secret and not config.sdk_key:
        raise ConfigValidationError(
            "sdk_key_secret requires sdk_key initialization",
            code="config.invalid_secret_usage",
            context={"reason": "sdk_key_secret_without_sdk_key"},
        )

    if has_sdk_key and not config.transport.config_endpoint.startswith("https://"):
        raise ConfigValidationError(
            "config_endpoint must use HTTPS for sdk_key initialization",
            code="config.insecure_endpoint",
            context={"reason": "config_endpoint_must_use_https"},
        )

    if not config.transport.tracking_endpoint.startswith("https://"):
        raise ConfigValidationError(
            "tracking_endpoint must use HTTPS",
            code="config.insecure_endpoint",
            context={"reason": "tracking_endpoint_must_use_https"},
        )

    if config.tracking.batch_size < 1:
        raise ConfigValidationError(
            "tracking.batch_size must be greater than zero",
            code="config.invalid_tracking",
            context={"reason": "tracking_batch_size_must_be_positive"},
        )

    if not config.tracking.source.strip():
        raise ConfigValidationError(
            "tracking.source must be a non-empty string",
            code="config.invalid_tracking",
            context={"reason": "tracking_source_required"},
        )

    if has_config_data:
        validate_config_data(config.config_data)


def validate_config_data(config_data: Mapping[str, Any] | None) -> None:
    if config_data is None or not isinstance(config_data, Mapping):
        raise ConfigValidationError(
            "config_data must be a mapping",
            code="config.invalid_data",
            context={"reason": "config_data_must_be_mapping"},
        )

    project = config_data.get("project")
    if not isinstance(project, Mapping):
        raise ConfigValidationError(
            "config_data must include a project mapping",
            code="config.invalid_data",
            context={"reason": "project_mapping_required", "field": "project"},
        )

    project_id = project.get("id")
    if project_id in (None, ""):
        raise ConfigValidationError(
            "config_data.project.id is required",
            code="config.invalid_data",
            context={"reason": "project_id_required", "field": "project.id"},
        )

    # Type-check the optional list-shaped collections at the boundary
    # so an upstream returning an HTML page or a string-typed payload
    # is rejected with a clean diagnostic instead of silently producing
    # an empty index downstream. Missing keys remain valid (the
    # normalizer fills them with empty tuples).
    for field in (
        "experiences",
        "features",
        "goals",
        "audiences",
        "segments",
        "archived_experiences",
    ):
        if field not in config_data:
            continue
        value = config_data[field]
        if value is None:
            continue
        if isinstance(value, (str, bytes, bytearray)):
            raise ConfigValidationError(
                f"config_data.{field} must be a list, not a string",
                code="config.invalid_data",
                context={"reason": "list_field_must_be_sequence", "field": field},
            )
        if not isinstance(value, (list, tuple, Mapping)):
            raise ConfigValidationError(
                f"config_data.{field} must be a list",
                code="config.invalid_data",
                context={"reason": "list_field_must_be_sequence", "field": field},
            )
