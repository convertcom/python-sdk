"""Goal deduplication for the Convert Python SDK (Story 2.3).

Implements the goal-deduplication truth table (architecture
#Goal-Deduplication-Truth-Table) exactly, keyed by ``(visitor_id, goal_id)``
within the current :class:`~convert_sdk.ports.storage.DataStore` scope.
Deduplication is by **goal identity**, never by payload content — a differing
``revenue`` / ``conversion_data`` does NOT defeat dedup.

Parity reference — JS ``DataManager.convert()`` (``data-manager.ts:1037-1048``)::

    // Store the data
    this.putData(visitorId, {goals: {[goalId.toString()]: true}});
    // Send conversion event
    if (!goalTriggered) sendConversion.call(this);
    // Send transaction event
    if (goalData && (!goalTriggered || forceMultipleTransactions))
      sendTransaction.call(this);

Two audit-authoritative nuances are encoded here:

* **F-006** — on a repeat under ``force_multiple=True`` the bare conversion
  event is NOT re-sent (it is guarded by ``!goalTriggered``); only the
  transaction (``goalData``) path fires. The first time a goal is seen, the
  conversion is sent (and the transaction too, if ``goalData`` is present).
* **F-007** — the "goal tracked" marker is persisted UNCONDITIONALLY for every
  call that passes the goal-rule check, including ``force_multiple=True``
  (``putData`` runs before the conditional sends). Skipping the marker on a
  forced first call would break dedup for later default-mode calls.

State is read and written ONLY through the ``DataStore`` protocol so a shared
adapter (e.g. Redis) makes dedup cross-process without any protocol or caller
change (Critical Warning #5, R2). No private dict bypasses the boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from convert_sdk.ports.storage import DataStore

# Namespacing prefix for the per-(visitor, goal) marker key. The key shape is an
# internal DataStore detail — callers never construct it directly except via
# :func:`goal_marker_key`. The ``dedup:`` namespace prevents cross-concern key
# collisions with sticky-bucketing or other DataStore consumers.
_MARKER_PREFIX = "dedup"


def goal_marker_key(visitor_id: str, goal_id: str) -> str:
    """Build the DataStore key for the ``(visitor_id, goal_id)`` tracked marker.

    F-050: uses a collision-safe namespaced key
    ``f"dedup:{json.dumps([visitor_id, goal_id])}"``. JSON serialization of a
    two-element list guarantees no collision regardless of separator characters
    in the values — e.g. ``("a:b", "c")`` → ``'dedup:["a:b", "c"]'`` and
    ``("a", "b:c")`` → ``'dedup:["a", "b:c"]'`` are guaranteed distinct, where a
    naive ``f"{visitor_id}:{goal_id}"`` composite would collide. ``json`` is
    stdlib — no new dependency.
    """
    return f"{_MARKER_PREFIX}:{json.dumps([visitor_id, goal_id])}"


@dataclass(frozen=True)
class DedupDecision:
    """The outcome of evaluating dedup for one conversion attempt.

    Attributes:
        suppressed: ``True`` when the attempt is a default-mode duplicate that
            produces no enqueue (``ConversionResult(tracked=False,
            reason="deduplicated")``).
        should_send_conversion: ``True`` when the bare conversion event should be
            enqueued (only the first time a goal is seen — ``!goalTriggered``).
        should_send_transaction: ``True`` when the transaction (``goalData``)
            event should be enqueued (``goalData`` present AND (first time OR
            ``force_multiple``)).
        already_tracked: Whether the goal had already been tracked for the
            visitor before this call (diagnostic).
    """

    suppressed: bool
    should_send_conversion: bool
    should_send_transaction: bool
    already_tracked: bool


def bucketing_marker_key(visitor_id: str, experience_id: str) -> str:
    """Build the DataStore key for the ``(visitor_id, experience_id)`` bucketing marker.

    Uses a collision-safe namespaced key
    ``f"bucketing:{json.dumps([visitor_id, experience_id])}"``. JSON serialization of a
    two-element list guarantees no collision regardless of separator characters in the
    values — e.g. ``("a:b", "c")`` → ``'bucketing:["a:b", "c"]'`` and
    ``("a", "b:c")`` → ``'bucketing:["a", "b:c"]'`` are guaranteed distinct, where a
    naive ``f"{visitor_id}:{experience_id}"`` composite would collide. Parallel to
    :func:`goal_marker_key` but uses the ``bucketing:`` prefix to keep concerns separate.
    """
    return f"bucketing:{json.dumps([visitor_id, experience_id])}"


def evaluate_bucketing_dedup(
    store: DataStore,
    *,
    visitor_id: str,
    experience_id: str,
) -> bool:
    """Check and persist a bucketing deduplication marker for ``(visitor_id, experience_id)``.

    Returns ``True`` (should enqueue) when the marker is absent (first time for this
    visitor+experience pair) and persists the marker via ``store.set(key, True)``.
    Returns ``False`` (suppress) when the marker is already present.

    Bucketing dedup has no ``force_multiple`` / ``goalData`` analog — it is a plain
    "first time?" check scoped to ``(visitor_id, experience_id)``. This satisfies
    Story 2.5 AC#3: client-side dedup ensures each visitor-experience pair produces
    at most one bucketing event per DataStore scope. Note that the JS SDK enqueues
    bucketing events unconditionally and relies on server-side ``enrichData`` — the
    Python SDK honors the story contract with an explicit client-side dedup marker
    instead, consistent with the Python SDK's ``DataStore``-backed dedup approach
    for conversions.
    """
    key = bucketing_marker_key(visitor_id, experience_id)
    if store.has(key):
        return False
    store.set(key, True)
    return True


def evaluate_dedup(
    store: DataStore,
    *,
    visitor_id: str,
    goal_id: str,
    force_multiple: bool = False,
    has_goal_data: bool = False,
) -> DedupDecision:
    """Apply the goal-deduplication truth table and persist the tracked marker.

    Reads the ``(visitor_id, goal_id)`` marker via the ``DataStore`` to learn
    whether the goal was already tracked (``goalTriggered``). Then:

    * If already tracked and NOT ``force_multiple`` → **suppress** (no marker
      write needed; it already exists) and send nothing.
    * Otherwise → persist the marker UNCONDITIONALLY (F-007) and decide sends:
      the conversion event fires only when the goal was not previously tracked
      (``!goalTriggered`` — F-006); the transaction event fires when
      ``has_goal_data`` and (``!goalTriggered`` or ``force_multiple``).

    Returns a :class:`DedupDecision` the tracker uses to enqueue (or not).
    """
    key = goal_marker_key(visitor_id, goal_id)
    goal_triggered = store.has(key)

    if goal_triggered and not force_multiple:
        # Default-mode duplicate — suppress. Marker already present.
        return DedupDecision(
            suppressed=True,
            should_send_conversion=False,
            should_send_transaction=False,
            already_tracked=True,
        )

    # F-007: store the marker unconditionally for every call that gets here
    # (first-time OR forced repeat), mirroring JS putData before the sends.
    store.set(key, True)

    should_send_conversion = not goal_triggered
    should_send_transaction = bool(has_goal_data) and (not goal_triggered or force_multiple)

    return DedupDecision(
        suppressed=False,
        should_send_conversion=should_send_conversion,
        should_send_transaction=should_send_transaction,
        already_tracked=goal_triggered,
    )
