"""Lightweight boundary validation for raw config payloads (Story 1.2).

Validation is intentionally minimal and ``pydantic``-free (Python 3.9+
compatible, no heavy core dependency). It checks only the structural invariants
Story 1.2 needs to build a snapshot; richer entity validation belongs to later
stories that actually consume those entities.

Malformed config raises :class:`~convert_sdk.errors.InvalidConfigError` — a
typed, diagnosable failure (AC #3) distinct from any future no-result outcome.
"""

from __future__ import annotations

from typing import Any

from convert_sdk.errors import InvalidConfigError

# Collection fields that, when present, must be lists.
_LIST_FIELDS = ("experiences", "features", "goals", "audiences", "segments")


def validate_config(raw: Any) -> None:
    """Validate the structural shape of a raw config payload.

    Raises:
        InvalidConfigError: if the payload is not a dict, is missing the
            required ``account_id`` / ``project`` fields, or has a malformed
            ``project`` or collection field.
    """
    if not isinstance(raw, dict):
        raise InvalidConfigError(
            f"config must be a mapping/dict; got {type(raw).__name__}"
        )

    if "account_id" not in raw or raw.get("account_id") in (None, ""):
        raise InvalidConfigError("config is missing required field 'account_id'")

    project = raw.get("project")
    if project is None:
        raise InvalidConfigError("config is missing required field 'project'")
    if not isinstance(project, dict):
        raise InvalidConfigError("config 'project' must be a mapping/dict")
    if project.get("id") in (None, ""):
        raise InvalidConfigError("config 'project' is missing required field 'id'")

    for field_name in _LIST_FIELDS:
        if field_name in raw and not isinstance(raw[field_name], list):
            raise InvalidConfigError(
                f"config '{field_name}' must be a list when present; "
                f"got {type(raw[field_name]).__name__}"
            )
