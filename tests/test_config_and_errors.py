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


def test_sdkconfig_logger_defaults_to_none():
    """Story 4.1: SDKConfig exposes an additive optional ``logger`` hook.

    The default is ``None`` — the logging layer then resolves the package
    ``convert_sdk`` namespace logger. Adding the field must not change any
    existing construction behavior (Critical Warning #6 — additive only)."""
    from convert_sdk import SDKConfig

    cfg = SDKConfig(sdk_key="k")
    assert cfg.logger is None


def test_sdkconfig_accepts_caller_supplied_logger():
    import logging

    from convert_sdk import SDKConfig

    custom = logging.getLogger("my.app.convert")
    cfg = SDKConfig(sdk_key="k", logger=custom)
    assert cfg.logger is custom


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


def test_config_load_error_redacts_query_and_sdk_key():
    """qs-08 NFR23 shim: ConfigLoadError messages strip the query string and
    mask the /config/{sdkKey} key segment — no full key, no secret query
    params ever appear."""
    from convert_sdk import ConfigLoadError

    err = ConfigLoadError(
        "config fetch failed",
        endpoint="https://cdn.example.com/config/sdk_key_abcdef1234567890?environment=prod&token=secret",
        status_code=503,
    )
    msg = str(err)
    assert "token=secret" not in msg
    assert "environment=prod" not in msg
    assert "?" not in msg
    assert "sdk_key_abcdef1234567890" not in msg  # full key masked
    assert "***" in msg
    assert "status=503" in msg
    assert "cdn.example.com/config/" in msg


def test_config_load_error_masks_short_key_fully():
    from convert_sdk import ConfigLoadError

    err = ConfigLoadError("x", endpoint="https://h/config/short")
    msg = str(err)
    assert "short" not in msg
    assert "/config/***" in msg


def test_config_load_error_uses_centralized_redaction_primitive():
    """Story 4.1 Task 3 regression: errors.py repoints onto the SINGLE
    ``_internal/redaction.py`` primitive (no second masking implementation),
    and the redacted rendering is equal-or-stricter than the Story 1.2 shim —
    the public contract (message + ``endpoint``/``status_code`` attrs) is
    unchanged (the full ``SafeContext`` enrichment is Story 4.2)."""
    from convert_sdk import ConfigLoadError
    from convert_sdk._internal.redaction import redact_url

    raw = "https://cdn.example.com/config/sdk_key_abcdef1234567890?token=secret"
    err = ConfigLoadError("config fetch failed", endpoint=raw, status_code=503)

    # The stored endpoint is exactly what the centralized primitive produces.
    assert err.endpoint == redact_url(raw)
    assert err.status_code == 503

    msg = str(err)
    assert "token=secret" not in msg
    assert "?" not in msg
    assert "sdk_key_abcdef1234567890" not in msg
    assert "cdn.example.com/config/" in msg
    assert "status=503" in msg


def test_tracking_delivery_error_uses_centralized_redaction_primitive():
    """The TrackingDeliveryError redaction is likewise repointed; public
    contract (message + endpoint/status_code) unchanged."""
    from convert_sdk import TrackingDeliveryError
    from convert_sdk._internal.redaction import redact_url

    raw = "https://cdn.example.com/track/sdk_key_abcdef1234567890?b=2"
    err = TrackingDeliveryError("delivery failed", endpoint=raw, status_code=502)
    assert err.endpoint == redact_url(raw)
    assert err.status_code == 502
    assert "sdk_key_abcdef1234567890" not in str(err)
    assert "?" not in str(err)


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
