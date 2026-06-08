"""Story 4.3 — Support Cross-SDK Debugging (FR48, partial AC #1).

This story extends the EXISTING diagnostic surface (Story 4.1's ``log_safe``
seam + Story 4.2's typed ``_Diagnostic.details`` mapping) so a diagnostic
carries the partial cross-SDK-comparable field set IN SCOPE for 4.3:

* ``reason`` — the closed Story 4.2 ``DiagnosticReason`` code value
* ``environment`` — the SDK config environment (or ``None`` for a directly
  constructed context with no environment wired)
* ``bucket_value`` — the deterministic bucketing value for a resolved
  experience (``None`` on a miss / non-experience diagnostic)
* ``variation_key`` — the selected variation key for a resolved experience
* ``visitor_ref`` — a HASHED visitor reference via
  :func:`convert_sdk._internal.redaction.fingerprint_visitor` (NEVER the raw id)

Deferred (NOT exercised here): ``config_version``, ``bucketing_inputs``
(key/traffic/seed/salt), ``experience_key`` completion (Story 4.5); the
parity-comparison helper + diagnostic-vector fixtures (Story 5.1); the formal
byte-comparable contract document ``docs/debugging.md`` (Story 4.5).

Guardrails (driver scope + story Architecture): there is NO ``diagnostics.py``
module, NO ``events.visitor_reference`` helper. The comparable fields live in
``_Diagnostic.details`` (4-2's read-only mapping) and are mirrored through
``log_safe`` (4-1). The visitor id appears ONLY as a ``fingerprint_visitor``
hash. The JS SDK has no diagnostic visitor-hash mechanism, so visitor-reference
byte-comparable parity is NOT asserted across SDKs.
"""

from __future__ import annotations

import contextlib
import logging

from convert_sdk._internal.redaction import fingerprint_visitor
from convert_sdk.context import Context
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.domain.results import DiagnosticReason, ExperienceDiagnostic

VISITOR = "visitor-cross-sdk-001"

# One always-qualifying experience (resolves + buckets) and one unknown key.
RESOLVING_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [
        {
            "id": "e1",
            "key": "open-exp",
            "variations": [
                {"id": "v1", "key": "treat", "traffic_allocation": 100.0},
            ],
        },
    ],
    "features": [],
    "goals": [{"id": "g1", "key": "signup"}],
}

#: The partial cross-SDK-comparable field set in scope for Story 4.3.
PARTIAL_CONTRACT_FIELDS = {
    "reason",
    "environment",
    "bucket_value",
    "variation_key",
    "visitor_ref",
}

#: Fields required by AC-1 but DEFERRED — must NOT have been smuggled in early.
DEFERRED_AC1_FIELDS = {"config_version", "bucketing_inputs", "seed", "salt", "traffic"}


def _context(*, environment=None, visitor=VISITOR, config=RESOLVING_CONFIG):
    return Context(
        visitor,
        ConfigSnapshot.from_normalized(config),
        environment=environment,
    )


# --- Task 4.1: capture diagnostic output + assert the partial contract -------


def test_resolved_experience_diagnostic_carries_partial_cross_sdk_field_set():
    """A RESOLVED experience diagnostic exposes the full partial field set."""
    diag = _context(environment="prod").diagnose_experience("open-exp")
    assert isinstance(diag, ExperienceDiagnostic)
    assert diag.reason is DiagnosticReason.RESOLVED

    details = diag.details
    assert PARTIAL_CONTRACT_FIELDS.issubset(set(details.keys()))
    assert details["reason"] == DiagnosticReason.RESOLVED.value
    assert details["environment"] == "prod"
    assert details["variation_key"] == "treat"
    # bucket_value is the deterministic bucketing value for the resolved exp.
    assert isinstance(details["bucket_value"], (int, float))
    assert details["visitor_ref"] == fingerprint_visitor(VISITOR)


def test_partial_contract_does_not_leak_deferred_ac1_fields():
    """The deferred AC-1 fields (Story 4.5) must NOT appear yet."""
    details = _context(environment="prod").diagnose_experience("open-exp").details
    assert DEFERRED_AC1_FIELDS.isdisjoint(set(details.keys()))


def test_miss_diagnostic_carries_reason_environment_and_hashed_visitor():
    """A miss still carries reason/environment/visitor_ref; bucket/variation absent-or-None."""
    diag = _context(environment="staging").diagnose_experience("nope")
    assert diag.reason is DiagnosticReason.EXPERIENCE_NOT_FOUND
    details = diag.details
    assert details["reason"] == DiagnosticReason.EXPERIENCE_NOT_FOUND.value
    assert details["environment"] == "staging"
    assert details["visitor_ref"] == fingerprint_visitor(VISITOR)
    # No bucketing happened on a miss.
    assert details.get("bucket_value") is None
    assert details.get("variation_key") is None


def test_environment_defaults_to_none_when_not_wired():
    """A directly-constructed context with no environment yields environment=None."""
    details = _context().diagnose_experience("open-exp").details
    assert details["environment"] is None


def test_visitor_id_never_appears_raw_in_details_or_log():
    """NFR6/NFR51: the raw visitor id never leaks — only the fingerprint hash."""
    pii_visitor = "raw-visitor-id-leak-check"
    ctx = Context(
        pii_visitor,
        ConfigSnapshot.from_normalized(RESOLVING_CONFIG),
        environment="prod",
        visitor_attributes={"email": "user@co.com", "name": "Jane"},
    )
    with _caplog_at_debug() as records:
        diag = ctx.diagnose_experience("open-exp")
    log_text = "\n".join(r.getMessage() for r in records if r.name == "convert_sdk")
    details_repr = repr(dict(diag.details))

    for sink in (log_text, details_repr):
        assert pii_visitor not in sink
        assert "user@co.com" not in sink
        assert "Jane" not in sink
    # The hashed reference is what appears instead.
    assert fingerprint_visitor(pii_visitor) == diag.details["visitor_ref"]


def test_diagnostic_log_mirrors_partial_field_set():
    """Miss-path diagnostic log carries reason + environment + hashed visitor."""
    ctx = Context(
        VISITOR,
        ConfigSnapshot.from_normalized(RESOLVING_CONFIG),
        environment="prod",
    )
    with _caplog_at_debug() as records:
        ctx.diagnose_experience("nope")
    text = "\n".join(r.getMessage() for r in records if r.name == "convert_sdk")
    assert DiagnosticReason.EXPERIENCE_NOT_FOUND.value in text
    assert "prod" in text
    assert fingerprint_visitor(VISITOR) in text


def test_details_mapping_stays_read_only():
    """Comparable fields live in the frozen 4-2 read-only details mapping."""
    import pytest

    details = _context(environment="prod").diagnose_experience("open-exp").details
    with pytest.raises(TypeError):
        details["environment"] = "tamper"  # type: ignore[index]


@contextlib.contextmanager
def _caplog_at_debug():
    """Capture ``convert_sdk`` records at DEBUG via a temporary handler."""

    class _Capture(logging.Handler):
        def __init__(self):
            super().__init__()
            self.records = []

        def emit(self, record):
            self.records.append(record)

    logger = logging.getLogger("convert_sdk")
    handler = _Capture()
    prev_level = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.records
    finally:
        logger.removeHandler(handler)
        logger.setLevel(prev_level)
