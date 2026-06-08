"""Story 4.2 — clear errors and diagnosable no-result outcomes (FR49/FR50/FR51/FR52).

Three test surfaces protect this story:

* **Diagnostic types (PY-1):** the closed :class:`DiagnosticReason` reason set
  (exactly the eight F-018 codes) and the frozen, field-stable ``*Diagnostic``
  dataclasses. Public-API stability is part of the contract (Critical Warning #5).
* **Typed exception context (PY-2):** the on-disk exception hierarchy carries a
  pre-redacted ``SafeContext`` (``code`` + read-only ``context``) and its
  ``__str__``/``__repr__`` never leak SDK keys, auth headers, raw attributes, or
  full URLs with query strings (FR49/NFR23, qs-08 Critical Warning #3).
* **Diagnosable surface + log routing (PY-3):** ``Context.diagnose_*`` returns the
  typed outcomes naming *why* a request did not resolve, miss-path diagnostics
  route through the Story 4.1 :func:`log_safe` seam with the same reason codes and
  no raw visitor data, and the pre-4.2 ``None``-returning callers are unaffected.
"""

from __future__ import annotations

import dataclasses
import logging
from types import MappingProxyType

import pytest

import convert_sdk
from convert_sdk.domain.results import (
    DiagnosticReason,
    EntityDiagnostic,
    ExperienceDiagnostic,
    FeatureDiagnostic,
    GoalDiagnostic,
)

# --- PY-1: closed reason set + frozen diagnostic dataclasses -----------------

# The authoritative F-018 closed set (driver ruling #2). Stale Task 2.3 examples
# (entity_missing, visitor_not_qualified, ...) are NOT part of the vocabulary.
F018_REASON_CODES = {
    "resolved",
    "audience_mismatch",
    "experience_not_found",
    "feature_not_in_selected_variations",
    "feature_not_found",
    "goal_not_found",
    "entity_not_found",
    "project_mapping_required",
}


def test_reason_set_is_exactly_the_eight_f018_codes():
    """The reason vocabulary is CLOSED and equals the eight F-018 codes."""
    assert {member.value for member in DiagnosticReason} == F018_REASON_CODES
    # Stale draft examples must never have leaked into the vocabulary.
    for stale in (
        "entity_missing",
        "visitor_not_qualified",
        "experience_paused",
        "feature_disabled",
        "config_unavailable",
    ):
        assert stale not in {m.value for m in DiagnosticReason}


def test_diagnostic_reason_is_a_string_enum():
    """Codes are a str-Enum so they compare/serialize as their stable values."""
    assert DiagnosticReason.RESOLVED.value == "resolved"
    assert DiagnosticReason.ENTITY_NOT_FOUND == "entity_not_found"


@pytest.mark.parametrize(
    "cls",
    [ExperienceDiagnostic, FeatureDiagnostic, GoalDiagnostic, EntityDiagnostic],
)
def test_diagnostic_dataclasses_are_frozen_and_field_stable(cls):
    """Frozen + stable field names (renames are breaking — Critical Warning #5)."""
    params = dataclasses.fields(cls)
    names = [f.name for f in params]
    assert names[:3] == ["reason", "message", "details"]
    diag = cls(reason=DiagnosticReason.RESOLVED, message="ok")
    with pytest.raises(dataclasses.FrozenInstanceError):
        diag.reason = DiagnosticReason.ENTITY_NOT_FOUND  # type: ignore[misc]


@pytest.mark.parametrize(
    "cls",
    [ExperienceDiagnostic, FeatureDiagnostic, GoalDiagnostic, EntityDiagnostic],
)
def test_diagnostic_details_are_read_only(cls):
    """``details`` is wrapped read-only so callers cannot mutate it."""
    diag = cls(reason=DiagnosticReason.ENTITY_NOT_FOUND, message="x", details={"a": 1})
    assert isinstance(diag.details, MappingProxyType)
    with pytest.raises(TypeError):
        diag.details["b"] = 2  # type: ignore[index]


def test_diagnostic_resolved_helper():
    """A diagnostic exposes whether it represents a resolved (non-miss) outcome."""
    assert ExperienceDiagnostic(reason=DiagnosticReason.RESOLVED, message="ok").resolved
    assert not ExperienceDiagnostic(
        reason=DiagnosticReason.EXPERIENCE_NOT_FOUND, message="no"
    ).resolved


def test_new_diagnostic_types_exported_additively():
    """The diagnostic surface is the documented public surface for FR50."""
    from convert_sdk import (  # noqa: F401
        DiagnosticReason,
        EntityDiagnostic,
        ExperienceDiagnostic,
        FeatureDiagnostic,
        GoalDiagnostic,
    )

    declared = set(convert_sdk.__all__)
    for name in (
        "DiagnosticReason",
        "ExperienceDiagnostic",
        "FeatureDiagnostic",
        "GoalDiagnostic",
        "EntityDiagnostic",
    ):
        assert name in declared
    # Frozen trio + prior exports must remain (nothing removed/renamed).
    assert {"Core", "Context", "__version__", "ExperienceResult"}.issubset(declared)
    # Internal modules must not leak.
    for internal in ("results", "errors", "logging", "_internal", "diagnostics"):
        assert internal not in declared
