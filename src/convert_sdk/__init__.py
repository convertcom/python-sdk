"""Stable public import boundary for the Convert Python SDK."""

from .config import SDKConfig, TrackingConfig, TransportConfig
from .context import Context
from .core import Core
from .domain.results import (
    ConversionEvent,
    ConversionResult,
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
    TrackingFlushResult,
)
from .errors import (
    ConfigLoadError,
    ConfigValidationError,
    ConversionDataError,
    GoalNotFoundError,
    InitializationError,
    TrackingError,
)
from .events import LifecycleEvent, LifecycleEventPayload
from .adapters.storage import InMemoryDataStore
from .ports.storage import DataStore
from .version import __version__

__all__ = [
    "ConfigLoadError",
    "ConfigValidationError",
    "ConversionDataError",
    "Context",
    "Core",
    "ConversionEvent",
    "ConversionResult",
    "DataStore",
    "ExperienceResult",
    "FeatureResult",
    "FeatureStatus",
    "GoalNotFoundError",
    "InMemoryDataStore",
    "InitializationError",
    "LifecycleEvent",
    "LifecycleEventPayload",
    "SDKConfig",
    "TrackingConfig",
    "TrackingFlushResult",
    "TrackingError",
    "TransportConfig",
    "__version__",
]
