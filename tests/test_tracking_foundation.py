"""Story 2.3 — tracking foundation tests (PL-1).

Auto-delegated foundation that the queue/dedup/flush layers build on:

* ``SDKConfig`` gains ``batch_size`` (JS ``DEFAULT_BATCH_SIZE`` parity for the
  events queue), ``auto_flush_interval_ms`` (opt-in periodic flush; default
  ``None`` = disabled), and an optional ``data_store``.
* ``ports/storage.py`` defines the minimal ``DataStore`` protocol
  (``get``/``set``/``has``) with an in-memory default implementation. Story 3.1
  owns the full persistence boundary; this is the minimal slice dedup needs.
* ``ports/transport.py`` ``Transport`` gains a tracking-POST method
  ``send_tracking(payload, *, sdk_key)`` and the httpx adapter implements it
  (TLS-only NFR8, JS route ``/track/{sdkKey}``, no retry — retries are a
  transport-adapter concern out of scope for this story).
"""

import pytest

from convert_sdk.config import SDKConfig, TransportConfig


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


def test_httpx_transport_send_tracking_posts_to_track_route(monkeypatch):
    import httpx

    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport

    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["url"] = str(request.url)
        captured["content"] = request.content
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(
        base_url="https://track.example.com",
        transport=httpx.MockTransport(_handler),
    )
    transport = HttpxTransport(
        TransportConfig(base_url="https://track.example.com"), client=client
    )
    transport.send_tracking({"accountId": "1", "visitors": []}, sdk_key="my-key")

    assert captured["method"] == "POST"
    assert "/track/my-key" in captured["url"]
    assert b"accountId" in captured["content"]


def test_httpx_transport_send_tracking_raises_on_error_status():
    import httpx

    from convert_sdk.adapters.transport.httpx_transport import HttpxTransport
    from convert_sdk.errors import ConvertSDKError

    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, text="bad gateway")

    client = httpx.Client(
        base_url="https://track.example.com",
        transport=httpx.MockTransport(_handler),
    )
    transport = HttpxTransport(
        TransportConfig(base_url="https://track.example.com"), client=client
    )
    with pytest.raises(ConvertSDKError):
        transport.send_tracking({"visitors": []}, sdk_key="my-key")
