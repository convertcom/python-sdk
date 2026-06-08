"""In-memory ``DataStore`` adapter (Story 3.1, L3).

:class:`InMemoryDataStore` is the default persistence backend the composition
root (``core.py``) wires when no ``data_store`` is configured on
:class:`~convert_sdk.config.SDKConfig`. It is a **dumb, thread-safe key/value
sink** — no business/decision logic (no dedup logic, no bucketing logic, no
payload shaping) lives here (Service Boundaries). All such logic stays in the
tracking/evaluation layers; this adapter only persists state.

Design (frozen by Story 3.1):

* **Per-instance backing store.** Each instance owns its OWN private ``dict``
  and its OWN :class:`threading.Lock` created in ``__init__`` — there is NO
  module global, class attribute, or singleton backing store. Two instances in
  one process therefore do NOT share state (the authoritative NFR9 assertion).
* **Thread safety.** Every read/write is guarded by the per-instance lock so
  concurrent worker threads and the Story 2.3 daemonic flush timer are safe. The
  critical sections are minimal (lock around dict access only) to preserve the
  NFR5 enqueue/dedup budget.
* **Lazy TTL via the monotonic clock (F-049).** ``set(key, value, ttl=<sec>)``
  stores ``(value, expires_at_monotonic)`` where ``expires_at_monotonic =
  time.monotonic() + ttl``; ``ttl=None`` stores ``(value, None)`` (never
  expires). Expiry is evaluated lazily on ``get``/``has`` access — an expired
  entry is treated as absent (and opportunistically purged) — so there is no
  background sweeper. ``time.monotonic()`` is used (NOT ``time.time()``) because
  it is immune to system-clock adjustments (NTP/DST) that would otherwise cause
  premature or missed expiry in long-running server processes.
* **Absence is ``None``.** A missing or expired key yields ``None`` from
  ``get`` and ``False`` from ``has`` — no sentinel strings. A stored falsy value
  (``0``/``""``/``False``) is still a present value (``has`` returns ``True``).

Layering: this is an **L3** adapter. The ONLY module allowed to import it is the
composition root ``core.py`` (L4). No L0/L1/L2 module
(``domain/``/``ports/``/``evaluation/``/``tracking/``/``context.py``) may import
it — they depend on the :class:`~convert_sdk.ports.storage.DataStore` protocol
only (import-linter-enforced; see ``tests/test_layering.py``).

Dependencies: stdlib only (``threading``, ``time``, ``typing``). No SQLite,
Redis, ``diskcache``, or any third-party storage library — durable adapters are
Post-MVP and ``httpx`` remains the SDK's only runtime dependency.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, Optional, Tuple


class InMemoryDataStore:
    """Per-process, per-instance thread-safe in-memory :class:`DataStore`.

    Satisfies the :class:`~convert_sdk.ports.storage.DataStore` protocol
    structurally (no subclassing required). The default when no shared
    ``data_store`` is configured; because state is process-local AND
    instance-local, deduplication/sticky state is isolated per worker — the
    documented R2 multi-worker caveat. Swapping in a shared adapter (same
    protocol) removes that isolation without touching any caller.
    """

    def __init__(self) -> None:
        # Private per-instance backing store: key -> (value, expires_at_monotonic
        # or None). Never a class attribute / module global / singleton (NFR9).
        self._store: Dict[str, Tuple[Any, Optional[float]]] = {}
        # Per-instance lock guarding all access to ``_store``.
        self._lock = threading.Lock()

    def get(self, key: str) -> Any:
        """Return the stored value for ``key``, or ``None`` if absent/expired."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            value, expires_at = entry
            if self._is_expired(expires_at):
                # Opportunistic lazy purge of the expired entry.
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        """Store ``value`` under ``key`` with an optional ``ttl`` (seconds)."""
        expires_at = time.monotonic() + ttl if ttl is not None else None
        with self._lock:
            self._store[key] = (value, expires_at)

    def has(self, key: str) -> bool:
        """Return ``True`` if ``key`` has a present, unexpired value."""
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return False
            _value, expires_at = entry
            if self._is_expired(expires_at):
                del self._store[key]
                return False
            return True

    def delete(self, key: str) -> None:
        """Remove ``key``; deleting an absent key is a safe idempotent no-op."""
        with self._lock:
            self._store.pop(key, None)

    @staticmethod
    def _is_expired(expires_at: Optional[float]) -> bool:
        """Return ``True`` if ``expires_at`` (monotonic) is at/in the past."""
        return expires_at is not None and time.monotonic() >= expires_at
