"""Storage port for the Convert Python SDK (Story 3.1 — full persistence boundary).

Defines the :class:`DataStore` protocol the tracking (and, later, evaluation)
layer depends on for visitor-linked state — deduplication markers and, in future
stories, sticky-bucketing assignments — decoupled from any concrete persistence
backend. Keeping storage behind a ``Protocol`` lets state run per-process with
the in-memory default (:class:`~convert_sdk.adapters.storage.in_memory.InMemoryDataStore`)
and cross-process/cross-worker with a shared adapter (e.g. Redis) **without
protocol changes** — the multi-worker isolation fix (R2) is purely an adapter
swap.

Story 3.1 freezes the MVP required surface to exactly four methods —
``get`` / ``set`` (with optional ``ttl``) / ``has`` / ``delete`` — so a Redis or
``diskcache`` adapter can be implemented without protocol changes. ``get_many``/
``set_many`` are documented as OPTIONAL future batch extensions and are NOT part
of the required surface (see :class:`DataStore`).

Layering: this is an **L1** ``ports/`` interface. It may import stdlib
(``typing``) and L0 (``domain/``, ``errors.py``, ``types.py``) ONLY — never
``adapters/``, ``tracking/``, ``evaluation/``, or ``core.py``. The concrete
:class:`InMemoryDataStore` adapter lives in ``adapters/storage/in_memory.py``
(L3); the composition root ``core.py`` (L4) is the single site allowed to import
it. ``tracking/`` talks to storage ONLY through this protocol (Critical Warning
#3/#4).
"""

from __future__ import annotations

import json
from typing import Any, Optional, Protocol, runtime_checkable

# Namespacing prefix for the per-visitor persisted ``ContextState`` key. Mirrors
# the ``dedup:`` namespacing in ``tracking/deduplication.py`` so the visitor
# state, deduplication markers, and any future DataStore consumer never collide
# in the shared single-per-Core store (Story 3.2).
_VISITOR_STATE_PREFIX = "state"


def visitor_state_key(visitor_id: str) -> str:
    """Build the DataStore key for a visitor's persisted ``ContextState``.

    Uses a collision-safe namespaced key
    ``f"state:{json.dumps([visitor_id])}"`` — JSON serialization guarantees no
    collision regardless of separator characters in ``visitor_id`` and keeps the
    derivation stdlib-only (no new dependency), consistent with
    :func:`convert_sdk.tracking.deduplication.goal_marker_key`. The key encodes
    ONLY this visitor's identity so writes/reads stay strictly visitor-scoped
    (never another visitor's state, never Core-global state).
    """
    return f"{_VISITOR_STATE_PREFIX}:{json.dumps([visitor_id])}"


@runtime_checkable
class DataStore(Protocol):
    """A key/value persistence boundary for visitor-linked SDK state.

    The frozen MVP required surface is exactly four methods: ``get``, ``set``
    (with an optional ``ttl`` in seconds), ``has``, and ``delete``. Any object
    that structurally satisfies these four methods is accepted as a
    ``DataStore`` — ``DataStore`` is ``@runtime_checkable`` so duck-typed
    adapters work without subclassing and ``isinstance(x, DataStore)`` is usable
    for structural validation (matching the JS SDK ``isValidDataStore`` spirit,
    extended for thread-safe server-side use).

    .. note::
        ``@runtime_checkable`` validates only the *presence* of the named
        methods at ``isinstance`` time, not their signatures or return types —
        full contract correctness is proven by the behavioral test suite.

    Implementations MUST be safe to call from the synchronous tracking path and
    from worker threads / the daemonic flush timer (Story 2.3). The default
    in-memory implementation is per-process; a shared adapter makes state
    cross-process without any change to this protocol or to callers.

    Optional future batch extensions ``get_many(keys)`` / ``set_many(items)``
    are named by the architecture for efficiency but are deliberately NOT part
    of the required MVP surface — adapters need only the four methods below.
    """

    def get(self, key: str) -> Any:
        """Return the stored value for ``key``, or ``None`` if absent/expired."""
        ...

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store ``value`` under ``key`` (overwriting any existing value).

        ``ttl`` (seconds) makes the entry expire after that many seconds;
        ``None`` (the default) means no expiry.
        """
        ...

    def has(self, key: str) -> bool:
        """Return ``True`` if ``key`` currently has a present, unexpired value."""
        ...

    def delete(self, key: str) -> None:
        """Remove ``key``. Deleting an absent key is a safe idempotent no-op."""
        ...
