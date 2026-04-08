"""Config snapshot loading orchestration."""

from __future__ import annotations

from .normalizer import build_snapshot
from .validators import validate_config_data, validate_sdk_config
from ..config import SDKConfig
from ..domain.config_snapshot import ConfigSnapshot
from ..errors import ConfigLoadError
from ..ports.transport import ConfigRequest, Transport


def load_config_snapshot(config: SDKConfig, transport: Transport) -> ConfigSnapshot:
    validate_sdk_config(config)

    if config.config_data is not None:
        validate_config_data(config.config_data)
        return build_snapshot(config.config_data)

    request = ConfigRequest(
        sdk_key=config.sdk_key or "",
        sdk_key_secret=config.sdk_key_secret,
        environment=config.environment,
        transport=config.transport,
    )

    try:
        config_data = transport.fetch_config(request)
    except Exception as exc:  # noqa: BLE001
        raise ConfigLoadError(
            f"Config fetch failed for sdk_key '{config.sdk_key}'"
        ) from exc

    validate_config_data(config_data)
    return build_snapshot(config_data)
