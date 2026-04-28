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
from .config_loader.refresh import RefresherStatus
from .errors import (
    ConfigLoadError,
    ConfigValidationError,
    ConversionDataError,
    ConvertSDKError,
    GoalNotFoundError,
    InitializationError,
    TrackingDeliveryError,
    TrackingError,
)
from .events import LifecycleEvent, LifecycleEventPayload
from .adapters.storage import InMemoryDataStore
from .ports.event_bus import EventBus
from .ports.storage import DataStore
from .ports.transport import Transport
from .version import __version__

__all__ = [
    "ConfigLoadError",
    "ConfigValidationError",
    "Context",
    "ConversionDataError",
    "ConversionEvent",
    "ConversionResult",
    "ConvertSDKError",
    "Core",
    "DataStore",
    "EntityDiagnostic",
    "EventBus",
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
    "RefresherStatus",
    "SDKConfig",
    "TrackingConfig",
    "TrackingDeliveryError",
    "TrackingError",
    "TrackingFlushResult",
    "Transport",
    "TransportConfig",
    "__version__",
]
