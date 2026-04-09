from importlib import resources

from convert_sdk import (
    Context,
    Core,
    ExperienceResult,
    FeatureResult,
    FeatureStatus,
    SDKConfig,
    TransportConfig,
    __version__,
)


def test_public_import_boundary_is_stable() -> None:
    assert Core.__module__ == "convert_sdk.core"
    assert Context.__module__ == "convert_sdk.context"
    assert SDKConfig.__module__ == "convert_sdk.config"
    assert TransportConfig.__module__ == "convert_sdk.config"
    assert ExperienceResult.__module__ == "convert_sdk.domain.results"
    assert FeatureResult.__module__ == "convert_sdk.domain.results"
    assert FeatureStatus.__module__ == "convert_sdk.domain.results"
    assert hasattr(Context, "run_experience")
    assert hasattr(Context, "run_experiences")
    assert hasattr(Context, "run_feature")
    assert hasattr(Context, "run_features")
    assert __version__ == "0.1.0"


def test_py_typed_marker_is_available() -> None:
    marker = resources.files("convert_sdk").joinpath("py.typed")
    assert marker.is_file()
