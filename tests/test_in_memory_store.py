"""Story 3.1 — InMemoryDataStore (L3 adapter) + DataStore (L1 port) unit tests.

Proves the frozen four-method ``DataStore`` MVP surface
(``get``/``set``/``has``/``delete`` with optional ``ttl``) for the thread-safe
in-memory adapter, plus the authoritative NFR9 isolation assertion, thread
safety under concurrent access, and NFR19 swappability through ``Core``.

Layering note: the concrete ``InMemoryDataStore`` now lives in
``convert_sdk.adapters.storage.in_memory`` (L3) and is re-exported from the
package root. ``DataStore`` (L1 port) is imported from ``convert_sdk.ports`` /
``convert_sdk``. No core/tracking module imports the concrete class — see
``tests/test_layering.py``.
"""

from __future__ import annotations

import threading
import time

import pytest

from convert_sdk import DataStore, InMemoryDataStore
from convert_sdk.adapters.storage.in_memory import (
    InMemoryDataStore as InMemoryDataStoreDirect,
)
from convert_sdk.ports import DataStore as DataStorePortExport
from convert_sdk.ports.storage import DataStore as DataStoreStorageExport


# --- import surface --------------------------------------------------------


def test_data_store_importable_from_stable_locations():
    # Adapter authors type-annotate against the protocol from the stable public
    # surface; the same object identity is exposed from each export site.
    assert DataStore is DataStorePortExport is DataStoreStorageExport


def test_in_memory_store_importable_from_root_and_adapter():
    assert InMemoryDataStore is InMemoryDataStoreDirect


# --- protocol compliance ---------------------------------------------------


def test_set_get_roundtrip():
    store = InMemoryDataStore()
    store.set("k", "v")
    assert store.get("k") == "v"


def test_get_missing_returns_none():
    store = InMemoryDataStore()
    assert store.get("missing") is None


def test_has_reflects_membership():
    store = InMemoryDataStore()
    assert store.has("k") is False
    store.set("k", True)
    assert store.has("k") is True


def test_delete_removes_key():
    store = InMemoryDataStore()
    store.set("k", "v")
    store.delete("k")
    assert store.has("k") is False
    assert store.get("k") is None


def test_delete_absent_key_is_idempotent_no_op():
    store = InMemoryDataStore()
    # Must not raise on an absent key.
    store.delete("never-set")
    store.delete("never-set")
    assert store.has("never-set") is False


def test_set_overwrites_existing_value():
    store = InMemoryDataStore()
    store.set("k", 1)
    store.set("k", 2)
    assert store.get("k") == 2


def test_stores_falsy_values_distinct_from_absence():
    # None-as-absence must not be confused with a stored falsy value: a key set
    # to a falsy value still reports has() True.
    store = InMemoryDataStore()
    store.set("zero", 0)
    store.set("empty", "")
    store.set("false", False)
    assert store.has("zero") is True
    assert store.get("zero") == 0
    assert store.has("empty") is True
    assert store.get("empty") == ""
    assert store.has("false") is True
    assert store.get("false") is False


# --- lazy ttl expiry (monotonic clock, F-049) ------------------------------


def test_ttl_none_never_expires():
    store = InMemoryDataStore()
    store.set("k", "v", ttl=None)
    assert store.get("k") == "v"
    assert store.has("k") is True


def test_ttl_expired_entry_treated_as_absent_on_get_and_has():
    store = InMemoryDataStore()
    store.set("k", "v", ttl=0)  # already expired (expires_at <= now)
    # tiny sleep guards against monotonic resolution edge on very fast clocks.
    time.sleep(0.001)
    assert store.get("k") is None
    assert store.has("k") is False


def test_ttl_unexpired_entry_is_present():
    store = InMemoryDataStore()
    store.set("k", "v", ttl=60)
    assert store.get("k") == "v"
    assert store.has("k") is True


def test_ttl_uses_monotonic_clock_not_wallclock(monkeypatch):
    # F-049: expiry must compare against time.monotonic(), not time.time().
    # Patch monotonic forward and assert expiry; wall clock changes must be
    # irrelevant.
    from convert_sdk.adapters.storage import in_memory as in_memory_mod

    fake_now = {"t": 1000.0}
    monkeypatch.setattr(in_memory_mod.time, "monotonic", lambda: fake_now["t"])

    store = InMemoryDataStore()
    store.set("k", "v", ttl=10)  # expires at monotonic 1010
    assert store.get("k") == "v"
    fake_now["t"] = 1011.0  # advance monotonic past expiry
    assert store.get("k") is None
    assert store.has("k") is False


# --- NFR9: two instances in one process do not share state -----------------


