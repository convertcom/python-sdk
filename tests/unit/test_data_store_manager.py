from __future__ import annotations

import threading

from convertcom_sdk import DataStoreManager, EventManager, SystemEvents


class FakeDataStore:
    def __init__(self) -> None:
        self.data = {}
        self.set_calls = []

    def get(self, key):
        return self.data.get(key)

    def set(self, key, value):
        self.data[key] = value
        self.set_calls.append((key, value))


def test_data_store_manager_releases_on_batch_size():
    store = FakeDataStore()
    event_manager = EventManager()
    released = []
    event_manager.on(
        SystemEvents.DATA_STORE_QUEUE_RELEASED,
        lambda args, err: released.append((args, err)),
    )
    manager = DataStoreManager(
        {"events": {"batch_size": 2, "release_interval": 1000}},
        data_store=store,
        event_manager=event_manager,
    )

    manager.enqueue("visitor-1", {"bucketing": {"exp-1": "var-1"}})
    manager.enqueue("visitor-2", {"bucketing": {"exp-2": "var-2"}})

    assert store.data == {
        "visitor-1": {"bucketing": {"exp-1": "var-1"}},
        "visitor-2": {"bucketing": {"exp-2": "var-2"}},
    }
    assert released == [({"reason": "size"}, None)]


def test_data_store_manager_merges_queued_values_by_key():
    store = FakeDataStore()
    manager = DataStoreManager(
        {"events": {"batch_size": 10, "release_interval": 1000}},
        data_store=store,
    )

    manager.enqueue("visitor-1", {"segments": {"country": "US"}})
    manager.enqueue("visitor-1", {"bucketing": {"exp-1": "var-1"}})
    manager.release_queue("manual")

    assert store.data["visitor-1"] == {
        "segments": {"country": "US"},
        "bucketing": {"exp-1": "var-1"},
    }


def test_data_store_manager_releases_on_timeout():
    store = FakeDataStore()
    event_manager = EventManager()
    released = []
    event = threading.Event()
    event_manager.on(
        SystemEvents.DATA_STORE_QUEUE_RELEASED,
        lambda args, err: (released.append((args, err)), event.set()),
    )
    manager = DataStoreManager(
        {"events": {"batch_size": 10, "release_interval": 50}},
        data_store=store,
        event_manager=event_manager,
    )

    manager.enqueue("visitor-1", {"segments": {"country": "US"}})

    assert event.wait(1)
    manager.close()
    assert released == [({"reason": "timeout"}, None)]
    assert store.data["visitor-1"] == {"segments": {"country": "US"}}
