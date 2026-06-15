"""Story 2.3 — tracking foundation tests (PL-1).

Auto-delegated foundation that the queue/dedup/flush layers build on:

* ``SDKConfig`` gains ``batch_size`` (JS ``DEFAULT_BATCH_SIZE`` parity for the
  events queue), ``auto_flush_interval_ms`` (opt-in periodic flush; default
  ``None`` = disabled), and an optional ``data_store``.
* ``ports/storage.py`` defines the minimal ``DataStore`` protocol
  (``get``/``set``/``has``) with an in-memory default implementation. Story 3.1
  owns the full persistence boundary; this is the minimal slice dedup needs.
* ``ports/transport.py`` ``Transport`` gains a tracking-POST method
  ``send_tracking(payload, *, sdk_key)`` and the httpx adapter implements it:
  - Posts to the SEPARATE metrics endpoint (NOT the config CDN host).
  - Substitutes ``[project_id]`` in ``TransportConfig.track_base_url`` from the
    payload's ``projectId`` field (JS/PHP parity).
  - Sets ``User-Agent: ConvertAgent/1.0`` so the metrics bot filter recognises
    Convert SDK traffic and does not silently drop events.
"""

import httpx
import pytest

from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
from convert_sdk.config import DEFAULT_TRACK_BASE_URL, SDKConfig, TransportConfig


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_transport_with_mock(captured: dict) -> HttpxTransport:
    """Return an HttpxTransport that captures every request into *captured*."""

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["content"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    return HttpxTransport(TransportConfig(), client=client)


# --- SDKConfig new fields -------------------------------------------------


def test_sdk_config_batch_size_defaults_to_ten():
    # JS DEFAULT_BATCH_SIZE = 10 for the events queue (api-manager.ts).
    cfg = SDKConfig(data={"account_id": "1"})
    assert cfg.batch_size == 10


def test_sdk_config_auto_flush_interval_ms_defaults_to_none():
    cfg = SDKConfig(data={"account_id": "1"})
    assert cfg.auto_flush_interval_ms is None


def test_sdk_config_data_store_defaults_to_none():
    cfg = SDKConfig(data={"account_id": "1"})
    assert cfg.data_store is None


def test_sdk_config_accepts_custom_batch_size_and_interval():
    cfg = SDKConfig(data={"account_id": "1"}, batch_size=3, auto_flush_interval_ms=500)
    assert cfg.batch_size == 3
    assert cfg.auto_flush_interval_ms == 500


def test_sdk_config_rejects_non_positive_batch_size():
    with pytest.raises(Exception):
        SDKConfig(data={"account_id": "1"}, batch_size=0)


# --- TransportConfig track_base_url field ---------------------------------


def test_transport_config_track_base_url_defaults_to_metrics_template():
    cfg = TransportConfig()
    assert cfg.track_base_url == DEFAULT_TRACK_BASE_URL
    assert "[project_id]" in cfg.track_base_url
    assert "metrics.convertexperiments.com" in cfg.track_base_url


def test_transport_config_accepts_custom_track_base_url():
    cfg = TransportConfig(track_base_url="https://custom.metrics.example.com/v1")
    assert cfg.track_base_url == "https://custom.metrics.example.com/v1"


def test_transport_config_rejects_non_https_track_base_url():
    from convert_sdk.errors import TransportError

    with pytest.raises(TransportError):
        TransportConfig(track_base_url="http://insecure.metrics.example.com/v1")


# --- DataStore protocol + in-memory default -------------------------------


def test_in_memory_store_set_get_roundtrip():
    # Story 3.1: the concrete adapter moved to adapters/storage/in_memory.py (L3)
    # and is re-exported from the package root; the L1 ports module exposes only
    # the DataStore protocol now.
    from convert_sdk import InMemoryDataStore

    store = InMemoryDataStore()
    store.set("k", "v")
    assert store.get("k") == "v"


def test_in_memory_store_get_missing_returns_none():
    from convert_sdk import InMemoryDataStore

    store = InMemoryDataStore()
    assert store.get("missing") is None


def test_in_memory_store_has_reflects_membership():
    from convert_sdk import InMemoryDataStore

    store = InMemoryDataStore()
    assert store.has("k") is False
    store.set("k", True)
    assert store.has("k") is True


def test_in_memory_store_satisfies_data_store_protocol():
    from convert_sdk import DataStore, InMemoryDataStore

    store = InMemoryDataStore()
    assert isinstance(store, DataStore)


def test_data_store_protocol_is_runtime_checkable():
    from convert_sdk.ports.storage import DataStore

    class _Fake:
        def get(self, key):  # pragma: no cover - shape only
            return None

        def set(self, key, value, ttl=None):  # pragma: no cover - shape only
            return None

        def has(self, key):  # pragma: no cover - shape only
            return False

        def delete(self, key):  # pragma: no cover - shape only
            return None

    assert isinstance(_Fake(), DataStore)


# --- Transport tracking-POST extension ------------------------------------


def test_transport_protocol_declares_send_tracking():
    from convert_sdk.ports.transport import Transport

    assert hasattr(Transport, "send_tracking")


def test_build_track_url_substitutes_project_id():
    url = HttpxTransport._build_track_url(
        "https://[project_id].metrics.convertexperiments.com/v1", "10034190", "my-key"
    )
    assert url == "https://10034190.metrics.convertexperiments.com/v1/track/my-key"
    assert "[project_id]" not in url


def test_build_track_url_without_placeholder():
    url = HttpxTransport._build_track_url(
        "https://custom.metrics.example.com/v1", "99999", "sdk-key"
    )
    assert url == "https://custom.metrics.example.com/v1/track/sdk-key"


@pytest.mark.parametrize(
    "project_id,sdk_key,expected_host_fragment",
    [
        ("10034190", "10035569/10034190", "10034190.metrics.convertexperiments.com"),
        ("99999", "abc123", "99999.metrics.convertexperiments.com"),
    ],
)
def test_send_tracking_posts_to_metrics_host_not_config_cdn(
    project_id, sdk_key, expected_host_fragment
):
    """Tracking must POST to the metrics endpoint, not the config CDN (bug fix)."""
    captured: dict = {}
    transport = _make_transport_with_mock(captured)
    transport.send_tracking(
        {"projectId": project_id, "accountId": "1", "visitors": []},
        sdk_key=sdk_key,
    )

    url = captured["url"]
    assert expected_host_fragment in url, (
        f"Expected metrics host fragment {expected_host_fragment!r} in URL {url!r}; "
        "tracking must not go to the config CDN"
    )
    assert "cdn" not in url, (
        f"Tracking request must not go to a CDN host; got URL {url!r}"
    )
    assert f"/track/{sdk_key}" in url


def test_send_tracking_sets_convert_agent_user_agent():
    """Every tracking POST must include User-Agent: ConvertAgent/1.0 (bot-filter bypass)."""
    captured: dict = {}
    transport = _make_transport_with_mock(captured)
    transport.send_tracking(
        {"projectId": "10034190", "accountId": "1", "visitors": []},
        sdk_key="my-key",
    )

    ua = captured["headers"].get("user-agent", "")
    assert ua.startswith("ConvertAgent/"), (
        f"Expected User-Agent starting with 'ConvertAgent/' but got {ua!r}; "
        "the metrics endpoint bot filter silently drops requests without this UA"
    )


def test_send_tracking_uses_absolute_url_independent_of_client_base_url():
    """Tracking POST URL must be absolute (metrics host), not relative to client base_url."""
    captured: dict = {}
    transport = _make_transport_with_mock(captured)
    transport.send_tracking(
        {"projectId": "10034190", "accountId": "1", "visitors": []},
        sdk_key="my-key",
    )

    url = captured["url"]
    assert url.startswith("https://"), f"Tracking URL must be absolute HTTPS; got {url!r}"
    assert "metrics.convertexperiments.com" in url


def test_send_tracking_posts_correct_body():
    captured: dict = {}
    transport = _make_transport_with_mock(captured)
    transport.send_tracking(
        {"projectId": "12345", "accountId": "1", "visitors": []},
        sdk_key="my-key",
    )

    assert captured["method"] == "POST"
    assert b"accountId" in captured["content"]


def test_httpx_transport_send_tracking_raises_on_error_status():
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    transport = HttpxTransport(TransportConfig(), client=client)

    from convert_sdk.errors import ConvertSDKError

    with pytest.raises(ConvertSDKError):
        transport.send_tracking(
            {"projectId": "10034190", "visitors": []}, sdk_key="my-key"
        )


def test_httpx_transport_send_tracking_raises_on_403_config_cdn_response():
    """A 403 from posting to the wrong host raises TrackingDeliveryError (regression guard)."""
    def _handler(request: httpx.Request) -> httpx.Response:
        # Simulate what happens if tracking accidentally hits the config CDN
        return httpx.Response(403, text="forbidden")

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    transport = HttpxTransport(TransportConfig(), client=client)

    from convert_sdk.errors import TrackingDeliveryError

    with pytest.raises(TrackingDeliveryError) as exc_info:
        transport.send_tracking(
            {"projectId": "10034190", "visitors": []}, sdk_key="my-key"
        )
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("status_code", [200, 201, 204])
def test_send_tracking_returns_http_status_code_on_success(status_code: int):
    """send_tracking() must return the HTTP status code (int) on success.

    Regression guard: before the fix send_tracking() returned None, causing
    QueueReleasedPayload.status_code to be None on every successful delivery
    and the demo/verify_staging_transaction to falsely warn "non-2xx (None)".
    """
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(_handler))
    transport = HttpxTransport(TransportConfig(), client=client)

    result = transport.send_tracking(
        {"projectId": "10034190", "accountId": "1", "visitors": []},
        sdk_key="my-key",
    )
    assert result == status_code, (
        f"send_tracking() must return the HTTP status code ({status_code}), got {result!r}"
    )
