"""Read-only config entity lookup for the Convert Python SDK (Story 3.4 / FR28).

This L2 evaluation helper resolves typed config entities from the immutable,
already-loaded :class:`~convert_sdk.domain.config_snapshot.ConfigSnapshot` by
key or by id, plus a multi-key convenience accessor. It is the Python analogue
of the JS ``DataManager.getEntity`` / ``getEntities`` / ``getEntityById`` path
(``_getEntityByField`` resolving the entity list by the ``key`` / ``id`` identity
field and returning ``null`` on no match) — but resolves via the snapshot's
precomputed by-key / by-id index in ``O(1)`` rather than scanning the list.

Behavioral contract:

* A HIT returns the snapshot's own indexed entity object — the normalized
  internal (snake_case) domain entity, NOT a raw camelCase transport dict and
  NOT a freshly built copy.
* A MISS returns the Story-3.4 no-result: ``None`` for single lookups, an empty
  ``list`` for multi-key. An unknown key/id, a known identity under the WRONG
  ``entity_type``, and an unknown/unsupported ``entity_type`` all collapse to the
  SAME no-result — never a raised exception on a normal miss, never a sentinel
  string.
* The single-entity no-result is produced at ONE localized decision point
  (:func:`_no_result`) so Story 4.2 can swap ``None`` → the FR50 typed-reason
  result object WITHOUT changing the hit return or breaking Story 3.4 callers.

The lookup is fully LOCAL and READ-ONLY: it reads only the loaded snapshot index
and performs NO network I/O and NO mutation of the snapshot, its indexes, or any
nested config structure (FR28 advanced/debugging access is a read over
already-loaded config).

Layering (L2): this module imports L0 (``domain/``) types for typing only. It
must NOT import ``tracking/``, ``adapters/``, ``context.py``, or ``core.py``
(architecture Forbidden-imports; enforced by ``tests/test_layering.py``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, List, Mapping, Optional, Sequence

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.domain.config_snapshot import ConfigSnapshot

# Stable, documented entity-type identifiers. They mirror the snapshot's
# collection / index names exactly, so the public ``entity_type`` argument is a
# small, predictable vocabulary (Task 3.4) rather than an arbitrary string. An
# entity_type outside this map is an unsupported lookup → the same no-result as
# an unknown key (never a crash).
#
# Each value pairs the snapshot's by-key accessor with its by-id accessor.
_BY_KEY = 0
_BY_ID = 1

_ENTITY_ACCESSORS: Mapping[
    str,
    tuple[
        Callable[["ConfigSnapshot", str], Optional[Mapping[str, Any]]],
        Callable[["ConfigSnapshot", str], Optional[Mapping[str, Any]]],
    ],
] = {
    "experiences": (
        lambda s, v: s.get_experience_by_key(v),
        lambda s, v: s.get_experience_by_id(v),
    ),
    "features": (
        lambda s, v: s.get_feature_by_key(v),
        lambda s, v: s.get_feature_by_id(v),
    ),
    "goals": (
        lambda s, v: s.get_goal_by_key(v),
        lambda s, v: s.get_goal_by_id(v),
    ),
    "audiences": (
        lambda s, v: s.get_audience_by_key(v),
        lambda s, v: s.get_audience_by_id(v),
    ),
    "segments": (
        lambda s, v: s.get_segment_by_key(v),
        lambda s, v: s.get_segment_by_id(v),
    ),
}

# Supported entity-type identifiers (documented public vocabulary for the
# ``entity_type`` argument). Exposed so the public surface / docs can reference
# the exact set without duplicating it.
SUPPORTED_ENTITY_TYPES: tuple[str, ...] = tuple(_ENTITY_ACCESSORS.keys())


def _no_result() -> Optional[Mapping[str, Any]]:
    """The Story-3.4 single-entity no-result decision point.

    Centralized so Story 4.2 can replace the ``None`` here with the FR50
    typed-reason result object in ONE place, without touching any hit return or
    breaking Story 3.4 callers. Do NOT inline ``None`` at the call sites. The
    return type matches :func:`_resolve` so callers can ``return _no_result()``
    under mypy strict (the value is ``None`` today; the typed annotation reserves
    the Story-4.2 swap point).
    """
    return None


def _resolve(
    snapshot: "ConfigSnapshot",
    entity_type: str,
    identity: str,
    field: int,
) -> Optional[Mapping[str, Any]]:
    """Resolve a single entity by the given identity field, or the no-result.

    ``field`` selects the by-key (:data:`_BY_KEY`) or by-id (:data:`_BY_ID`)
    accessor. An unsupported ``entity_type`` yields the no-result (never raises).
    """
    accessors = _ENTITY_ACCESSORS.get(entity_type)
    if accessors is None:
        return _no_result()
    entity: Optional[Mapping[str, Any]] = accessors[field](snapshot, str(identity))
    if entity is None:
        return _no_result()
    return entity


def resolve_entity(
    snapshot: "ConfigSnapshot",
    entity_type: str,
    key: str,
) -> Optional[Mapping[str, Any]]:
    """Resolve the typed entity of ``entity_type`` matching ``key`` (by-key).

    Returns the snapshot's indexed entity on a hit, or the Story-3.4 no-result
    (``None``) on any miss — unknown key, or an unsupported ``entity_type``.
    Python analogue of JS ``getEntity(key, entityType)``.
    """
    return _resolve(snapshot, entity_type, key, _BY_KEY)


def resolve_entity_by_id(
    snapshot: "ConfigSnapshot",
    entity_type: str,
    entity_id: str,
) -> Optional[Mapping[str, Any]]:
    """Resolve the typed entity of ``entity_type`` matching ``entity_id`` (by-id).

    Returns the snapshot's indexed entity on a hit, or the Story-3.4 no-result
    (``None``) on any miss. Python analogue of JS ``getEntityById(id, entityType)``.
    """
    return _resolve(snapshot, entity_type, entity_id, _BY_ID)


def resolve_entities(
    snapshot: "ConfigSnapshot",
    entity_type: str,
    keys: Sequence[str],
) -> List[Mapping[str, Any]]:
    """Resolve the typed entities of ``entity_type`` for the supplied ``keys``.

    Resolves each key by-key and returns the list of matched entities in the
    supplied order, SKIPPING keys that do not resolve (no ``None`` placeholders).
    An empty list is the normal no-match (including when ``entity_type`` is
    unsupported or ``keys`` is empty). Python analogue of JS
    ``getEntities(keys, entityType)``.
    """
    resolved: List[Mapping[str, Any]] = []
    for key in keys:
        entity = resolve_entity(snapshot, entity_type, key)
        if entity is not None:
            resolved.append(entity)
    return resolved
