"""Protocol definitions for visitor-linked SDK state persistence."""

from __future__ import annotations

from typing import Protocol

from ..domain.context_state import ContextState


class DataStore(Protocol):
    """Persistence boundary for visitor-linked SDK state."""

    def load_context_state(self, visitor_id: str) -> ContextState | None:
        """Return stored state for a visitor, if available."""

        ...

    def save_context_state(self, state: ContextState) -> None:
        """Persist the latest visitor-scoped state."""

        ...

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        """Return whether a visitor/goal conversion has already been recorded."""

        ...

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        """Persist a visitor/goal conversion as tracked for deduplication."""

        ...
