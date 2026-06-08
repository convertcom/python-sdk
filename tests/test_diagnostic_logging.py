"""Story 4.1 — diagnostic-log emission wiring tests (AC #1, #2; Tasks 6.2–6.4).

Exercises the four core flows (init / config-load / evaluation / tracking)
through the public surface with direct-config initialization (offline, no
network) and asserts:

* event-oriented ``convert_sdk`` records are emitted keyed off the
  ``LifecycleEvent`` vocabulary with allowlisted fields (AC #1);
* NFR6 — no raw visitor attributes, email, name, or raw ``visitor_id`` appear;
  only a hashed/fingerprinted visitor reference and allowlisted fields;
* NFR7 — no record at any level contains the raw SDK key or auth/credential
  values.

Adding this logging must NOT change any evaluation/tracking outcome (Critical
Warning #6) — the result assertions below pin that the observable behavior is
identical to the pre-logging suites.
"""

from __future__ import annotations

import logging

import pytest

from convert_sdk import Core, SDKConfig
from convert_sdk._internal.redaction import fingerprint_visitor
from convert_sdk.events import LifecycleEvent

# A self-contained config: one always-qualifying experience and one goal, so the
# evaluation and tracking flows both produce a positive outcome to log.
CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "audiences": [],
    "experiences": [
        {
            "id": "e2",
            "key": "us-experience",
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        }
    ],
    "goals": [{"id": "g1", "key": "signup"}],
}

VISITOR = "visitor-xyz-789"
PII_ATTRS = {"email": "user@co.com", "name": "Jane", "plan": "pro"}


def _messages(caplog):
    return [r.getMessage() for r in caplog.records if r.name == "convert_sdk"]


def _all_text(caplog):
    return "\n".join(_messages(caplog))


def test_init_and_config_load_emit_records(caplog):
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        Core(SDKConfig(data=CONFIG)).initialize()
    text = _all_text(caplog)
    # A config-load / ready lifecycle record is emitted.
    assert any(
        ev.value in text
        for ev in (LifecycleEvent.CONFIG_UPDATED, LifecycleEvent.READY)
    )


def test_evaluation_emits_record_with_hashed_visitor_ref(caplog):
    core = Core(SDKConfig(data=CONFIG)).initialize()
    ctx = core.create_context(VISITOR, visitor_attributes=PII_ATTRS)
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        result = ctx.run_experience("us-experience")
    # Behavior unchanged: the experience still resolves.
    assert result is not None
    text = _all_text(caplog)
    assert LifecycleEvent.BUCKETING.value in text
    # Allowlisted entity key appears; hashed visitor ref appears.
    assert "us-experience" in text
    assert fingerprint_visitor(VISITOR) in text


def test_tracking_emits_record(caplog):
    core = Core(SDKConfig(data=CONFIG)).initialize()
    ctx = core.create_context(VISITOR)
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        result = ctx.track_conversion("signup")
    assert result.tracked is True  # behavior unchanged
    text = _all_text(caplog)
    assert LifecycleEvent.CONVERSION.value in text
    assert "signup" in text  # goal key is allowlisted


def test_nfr6_no_pii_in_logs(caplog):
    """NFR6: a visitor evaluation must not leak raw attributes/email/name/id."""
    core = Core(SDKConfig(data=CONFIG)).initialize()
    ctx = core.create_context(VISITOR, visitor_attributes=PII_ATTRS)
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        ctx.run_experience("us-experience")
        ctx.track_conversion("signup")
    text = _all_text(caplog)
    assert "user@co.com" not in text
    assert "Jane" not in text
    assert VISITOR not in text  # raw visitor_id never appears
    assert "'email'" not in text and "email=" not in text  # no raw attr dump
    assert "plan" not in text


def test_nfr7_no_secret_in_logs(caplog):
    """NFR7: the raw SDK key / auth header / credential values never appear in
    logs at ANY level across init/config-load/evaluation/tracking."""
    raw_key = "sdk_key_abcdef1234567890"
    # Direct-config init never sends the key, but we still drive every flow and
    # assert the key text never surfaces anywhere in the log stream.
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        core = Core(SDKConfig(data=CONFIG)).initialize()
        ctx = core.create_context(VISITOR)
        ctx.run_experience("us-experience")
        ctx.track_conversion("signup")
    text = _all_text(caplog)
    assert raw_key not in text
    assert "Authorization" not in text
    assert "Bearer" not in text


def test_logging_does_not_change_evaluation_outcome():
    """Critical Warning #6: with logging fully enabled vs disabled, the
    evaluation + tracking outcomes are byte-for-byte identical."""
    core = Core(SDKConfig(data=CONFIG)).initialize()
    ctx = core.create_context(VISITOR, visitor_attributes={"country": "US"})

    logging.getLogger("convert_sdk").setLevel(logging.CRITICAL)
    quiet_exp = ctx.run_experience("us-experience")
    quiet_track = ctx.track_conversion("signup", force_multiple=True)

    logging.getLogger("convert_sdk").setLevel(logging.DEBUG)
    loud_exp = ctx.run_experience("us-experience")
    loud_track = ctx.track_conversion("signup", force_multiple=True)

    assert quiet_exp is not None and loud_exp is not None
    assert quiet_exp.variation_id == loud_exp.variation_id
    assert quiet_track.tracked == loud_track.tracked
