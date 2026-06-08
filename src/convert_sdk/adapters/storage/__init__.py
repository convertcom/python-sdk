"""Storage adapters (L3) for the Convert Python SDK.

Concrete persistence backends satisfying the
:class:`~convert_sdk.ports.storage.DataStore` protocol. Story 3.1 ships the
stdlib-only :class:`~convert_sdk.adapters.storage.in_memory.InMemoryDataStore`
default; durable adapters (SQLite/Redis/``diskcache``) are explicitly Post-MVP.
"""

from convert_sdk.adapters.storage.in_memory import InMemoryDataStore

__all__ = ["InMemoryDataStore"]
