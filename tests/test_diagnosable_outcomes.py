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


# --- PY-2: typed exception SafeContext carriers (FR49 / NFR23) ----------------

RAW_CONFIG_URL = (
    "https://cdn.example.com/config/sdk_key_abcdef1234567890"
    "?environment=prod&token=supersecret"
)


def test_base_error_carries_code_and_read_only_context():
    """ConvertSDKError exposes ``code`` + a read-only ``context`` mapping."""
    from convert_sdk._internal.redaction import SafeContext
    from convert_sdk.errors import ConvertSDKError

    err = ConvertSDKError("boom", code="generic_failure", context=SafeContext(status_code=500))
    assert err.code == "generic_failure"
    assert isinstance(err.context, MappingProxyType)
    assert err.context["status_code"] == 500
    with pytest.raises(TypeError):
        err.context["status_code"] = 0  # type: ignore[index]


def test_base_error_context_defaults_are_safe():
    """A plain error has an empty (never ``None``) context and no code by default."""
    from convert_sdk.errors import ConvertSDKError

    err = ConvertSDKError("boom")
    assert err.code is None
    assert isinstance(err.context, MappingProxyType)
    assert dict(err.context) == {}


def test_config_load_error_includes_status_and_redacted_url_no_query():
    """ConfigLoadError carries status + redacted endpoint; message has no query."""
    from convert_sdk.errors import ConfigLoadError

    err = ConfigLoadError("config fetch failed", endpoint=RAW_CONFIG_URL, status_code=503)
    text = str(err)
    # No raw secrets anywhere in the rendered message.
    assert "supersecret" not in text
    assert "environment=prod" not in text
    assert "?" not in text
    assert "sdk_key_abcdef1234567890" not in text
    # Diagnosable safe context present.
    assert "503" in text
    assert "cdn.example.com" in text
    # Backwards-compatible attributes preserved.
    assert err.status_code == 503
    # Story 4.2 enrichment: a SafeContext-derived read-only context carrier.
    assert err.context["status_code"] == 503
    assert "supersecret" not in str(err.context)


def test_config_load_error_repr_is_secret_free():
    """``repr`` must be as safe as ``str`` (no SDK key / query / token)."""
    from convert_sdk.errors import ConfigLoadError

    err = ConfigLoadError("config fetch failed", endpoint=RAW_CONFIG_URL, status_code=503)
    r = repr(err)
    for leak in ("supersecret", "environment=prod", "sdk_key_abcdef1234567890", "?token"):
        assert leak not in r


def test_tracking_delivery_error_includes_batch_and_retry_no_secrets():
    """TrackingDeliveryError carries batch_size + retry_count, never the SDK key."""
    from convert_sdk.errors import TrackingDeliveryError

    err = TrackingDeliveryError(
        "delivery failed",
        endpoint="https://track.example.com/track/sdk_key_abcdef1234567890",
        status_code=502,
        batch_size=15,
        retry_count=2,
    )
    text = str(err)
    assert "15" in text  # batch_size
    assert "502" in text  # status
    assert "sdk_key_abcdef1234567890" not in text
    assert err.context["batch_size"] == 15
    assert err.context["retry_count"] == 2
    assert err.status_code == 502


def test_conversion_data_error_never_embeds_raw_value():
    """ConversionDataError carries only the offending key + safe reason (no value)."""
    from convert_sdk.errors import ConversionDataError

    err = ConversionDataError("payload", reason="not a JSON primitive")
    text = str(err)
    assert "payload" in text
    assert "not a JSON primitive" in text
