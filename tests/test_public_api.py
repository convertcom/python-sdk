from importlib import resources

from convert_sdk import Context, Core, __version__


def test_public_import_boundary_is_stable() -> None:
    assert Core.__module__ == "convert_sdk.core"
    assert Context.__module__ == "convert_sdk.context"
    assert __version__ == "0.1.0"


def test_py_typed_marker_is_available() -> None:
    marker = resources.files("convert_sdk").joinpath("py.typed")
    assert marker.is_file()
