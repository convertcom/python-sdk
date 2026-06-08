"""Story 1.2 — httpx transport adapter tests (SDK-3).

Covers the transport port + httpx adapter:

* The adapter conforms to the transport :class:`Transport` protocol.
* It fetches ``GET /api/v1/config/{sdkKey}`` over HTTPS using a long-lived client.
  The ``/api/v1`` prefix is the real Convert config-serving CDN path, confirmed
  by live endpoint testing and the PHP SDK generated client (ProjectConfigApi).
* It honors the conditional query shape: ``environment={environment}`` present
  only when configured, ``_conv_low_cache=1`` present only when cache is low.
* Optional bearer auth is injected as an ``Authorization`` header.
* A non-HTTPS base URL raises :class:`TransportError` before any network I/O
  (AC #4 / NFR8).
* Transport/HTTP failures raise typed :class:`ConfigLoadError` with a redacted
  endpoint and status code (NFR23 / qs-08 shim).

All HTTP is mocked at the route level with RESPX — no real network, no
socket-level patching (qs-06 pattern).
"""

import httpx
import pytest
import respx

from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import SDKConfig, TransportConfig
from convert_sdk.errors import ConfigLoadError, TransportError
from convert_sdk.ports.transport import Transport


CONFIG_BODY = {"account_id": "100123", "project": {"id": "200456"}, "experiences": []}


def test_adapter_satisfies_transport_protocol():
    transport = HttpxTransport(TransportConfig())
    assert isinstance(transport, Transport)
    transport.close()


def test_non_https_base_url_raises_before_network():
    """AC #4 / NFR8 — the typed error is raised at config construction, so the
    adapter can never even be built with an insecure URL."""
    with pytest.raises(TransportError):
        TransportConfig(base_url="http://insecure.example.com")


@respx.mock
def test_fetch_config_uses_api_v1_config_route_over_https():
    """The emitted route is /api/v1/config/{sdkKey} — confirmed by live CDN test
    and the PHP SDK generated client (ProjectConfigApi, server base
    ``https://cdn-4.convertexperiments.com/api/v1``, resource path
    ``/config/{sdkKey}``)."""
    route = respx.get(
        "https://cdn-4.convertexperiments.com/api/v1/config/sdkkey123"
    ).mock(return_value=httpx.Response(200, json=CONFIG_BODY))

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    body = transport.fetch_config(cfg)
    transport.close()

    assert route.called
    called = route.calls.last.request
    assert called.url.scheme == "https"
    assert called.url.path == "/api/v1/config/sdkkey123"
    assert body == CONFIG_BODY


@respx.mock
def test_environment_query_present_when_configured():
    respx.get(url__regex=r"https://cdn-4\.convertexperiments\.com/api/v1/config/sdkkey123.*").mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123", environment="staging")
    transport.fetch_config(cfg)
    request = respx.calls.last.request
    transport.close()

    assert request.url.path == "/api/v1/config/sdkkey123"
    assert request.url.params.get("environment") == "staging"
    assert "_conv_low_cache" not in request.url.params


@respx.mock
def test_environment_query_absent_by_default():
    respx.get(url__regex=r"https://cdn-4\.convertexperiments\.com/api/v1/config/sdkkey123.*").mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    transport.fetch_config(cfg)
    request = respx.calls.last.request
    transport.close()

    assert "environment" not in request.url.params
    assert "_conv_low_cache" not in request.url.params


@respx.mock
def test_low_cache_query_present_when_cache_level_low():
    respx.get(url__regex=r"https://cdn-4\.convertexperiments\.com/api/v1/config/sdkkey123.*").mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123", cache_level="low")
    transport.fetch_config(cfg)
    request = respx.calls.last.request
    transport.close()

    assert request.url.params.get("_conv_low_cache") == "1"
    assert "environment" not in request.url.params


@respx.mock
def test_both_environment_and_low_cache_present():
    respx.get(url__regex=r"https://cdn-4\.convertexperiments\.com/api/v1/config/sdkkey123.*").mock(
        return_value=httpx.Response(200, json=CONFIG_BODY)
    )

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123", environment="prod", cache_level="low")
    transport.fetch_config(cfg)
    request = respx.calls.last.request
    transport.close()

    assert request.url.params.get("environment") == "prod"
    assert request.url.params.get("_conv_low_cache") == "1"


