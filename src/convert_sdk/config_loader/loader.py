"""Config loading pipeline for the Convert Python SDK (Story 1.2).

Ties together validation → normalization → immutable snapshot construction.
This is the single entry point both direct-config and transport-backed
initialization funnel through, so the immutability and validation guarantees
hold regardless of how the raw payload arrived.
"""

from __future__ import annotations

from typing import Any, Mapping

from convert_sdk.config_loader.normalizer import normalize_config
from convert_sdk.config_loader.validators import validate_config
from convert_sdk.domain.config_snapshot import ConfigSnapshot


def load_snapshot(raw: Mapping[str, Any]) -> ConfigSnapshot:
    """Validate, normalize, and build an immutable :class:`ConfigSnapshot`.

    Raises:
        InvalidConfigError: if the raw payload fails boundary validation.
    """
    validate_config(raw)
    normalized = normalize_config(raw)
    return ConfigSnapshot.from_normalized(normalized)
