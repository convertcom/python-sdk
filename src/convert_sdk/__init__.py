"""Convert Python SDK — public import boundary.

Canonical naming (qs-01): the distribution name on PyPI is
``convert-python-sdk`` while the import package is ``convert_sdk``. The two
differ by design — the hyphenated name is the discoverability surface on PyPI;
the snake_case name is the ergonomic import path.

Story 1.1 freezes the public surface to ``Core``, ``Context`` and
``__version__`` (the latter two are placeholders until later stories implement
behavior). Subsequent stories extend this surface per the Public Surface
Rollout schedule in qs-01 — never by renaming what is frozen here.

Story 1.2 extends the surface with the initialization config types
(``SDKConfig``, ``TransportConfig``) and the typed initialization/config error
hierarchy (``ConvertSDKError`` and its subclasses), without altering the frozen
Story 1.1 boundary.
"""

from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.context import Context
from convert_sdk.core import Core
from convert_sdk.errors import (
    ConfigError,
    ConfigLoadError,
    ConvertSDKError,
    InvalidConfigError,
    TransportError,
)
from convert_sdk.version import __version__

__all__ = [
    # Frozen Story 1.1 boundary.
    "Core",
    "Context",
    "__version__",
    # Story 1.2 initialization config.
    "SDKConfig",
    "TransportConfig",
    # Story 1.2 typed error hierarchy.
    "ConvertSDKError",
    "ConfigError",
    "InvalidConfigError",
    "ConfigLoadError",
    "TransportError",
]