@respx.mock
def test_bearer_auth_header_injected_when_secret_present():
    respx.get(
        "https://cdn-4.convertexperiments.com/api/v1/config/sdkkey123"
    ).mock(return_value=httpx.Response(200, json=CONFIG_BODY))

    transport = HttpxTransport(TransportConfig(auth_secret="s3cr3t"))
    cfg = SDKConfig(sdk_key="sdkkey123")
    transport.fetch_config(cfg)
    request = respx.calls.last.request
    transport.close()

    assert request.headers.get("authorization") == "Bearer s3cr3t"


@respx.mock
def test_http_5xx_raises_config_load_error_with_redacted_endpoint():
    respx.get(
        "https://cdn-4.convertexperiments.com/api/v1/config/sdkkey123"
    ).mock(return_value=httpx.Response(503, text="unavailable"))

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    with pytest.raises(ConfigLoadError) as exc_info:
        transport.fetch_config(cfg)
    transport.close()

    err = exc_info.value
    assert err.status_code == 503
    # Redacted endpoint: host + path, no query string, and the SDK key masked
    # (qs-08 NFR23 — full keys never appear in error messages).
    assert "?" not in str(err)
    assert "cdn-4.convertexperiments.com/api/v1/config/" in str(err)
    assert "sdkkey123" not in str(err)  # full key must not leak
    assert "***" in str(err)  # masked form present


@respx.mock
def test_connection_error_raises_config_load_error():
    respx.get(
        "https://cdn-4.convertexperiments.com/api/v1/config/sdkkey123"
    ).mock(side_effect=httpx.ConnectError("boom"))

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    with pytest.raises(ConfigLoadError):
        transport.fetch_config(cfg)
    transport.close()


@respx.mock
def test_malformed_json_body_raises_config_load_error():
    respx.get(
        "https://cdn-4.convertexperiments.com/api/v1/config/sdkkey123"
    ).mock(return_value=httpx.Response(200, text="not json{{"))

    transport = HttpxTransport(TransportConfig())
    cfg = SDKConfig(sdk_key="sdkkey123")
    with pytest.raises(ConfigLoadError):
        transport.fetch_config(cfg)
    transport.close()


def test_transport_is_context_manager():
    with HttpxTransport(TransportConfig()) as transport:
        assert isinstance(transport, Transport)


# --- _build_route regression tests (bugfix: /api/v1 prefix) -------------------


def test_build_route_emits_api_v1_prefix():
    """Regression: route must be /api/v1/config/{key}, not /config/{key}.

    The real Convert config-serving CDN returns 404 for /config/{key} and 200
    for /api/v1/config/{key} (confirmed by live staging test). The PHP SDK
    generated client (ProjectConfigApi) uses server base
    ``https://cdn-4.convertexperiments.com/api/v1`` + resource path
    ``/config/{sdkKey}``, yielding the same full path.
    """
    cfg = SDKConfig(sdk_key="my-sdk-key")
    route = HttpxTransport._build_route(cfg)
    assert route == "/api/v1/config/my-sdk-key"


def test_build_route_with_environment_query():
    cfg = SDKConfig(sdk_key="my-sdk-key", environment="staging")
    route = HttpxTransport._build_route(cfg)
    assert route == "/api/v1/config/my-sdk-key?environment=staging"


def test_build_route_with_low_cache_query():
    cfg = SDKConfig(sdk_key="my-sdk-key", cache_level="low")
    route = HttpxTransport._build_route(cfg)
    assert route == "/api/v1/config/my-sdk-key?_conv_low_cache=1"


def test_build_route_with_both_query_params():
    cfg = SDKConfig(sdk_key="my-sdk-key", environment="prod", cache_level="low")
    route = HttpxTransport._build_route(cfg)
    assert route == "/api/v1/config/my-sdk-key?environment=prod&_conv_low_cache=1"


@respx.mock
def test_fetch_config_staging_host_uses_correct_route():
    """A user-supplied staging base_url (pure host) must hit /api/v1/config/{key}.

    Regression: before the fix, supplying the staging CDN host returned 404
    because the route was /config/{key}. Now it must use /api/v1/config/{key}
    regardless of which CDN host is configured.
    """
    staging_base = "https://cdn-4-staging.convertexperiments.com"
    route = respx.get(
        f"{staging_base}/api/v1/config/stg-key"
    ).mock(return_value=httpx.Response(200, json=CONFIG_BODY))

    transport = HttpxTransport(TransportConfig(base_url=staging_base))
    cfg = SDKConfig(sdk_key="stg-key", transport=TransportConfig(base_url=staging_base))
    body = transport.fetch_config(cfg)
    transport.close()

    assert route.called
    called = route.calls.last.request
    assert called.url.path == "/api/v1/config/stg-key"
    assert body == CONFIG_BODY
