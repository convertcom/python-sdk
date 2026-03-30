from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from convertcom_sdk.enums import SystemEvents
from convertcom_sdk.utils.object_utils import object_deep_merge

DEFAULT_BATCH_SIZE = 1
DEFAULT_RELEASE_INTERVAL = 5000


class DataStoreManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        data_store: Any = None,
        event_manager: Any | None = None,
        logger_manager: Any | None = None,
    ) -> None:
        config = dict(config or {})
        events = config.get("events") or {}
        self._lock = threading.RLock()
        self._event_manager = event_manager
        self._logger_manager = logger_manager
        self._mapper = config.get("mapper") or (lambda value: value)
        self.batch_size = int(events.get("batch_size") or DEFAULT_BATCH_SIZE)
        self.release_interval = int(
            events.get("release_interval") or DEFAULT_RELEASE_INTERVAL
        )
        self._requests_queue: dict[str, Any] = {}
        self._requests_queue_timer: threading.Timer | None = None
        self.data_store = data_store if self.is_valid_data_store(data_store) else None

    def set(self, key: str, data: Any) -> None:
        if self.data_store is None:
            return
        try:
            self.data_store.set(key, data)
        except Exception as error:
            if self._logger_manager:
                self._logger_manager.error(
                    "DataStoreManager.set()",
                    {"error": str(error)},
                )

    def get(self, key: str) -> Any:
        if self.data_store is None:
            return None
        try:
            return self.data_store.get(key)
        except Exception as error:
            if self._logger_manager:
                self._logger_manager.error(
                    "DataStoreManager.get()",
                    {"error": str(error)},
                )
            return None

    def enqueue(self, key: str, data: Any) -> None:
        if self._logger_manager:
            self._logger_manager.trace(
                "DataStoreManager.enqueue()",
                self._mapper({"key": key, "data": data}),
            )
        with self._lock:
            self._requests_queue = object_deep_merge(
                self._requests_queue,
                {key: data},
            )
            queue_length = len(self._requests_queue)
        if queue_length >= self.batch_size:
            self.release_queue("size")
        elif queue_length == 1:
            self.start_queue()

    def release_queue(self, reason: str | None = None) -> None:
        if self._logger_manager:
            self._logger_manager.info(
                "DataStoreManager.release_queue()",
                {"reason": reason or ""},
            )
        with self._lock:
            queued_items = dict(self._requests_queue)
            self._requests_queue = {}
        self.stop_queue()
        for key, value in queued_items.items():
            self.set(key, value)
        if self._event_manager:
            self._event_manager.fire(
                SystemEvents.DATA_STORE_QUEUE_RELEASED,
                {"reason": reason or ""},
            )

    def releaseQueue(self, reason: str | None = None) -> None:
        self.release_queue(reason)

    def stop_queue(self) -> None:
        with self._lock:
            timer = self._requests_queue_timer
            self._requests_queue_timer = None
        if timer:
            timer.cancel()

    def start_queue(self) -> None:
        self.stop_queue()
        with self._lock:
            timer = threading.Timer(
                self.release_interval / 1000.0,
                lambda: self.release_queue("timeout"),
            )
            timer.daemon = True
            self._requests_queue_timer = timer
            timer.start()

    def close(self) -> None:
        self.stop_queue()

    def is_valid_data_store(self, data_store: Any) -> bool:
        return bool(
            data_store
            and hasattr(data_store, "get")
            and callable(data_store.get)
            and hasattr(data_store, "set")
            and callable(data_store.set)
        )
