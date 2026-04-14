from importlib import resources

from convert_sdk import (
    ConversionDataError,
    Context,
    ConversionEvent,
    ConversionResult,
    Core,
    DataStore,
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
    GoalNotFoundError,
    InMemoryDataStore,
    LifecycleEvent,
    LifecycleEventPayload,
    SDKConfig,
    TrackingConfig,
    TrackingFlushResult,
    TrackingError,
    TransportConfig,
    __version__,
)


def test_public_import_boundary_is_stable() -> None:
    assert Core.__module__ == "convert_sdk.core"
    assert Context.__module__ == "convert_sdk.context"
    assert SDKConfig.__module__ == "convert_sdk.config"
    assert TrackingConfig.__module__ == "convert_sdk.config"
    assert TransportConfig.__module__ == "convert_sdk.config"
    assert ConversionEvent.__module__ == "convert_sdk.domain.results"
    assert ConversionResult.__module__ == "convert_sdk.domain.results"
    assert ConversionDataError.__module__ == "convert_sdk.errors"
    assert DataStore.__module__ == "convert_sdk.ports.storage"
    assert ExperienceResult.__module__ == "convert_sdk.domain.results"
    assert FeatureResult.__module__ == "convert_sdk.domain.results"
    assert FeatureStatus.__module__ == "convert_sdk.domain.results"
    assert GoalNotFoundError.__module__ == "convert_sdk.errors"
    assert InMemoryDataStore.__module__ == "convert_sdk.adapters.storage.in_memory"
    assert LifecycleEvent.__module__ == "convert_sdk.events"
    assert LifecycleEventPayload.__module__ == "convert_sdk.events"
    assert TrackingFlushResult.__module__ == "convert_sdk.domain.results"
    assert TrackingError.__module__ == "convert_sdk.errors"
    assert hasattr(Core, "off")
    assert hasattr(Core, "on")
    assert hasattr(Context, "release_queues")
    assert hasattr(Context, "track_conversion")
    assert hasattr(Context, "update_visitor_attributes")
    assert hasattr(Context, "update_visitor_properties")
    assert hasattr(Context, "run_experience")
    assert hasattr(Context, "run_experiences")
    assert hasattr(Context, "run_feature")
    assert hasattr(Context, "run_features")
    assert __version__ == "0.1.0"


def test_py_typed_marker_is_available() -> None:
    marker = resources.files("convert_sdk").joinpath("py.typed")
    assert marker.is_file()
