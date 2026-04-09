"""Stable public import boundary for the Convert Python SDK."""

from .config import SDKConfig, TransportConfig
from .context import Context
from .core import Core
from .domain.results import (
    ConversionEvent,
    ConversionResult,
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
)
from .errors import (
    ConfigLoadError,
    ConfigValidationError,
    ConversionDataError,
    GoalNotFoundError,
    InitializationError,
    TrackingError,
)
from .version import __version__

__all__ = [
    "ConfigLoadError",
    "ConfigValidationError",
    "ConversionDataError",
    "Context",
    "Core",
    "ConversionEvent",
    "ConversionResult",
    "ExperienceResult",
    "FeatureResult",
    "FeatureStatus",
    "GoalNotFoundError",
    "InitializationError",
    "SDKConfig",
    "TrackingError",
    "TransportConfig",
    "__version__",
]
