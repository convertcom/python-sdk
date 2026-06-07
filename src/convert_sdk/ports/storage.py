"""Storage port for the Convert Python SDK (Story 2.3 minimal slice).

Defines the :class:`DataStore` protocol the tracking layer depends on for
deduplication state, decoupled from any concrete persistence backend. Keeping
storage behind a ``Protocol`` lets dedup run per-process with the in-memory
default (:class:`InMemoryDataStore`) and cross-process/cross-worker with a
shared adapter (e.g. Redis) **without protocol changes** — the multi-worker
dedup fix (R2) is purely an adapter swap.

Scope (Story 2.3): only the minimal ``get``/``set``/``has`` surface that
deduplication needs. Story 3.1 owns the full persistence boundary (TTL,
``delete``, richer adapters) and may extend this protocol additively without
breaking the tracking layer.

Layering: this is an L1 ``ports/`` interface. ``tracking/`` talks to storage
ONLY through this protocol — never through a concrete adapter or a private dict
that bypasses the boundary (Critical Warning #5).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class DataStore(Protocol):
    """A minimal key/value store the tracking layer uses for dedup state.

    Implementations must be safe to call from the synchronous tracking path.
    The default in-memory implementation is per-process; a shared adapter makes
    state cross-process without any change to this protocol or to callers.
    """

    def get(self, key: str) -> Any:
        """Return the stored value for ``key``, or ``None`` if absent."""
        ...

    def set(self, key: str, value: Any) -> None:
        """Store ``value`` under ``key`` (overwriting any existing value)."""
        ...

    def has(self, key: str) -> bool:
        """Return ``True`` if ``key`` currently has a stored value."""
        ...


class InMemoryDataStore:
    """Per-process in-memory :class:`DataStore` (Story 2.3 default).

    The default when no shared ``data_store`` is configured. Because it is
    per-process, deduplication is isolated per worker — the documented R2
    multi-worker caveat. Swapping in a shared adapter (same protocol) removes
    that isolation without touching the tracking layer.

    Story 3.1 may replace or extend this with TTL/eviction; the tracking layer
    only relies on the ``get``/``set``/``has`` contract.
    """

    def __init__(self) -> None:
        self._data: Dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self._data.get(key)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def has(self, key: str) -> bool:
        return key in self._data


def resolve_data_store(configured: Optional[Any]) -> DataStore:
    """Return the configured :class:`DataStore`, or a fresh in-memory default.

    Centralizes the "no shared store -> per-process in-memory" decision so every
    tracking caller selects the dedup backend the same way.
    """
    if configured is not None:
        return configured
    return InMemoryDataStore()
