"""Config snapshot loading orchestration."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from .normalizer import build_snapshot
from .validators import validate_config_data, validate_sdk_config
from ..config import SDKConfig
from ..diagnostics import config_source, log_diagnostic_event, snapshot_entity_counts
from ..domain.config_snapshot import ConfigSnapshot
from ..errors import ConfigLoadError, ConfigValidationError
from ..ports.transport import ConfigRequest, Transport


def load_config_snapshot(config: SDKConfig, transport: Transport) -> ConfigSnapshot:
    source = config_source(config.config_data, config.sdk_key)
    log_diagnostic_event(
        "config.load.started",
        source=source,
        has_environment=bool(config.environment),
    )
    try:
        validate_sdk_config(config)
    except ConfigValidationError as exc:
        log_diagnostic_event(
            "config.load.failed",
            level=logging.WARNING,
            source=source,
            error_type=type(exc).__name__,
            error_code=exc.code,
            reason=exc.context.get("reason"),
        )
        raise

    if config.config_data is not None:
        snapshot = _build_validated_snapshot(
            config.config_data,
            source=source,
            endpoint_host=None,
        )
        log_diagnostic_event(
            "config.load.succeeded",
            source=source,
            has_account_id=snapshot.account_id is not None,
            has_project_id=snapshot.project_id is not None,
            entity_counts=snapshot_entity_counts(snapshot),
        )
        return snapshot

    request = ConfigRequest(
        sdk_key=config.sdk_key or "",
        sdk_key_secret=config.sdk_key_secret,
        environment=config.environment,
        transport=config.transport,
    )

    try:
        config_data = transport.fetch_config(request)
    except Exception as exc:  # noqa: BLE001
        endpoint_host = _safe_hostname(config.transport.config_endpoint)
        log_diagnostic_event(
            "config.load.failed",
            level=logging.WARNING,
            source=source,
            error_type=type(exc).__name__,
            error_code="config.fetch_failed",
            endpoint_host=endpoint_host,
        )
        raise ConfigLoadError(
            "Config fetch failed; verify SDK key credentials, endpoint, and network access.",
            code="config.fetch_failed",
            context={
                "source": source,
                "endpoint_host": endpoint_host,
                "error_type": type(exc).__name__,
                "has_environment": bool(config.environment),
            },
        ) from None

    snapshot = _build_validated_snapshot(
        config_data,
        source=source,
        endpoint_host=_safe_hostname(config.transport.config_endpoint),
    )
    log_diagnostic_event(
        "config.load.succeeded",
        source=source,
        has_account_id=snapshot.account_id is not None,
        has_project_id=snapshot.project_id is not None,
        entity_counts=snapshot_entity_counts(snapshot),
    )
    return snapshot


def _build_validated_snapshot(
    config_data: object,
    *,
    source: str,
    endpoint_host: str | None,
) -> ConfigSnapshot:
    try:
        validate_config_data(config_data)  # type: ignore[arg-type]
        return build_snapshot(config_data)  # type: ignore[arg-type]
    except ConfigValidationError as exc:
        log_diagnostic_event(
            "config.load.failed",
            level=logging.WARNING,
            source=source,
            error_type=type(exc).__name__,
            error_code=exc.code,
            reason=exc.context.get("reason"),
            endpoint_host=endpoint_host,
        )
        raise
    except Exception as exc:  # noqa: BLE001
        log_diagnostic_event(
            "config.load.failed",
            level=logging.WARNING,
            source=source,
            error_type=type(exc).__name__,
            error_code="config.processing_failed",
            endpoint_host=endpoint_host,
        )
        raise ConfigValidationError(
            "Config processing failed; verify the project config shape.",
            code="config.processing_failed",
            context={
                "source": source,
                "endpoint_host": endpoint_host,
                "error_type": type(exc).__name__,
            },
        ) from None


def _safe_hostname(url: str) -> str | None:
    hostname = urlparse(url).hostname
    return hostname or None
