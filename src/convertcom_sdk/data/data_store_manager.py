from __future__ import annotations

from collections.abc import Mapping
from typing import Any


class DataStoreManager:
    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        data_store: Any = None,
    ) -> None:
        del config
        self.data_store = data_store if self.is_valid_data_store(data_store) else None

    def set(self, key: str, data: Any) -> None:
        if self.data_store is not None:
            self.data_store.set(key, data)

    def get(self, key: str) -> Any:
        if self.data_store is None:
            return None
        return self.data_store.get(key)

    def is_valid_data_store(self, data_store: Any) -> bool:
        return bool(
            data_store
            and hasattr(data_store, "get")
            and callable(data_store.get)
            and hasattr(data_store, "set")
            and callable(data_store.set)
        )

    def release_queue(self, reason: str | None = None) -> None:
        del reason
