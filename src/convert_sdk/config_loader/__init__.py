"""Config-loading boundary for the Convert Python SDK (Story 1.2).

Internal package (not part of the public import surface) that validates,
normalizes, and ingests raw config payloads into an immutable
:class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot`.
"""

from convert_sdk.config_loader.loader import load_snapshot
from convert_sdk.config_loader.normalizer import normalize_config
from convert_sdk.config_loader.validators import validate_config

__all__ = ["load_snapshot", "normalize_config", "validate_config"]
