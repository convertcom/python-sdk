"""Story 1.2 — config & error model tests (SDK-1).

Covers the public initialization config types (``SDKConfig``,
``TransportConfig``) and the typed initialization/config error hierarchy, plus
the extended public import boundary. These are unit-level tests that must not
touch the network.

AC #3 (typed diagnosable failures) and AC #4 (NFR8 TLS-only transport — a
non-HTTPS base URL must raise a typed error before any network I/O) are
anchored here at the config-validation layer.
"""

import pytest


def test_config_and_error_symbols_importable():
    """Story 1.2 extends the public surface with config + error types while
    preserving the frozen Story 1.1 boundary."""
    from convert_sdk import (  # noqa: F401
        Context,
        Core,
        SDKConfig,
        TransportConfig,
        ConvertSDKError,
        ConfigError,
        InvalidConfigError,
        ConfigLoadError,
        TransportError,
        __version__,
    )

    assert Core is not None
    assert Context is not None
    assert isinstance(__version__, str)


def test_story_1_1_boundary_preserved():
    """The frozen Story 1.1 trio must still import unchanged."""
    from convert_sdk import Context, Core, __version__  # noqa: F401

    assert __version__ == "0.1.0"


def test_sdkconfig_accepts_sdk_key():
    from convert_sdk import SDKConfig

    cfg = SDKConfig(sdk_key="sdk_key_abcdef1234567890")
    assert cfg.sdk_key == "sdk_key_abcdef1234567890"
    assert cfg.data is None


def test_sdkconfig_accepts_direct_data():
    from convert_sdk import SDKConfig

    cfg = SDKConfig(data={"account_id": "1", "project": {"id": "2"}})
    assert cfg.data == {"account_id": "1", "project": {"id": "2"}}
    assert cfg.sdk_key is None


def test_sdkconfig_requires_one_of_sdk_key_or_data():
    """Neither sdk_key nor data provided is a typed config error."""
    from convert_sdk import InvalidConfigError, SDKConfig

    with pytest.raises(InvalidConfigError):
        SDKConfig()


def test_sdkconfig_rejects_both_sdk_key_and_data():
    """Providing both initialization modes at once is ambiguous → typed error."""
    from convert_sdk import InvalidConfigError, SDKConfig

    with pytest.raises(InvalidConfigError):
        SDKConfig(sdk_key="k", data={"account_id": "1"})


def test_sdkconfig_supports_environment_and_cache_level():
    from convert_sdk import SDKConfig

    cfg = SDKConfig(sdk_key="k", environment="staging", cache_level="low")
    assert cfg.environment == "staging"
    assert cfg.cache_level == "low"


def test_transportconfig_defaults_to_https_endpoint():
    from convert_sdk import TransportConfig

    tc = TransportConfig()
    assert tc.base_url.startswith("https://")


def test_transportconfig_accepts_https_base_url():
    from convert_sdk import TransportConfig

    tc = TransportConfig(base_url="https://cdn-4.convertexperiments.com")
    assert tc.base_url == "https://cdn-4.convertexperiments.com"


def test_transportconfig_rejects_non_https_base_url():
    """AC #4 / NFR8: non-HTTPS base URL raises a typed error at config time —
    before any transport/network I/O can occur."""
    from convert_sdk import TransportError, TransportConfig

    with pytest.raises(TransportError):
        TransportConfig(base_url="http://insecure.example.com")


def test_error_hierarchy_is_typed_and_distinct():
    """Initialization errors must be a distinct, catchable typed hierarchy so
    they are distinguishable from normal (future) evaluation no-result paths."""
    from convert_sdk import (
        ConvertSDKError,
        ConfigError,
        InvalidConfigError,
        ConfigLoadError,
        TransportError,
    )

    # All SDK errors share a common root.
    for exc in (ConfigError, InvalidConfigError, ConfigLoadError, TransportError):
        assert issubclass(exc, ConvertSDKError)

    # Config-shape errors live under ConfigError.
    assert issubclass(InvalidConfigError, ConfigError)
    assert issubclass(ConfigLoadError, ConfigError)

    # The root is a real Exception subclass.
    assert issubclass(ConvertSDKError, Exception)
