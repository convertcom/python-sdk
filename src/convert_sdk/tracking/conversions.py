"""Conversion event creation from a visitor context (Story 2.1).

:func:`create_conversion` is the first tracking-domain operation: it resolves a
goal by key from the current immutable :class:`ConfigSnapshot` and builds an
in-process :class:`ConversionEvent` associated with the visitor and the resolved
goal identity. It returns a typed :class:`ConversionResult` for **both**
outcomes — a successful enqueue (``QUEUED``) and an unknown goal key
(``GOAL_NOT_FOUND``).

Audit-corrected behavior (F-052 / FR50): an unknown goal key is a *diagnosable
NON-EXCEPTION* outcome, not programmer misuse. The miss is distinguishable from
success purely via :attr:`ConversionResult.status` so callers never need
``try``/``except`` to tell them apart.

Story 2.1 guardrails honored here:

* Goal resolution goes through the snapshot's precomputed index
  (:meth:`ConfigSnapshot.get_goal_by_key`) — never an ad-hoc raw-config scan
  (Critical Warning #4).
* No raw outbound payload assembly (Story 2.2 owns ``tracking/payloads.py``).
* No network I/O, batching, deduplication, or flush (later Epic 2 stories).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from convert_sdk.domain.results import (
    ConversionEvent,
    ConversionResult,
    ConversionStatus,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


def create_conversion(
    snapshot: "ConfigSnapshot",
    *,
    visitor_id: str,
    goal_key: str,
) -> ConversionResult:
    """Create an in-process conversion event for ``goal_key`` and ``visitor_id``.

    Resolves the goal from the immutable ``snapshot``. On a hit, builds a
    :class:`ConversionEvent` carrying the visitor and the stable goal identity
    (id + key) and returns a ``QUEUED`` :class:`ConversionResult`. On a miss,
    returns a ``GOAL_NOT_FOUND`` result with no event (FR50) — never raises.

    The result is diagnosable without leaking config secrets or unrelated
    visitor data: only the requested ``goal_key`` and the visitor's own id are
    echoed back.
    """
    goal = snapshot.get_goal_by_key(goal_key)
    if goal is None:
        # FR50: typed, diagnosable, NON-EXCEPTION miss — distinguishable from
        # a successful enqueue purely by status.
        return ConversionResult(
            status=ConversionStatus.GOAL_NOT_FOUND,
            goal_key=goal_key,
            goal_id=None,
            visitor_id=visitor_id,
            event=None,
        )

    goal_id = str(goal.get("id"))
    event = ConversionEvent(
        visitor_id=visitor_id,
        goal_id=goal_id,
        goal_key=goal_key,
    )
    return ConversionResult(
        status=ConversionStatus.QUEUED,
        goal_key=goal_key,
        goal_id=goal_id,
        visitor_id=visitor_id,
        event=event,
    )
