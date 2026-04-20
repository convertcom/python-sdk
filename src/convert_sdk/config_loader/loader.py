"""Config snapshot loading orchestration."""

from __future__ import annotations

import logging

from .normalizer import build_snapshot
from .validators import validate_config_data, validate_sdk_config
from ..config import SDKConfig
from ..diagnostics import config_source, log_diagnostic_event, snapshot_entity_counts
from ..domain.config_snapshot import ConfigSnapshot
from ..errors import ConfigLoadError
from ..ports.transport import ConfigRequest, Transport


def load_config_snapshot(config: SDKConfig, transport: Transport) -> ConfigSnapshot:
    source = config_source(config.config_data, config.sdk_key)
    log_diagnostic_event(
        "config.load.started",
        source=source,
        has_environment=bool(config.environment),
    )
    validate_sdk_config(config)

    if config.config_data is not None:
        validate_config_data(config.config_data)
        snapshot = build_snapshot(config.config_data)
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
        log_diagnostic_event(
            "config.load.failed",
            level=logging.WARNING,
            source=source,
            error_type=type(exc).__name__,
        )
        raise ConfigLoadError(
            f"Config fetch failed for sdk_key '{config.sdk_key}'"
        ) from exc

    validate_config_data(config_data)
    snapshot = build_snapshot(config_data)
    log_diagnostic_event(
        "config.load.succeeded",
        source=source,
        has_account_id=snapshot.account_id is not None,
        has_project_id=snapshot.project_id is not None,
        entity_counts=snapshot_entity_counts(snapshot),
    )
    return snapshot