def test_two_instances_do_not_share_state():
    store_a = InMemoryDataStore()
    store_b = InMemoryDataStore()
    store_a.set("k", "from-a")
    assert store_b.has("k") is False
    assert store_b.get("k") is None
    store_b.set("k", "from-b")
    assert store_a.get("k") == "from-a"
    assert store_b.get("k") == "from-b"


def test_no_class_level_shared_backing_store():
    # The backing dict must be a per-instance attribute, never a class attribute
    # or module global. Two instances must hold distinct dict objects.
    store_a = InMemoryDataStore()
    store_b = InMemoryDataStore()
    backing_a = next(
        v for v in vars(store_a).values() if isinstance(v, dict)
    )
    backing_b = next(
        v for v in vars(store_b).values() if isinstance(v, dict)
    )
    assert backing_a is not backing_b


# --- thread safety ---------------------------------------------------------


def test_concurrent_set_get_delete_is_safe():
    store = InMemoryDataStore()
    errors: list[BaseException] = []
    n_threads = 16
    per_thread = 200

    def worker(tid: int) -> None:
        try:
            for i in range(per_thread):
                key = f"t{tid}:k{i}"
                store.set(key, i)
                _ = store.get(key)
                _ = store.has(key)
                if i % 2 == 0:
                    store.delete(key)
        except BaseException as exc:  # pragma: no cover - failure path
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    # Odd-index keys survive (not deleted); even-index keys were deleted.
    for tid in range(n_threads):
        for i in range(per_thread):
            present = store.has(f"t{tid}:k{i}")
            assert present is (i % 2 == 1)


def test_concurrent_distinct_keys_all_present():
    store = InMemoryDataStore()
    n_threads = 20

    def worker(tid: int) -> None:
        store.set(f"key-{tid}", tid)

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    for tid in range(n_threads):
        assert store.get(f"key-{tid}") == tid


# --- runtime_checkable protocol --------------------------------------------


def test_in_memory_store_is_instance_of_data_store():
    store = InMemoryDataStore()
    assert isinstance(store, DataStore)


def test_duck_typed_four_method_object_satisfies_protocol():
    class _Stub:
        def get(self, key):  # pragma: no cover - shape only
            return None

        def set(self, key, value, ttl=None):  # pragma: no cover - shape only
            return None

        def has(self, key):  # pragma: no cover - shape only
            return False

        def delete(self, key):  # pragma: no cover - shape only
            return None

    assert isinstance(_Stub(), DataStore)


def test_object_missing_delete_does_not_satisfy_protocol():
    # delete is a required MVP method now; an object lacking it is not a
    # structural DataStore under @runtime_checkable.
    class _ThreeMethod:
        def get(self, key):  # pragma: no cover - shape only
            return None

        def set(self, key, value, ttl=None):  # pragma: no cover - shape only
            return None

        def has(self, key):  # pragma: no cover - shape only
            return False

    assert not isinstance(_ThreeMethod(), DataStore)


# --- NFR19: Core uses an injected duck-typed store -------------------------


class _RecordingStore:
    """Minimal duck-typed DataStore that records what Core writes to it."""

    def __init__(self) -> None:
        self._data: dict = {}
        self.set_keys: list[str] = []

    def get(self, key):
        return self._data.get(key)

    def set(self, key, value, ttl=None):
        self._data[key] = value
        self.set_keys.append(key)

    def has(self, key):
        return key in self._data

    def delete(self, key):
        self._data.pop(key, None)


def _minimal_snapshot_config(store):
    from convert_sdk.config import SDKConfig

    return SDKConfig(
        data={
            "account_id": "1",
            "project_id": "1",
            "goals": [{"id": "100", "key": "signup"}],
        },
        data_store=store,
    )


def test_core_uses_injected_data_store_for_dedup_markers():
    from convert_sdk import Core

    stub = _RecordingStore()
    assert isinstance(stub, DataStore)

    core = Core(_minimal_snapshot_config(stub)).initialize()
    ctx = core.create_context("visitor-1")
    ctx.track_conversion("signup")

    # The dedup marker for (visitor-1, goal 100) must land in the injected store,
    # proving Core/Tracker depend on the protocol, not the concrete class.
    assert any(key.startswith("dedup:") for key in stub.set_keys)
    core.close()


def test_core_defaults_to_in_memory_store_when_none():
    from convert_sdk import Core
    from convert_sdk.config import SDKConfig

    config = SDKConfig(
        data={
            "account_id": "1",
            "project_id": "1",
            "goals": [{"id": "100", "key": "signup"}],
        },
    )
    assert config.data_store is None
    core = Core(config).initialize()
    # No exception, fully functional with the in-memory default.
    ctx = core.create_context("visitor-1")
    result = ctx.track_conversion("signup")
    assert result is not None
    core.close()
