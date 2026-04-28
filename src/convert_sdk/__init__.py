"""Stable public import boundary for the Convert Python SDK."""

from .config import RefreshConfig, SDKConfig, TrackingConfig, TransportConfig
from .context import Context
from .core import Core
from .domain.results import (
    ConversionEvent,
    ConversionResult,
    EntityDiagnostic,
    ExperienceDiagnostic,
    ExperienceResult,
    FeatureDiagnostic,
    FeatureResult,
    FeatureStatus,
    GoalDiagnostic,
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
    "Context",
    "ConversionDataError",
    "ConversionEvent",
    "ConversionResult",
    "Core",
    "DataStore",
    "EntityDiagnostic",
    "ExperienceDiagnostic",
    "ExperienceResult",
    "FeatureDiagnostic",
    "FeatureResult",
    "FeatureStatus",
    "GoalDiagnostic",
    "GoalNotFoundError",
    "InMemoryDataStore",
    "InitializationError",
    "LifecycleEvent",
    "LifecycleEventPayload",
    "RefreshConfig",
    "SDKConfig",
    "TrackingConfig",
    "TrackingError",
    "TrackingFlushResult",
    "TransportConfig",
    "__version__",
]
