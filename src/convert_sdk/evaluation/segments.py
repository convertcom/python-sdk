"""Local custom-segment evaluation for the Convert Python SDK (Story 3.3 / FR15).

This L2 evaluation helper resolves named ``ConfigSegment`` entities from the
immutable loaded :class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot` and
evaluates each segment's rule against a visitor's segment-rule input using the
EXISTING Story 1.4 pure-Python rule engine (:func:`convert_sdk.evaluation.rules.is_rule_matched`).
It is the Python analogue of the JS
``SegmentsManager.selectCustomSegments`` → ``RuleManager.isRuleMatched`` path.

Behavioral parity with JS ``SegmentsManager.setCustomSegments``:

* Segments are resolved by key from the snapshot.
* A single ``segments_matched`` flag latches across the candidate list: once a
  segment's rule matches (or once a rule-less segment is reached, or when no
  ``segment_rule`` is supplied) the matching segments are recorded by id.
* A segment whose id is already recorded (``existing_ids``) is NOT re-added
  (duplicates are skipped).
* A normal no-match records nothing and is not an error.

Layering (L2): this module imports L0 (``domain/``) and the sibling
``evaluation/rules.py`` ONLY. It must NOT import ``tracking/``, ``adapters/``,
``ports/`` concretes, ``context.py``, or ``core.py``. Evaluation is fully LOCAL:
no network I/O, no transport, no config refresh (FR15, no-network rule —
Critical Warning #5).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Mapping, Optional, Sequence

from convert_sdk.evaluation.rules import is_rule_matched

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot


def _resolve_segments(
    snapshot: "ConfigSnapshot",
    segment_keys: Sequence[str],
) -> List[Mapping[str, Any]]:
    """Resolve the named ``ConfigSegment`` entities from the snapshot, in order.

    Resolution iterates the immutable ``snapshot.segments`` locally and matches
    each requested key. Unknown keys are silently skipped (a safe non-match, JS
    ``getEntities`` parity). The snapshot is never mutated; this is read-only
    segment resolution scoped to custom-segment evaluation — not a general
    entity-lookup index (that is Story 3.4).
    """
    by_key = {
        str(segment.get("key")): segment
        for segment in snapshot.segments
        if segment.get("key") is not None
    }
    resolved: List[Mapping[str, Any]] = []
    for key in segment_keys:
        segment = by_key.get(str(key))
        if segment is not None:
            resolved.append(segment)
    return resolved


def select_custom_segments(
    snapshot: "ConfigSnapshot",
    segment_keys: Sequence[str],
    segment_rule: Optional[Mapping[str, Any]],
    *,
    existing_ids: Optional[Sequence[str]] = None,
) -> List[str]:
    """Return the segment IDs newly matched for ``segment_keys`` against ``snapshot``.

    For each resolved segment, the segment's ``rules`` are matched against
    ``segment_rule`` via :func:`is_rule_matched` (the Story 1.4 engine). A
    segment with no ``rules`` matches unconditionally. Once a match is found the
    JS ``segments_matched`` latch stays set, so subsequent rule-less / matched
    segments are also recorded — mirroring ``SegmentsManager.setCustomSegments``.

    Segment IDs already present in ``existing_ids`` are skipped (no duplicates).
    Returns the list of NEWLY matched ids in resolution order; an empty list is
    a normal no-match (never raises). Reads only the immutable snapshot and the
    caller-supplied ``segment_rule`` — no network I/O.
    """
    existing = set(str(i) for i in (existing_ids or []))
    segments = _resolve_segments(snapshot, segment_keys)

    matched_ids: List[str] = []
    matched = False  # JS/PHP `segmentsMatched` latch (segments-manager.ts:100-121)
    for segment in segments:
        rules = segment.get("rules")
        # Evaluate this segment's OWN rule only until the first match latches.
        # A rule-less segment matches unconditionally (preserved Story 3.3 semantics);
        # a rule-bearing segment uses the Story 1.4 engine.
        if segment_rule is not None and not matched:
            matched = True if not rules else is_rule_matched(segment_rule, rules)
        # Once latched (or when no segment_rule is supplied), record subsequent
        # segments WITHOUT re-evaluating their own rules — JS/PHP parity.
        if segment_rule is None or matched:
            raw_id = segment.get("id")
            if raw_id is None:
                continue
            segment_id = str(raw_id)
            if segment_id in existing or segment_id in matched_ids:
                # Duplicate id — skip (JS parity: customSegments.includes -> no re-add).
                continue
            matched_ids.append(segment_id)
    return matched_ids
