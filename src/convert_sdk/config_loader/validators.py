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
            "Provide exactly one of sdk_key or config_data when initializing Core"
        )

    if config.sdk_key_secret and not config.sdk_key:
        raise ConfigValidationError("sdk_key_secret requires sdk_key initialization")

    if has_sdk_key and not config.transport.config_endpoint.startswith("https://"):
        raise ConfigValidationError(
            "config_endpoint must use HTTPS for sdk_key initialization"
        )

    if not config.transport.tracking_endpoint.startswith("https://"):
        raise ConfigValidationError("tracking_endpoint must use HTTPS")

    if config.tracking.batch_size < 1:
        raise ConfigValidationError("tracking.batch_size must be greater than zero")

    if not config.tracking.source.strip():
        raise ConfigValidationError("tracking.source must be a non-empty string")

    if has_config_data:
        validate_config_data(config.config_data)


def validate_config_data(config_data: Mapping[str, Any] | None) -> None:
    if config_data is None or not isinstance(config_data, Mapping):
        raise ConfigValidationError("config_data must be a mapping")

    project = config_data.get("project")
    if not isinstance(project, Mapping):
        raise ConfigValidationError("config_data must include a project mapping")

    project_id = project.get("id")
    if project_id in (None, ""):
        raise ConfigValidationError("config_data.project.id is required")
