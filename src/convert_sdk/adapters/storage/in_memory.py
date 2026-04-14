"""Default in-memory persistence adapter for visitor-linked SDK state."""

from __future__ import annotations

from threading import Lock

from ...domain.context_state import ContextState
from ...ports.storage import DataStore


class InMemoryDataStore(DataStore):
    """Thread-safe process-local visitor state store for MVP behavior."""

    def __init__(self) -> None:
        self._context_states: dict[str, ContextState] = {}
        self._tracked_goals: set[tuple[str, str]] = set()
        self._lock = Lock()

    def load_context_state(self, visitor_id: str) -> ContextState | None:
        with self._lock:
            return self._context_states.get(visitor_id)

    def save_context_state(self, state: ContextState) -> None:
        with self._lock:
            self._context_states[state.visitor_id] = state

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        with self._lock:
            return (visitor_id, goal_id) in self._tracked_goals

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        with self._lock:
            self._tracked_goals.add((visitor_id, goal_id))
