"""Boundary normalization for raw config payloads (Story 1.2).

Raw transport/preloaded dictionaries must never leak through the public API or
be stored by reference. Normalization produces an internally-owned structure
with stable shape (collections always present as lists) and deep-copied entity
dicts so later mutation of the caller's input cannot affect a stored snapshot.

This step assumes the payload has already passed
:func:`convert_sdk.config_loader.validators.validate_config`.
"""

from __future__ import annotations

import copy
from typing import Any, Dict, Mapping

_LIST_FIELDS = ("experiences", "features", "goals", "audiences", "segments")


def normalize_config(raw: Mapping[str, Any]) -> Dict[str, Any]:
    """Normalize a validated raw config into an internally-owned dict.

    * Deep-copies entity collections so the result never aliases caller data.
    * Guarantees every known collection field is present as a list.
    * Preserves ``account_id`` and ``project`` as owned copies.
    """
    normalized: Dict[str, Any] = {
        "account_id": raw["account_id"],
        "project": copy.deepcopy(dict(raw["project"])),
    }
    for field_name in _LIST_FIELDS:
        value = raw.get(field_name, [])
        normalized[field_name] = copy.deepcopy(list(value)) if value else []
    return normalized
