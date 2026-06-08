"""Story 4.1 — log_safe() wrapper + library-logging-discipline tests (AC #1, #2).

Covers the ``convert_sdk.logging.log_safe`` helper that every SDK log call site
uses: it builds a stable, event-oriented log record from a ``LifecycleEvent``
name plus a :class:`~convert_sdk._internal.redaction.SafeContext` (and/or
already-redacted kwargs), routing every value through the centralized redaction
primitives. Also pins the library-logging discipline (no ``basicConfig``, no
handler/level mutation) and structural-at-all-levels redaction.
"""

from __future__ import annotations

import logging

import pytest

from convert_sdk._internal.redaction import SafeContext
from convert_sdk.events import LifecycleEvent
from convert_sdk.logging import log_safe, logger as sdk_logger


def test_log_safe_emits_on_convert_sdk_namespace(caplog):
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        log_safe(
            LifecycleEvent.CONFIG_UPDATED,
            level=logging.INFO,
            context=SafeContext(endpoint="cdn.convert.com/c.json", status_code=200),
        )
    records = [r for r in caplog.records if r.name == "convert_sdk"]
    assert records, "log_safe must emit on the convert_sdk logger"
    rec = records[-1]
    assert rec.levelno == logging.INFO
    msg = rec.getMessage()
    # Stable event-oriented phrasing keyed off the LifecycleEvent vocabulary.
    assert LifecycleEvent.CONFIG_UPDATED.value in msg
    assert "endpoint=cdn.convert.com/c.json" in msg
    assert "status_code=200" in msg


def test_log_safe_default_level_is_info(caplog):
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        log_safe(LifecycleEvent.READY)
    rec = [r for r in caplog.records if r.name == "convert_sdk"][-1]
    assert rec.levelno == logging.INFO


def test_log_safe_honors_caller_supplied_logger(caplog):
    custom = logging.getLogger("convert_sdk.testcustom")
    with caplog.at_level(logging.DEBUG, logger="convert_sdk.testcustom"):
        log_safe(
            LifecycleEvent.BUCKETING,
            level=logging.DEBUG,
            target=custom,
            context=SafeContext(entity_key="exp-1"),
        )
    records = [r for r in caplog.records if r.name == "convert_sdk.testcustom"]
    assert records
    assert "entity_key=exp-1" in records[-1].getMessage()


def test_log_safe_redacts_url_kwargs_structurally(caplog):
    # A raw URL passed as a kwarg must be redacted at record-construction time,
    # not relied on level-gating. Even at DEBUG no query string survives.
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        log_safe(
            LifecycleEvent.CONFIG_UPDATED,
            level=logging.DEBUG,
            url="https://cdn.convert.com/config/sdk_key_abcdef1234567890?token=secret",
        )
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "convert_sdk")
    assert "token=secret" not in text
    assert "sdk_key_abcdef1234567890" not in text
    assert "?" not in text
    assert "cdn.convert.com/config/" in text


def test_log_safe_never_emits_raw_key_kwarg(caplog):
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        log_safe(
            LifecycleEvent.READY,
            level=logging.DEBUG,
            key="sdk_key_abcdef1234567890",
        )
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "convert_sdk")
    assert "sdk_key_abcdef1234567890" not in text
    # If shown at all, only the masked shape may appear.
    if "sdk_" in text:
        assert "sdk_****_7890" in text


@pytest.mark.parametrize("level", [logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR])
def test_log_safe_redaction_is_level_independent(caplog, level):
    with caplog.at_level(logging.DEBUG, logger="convert_sdk"):
        log_safe(
            LifecycleEvent.API_QUEUE_RELEASED,
            level=level,
            url="https://h/track/k?auth=bearerSECRET",
        )
    text = " ".join(r.getMessage() for r in caplog.records if r.name == "convert_sdk")
    assert "bearerSECRET" not in text


# --- library-logging discipline ---------------------------------------------


def test_sdk_logger_adds_no_handlers():
    # The SDK must not attach handlers to its own logger or the root logger.
    assert sdk_logger.handlers == [] or all(
        isinstance(h, logging.NullHandler) for h in sdk_logger.handlers
    )


def test_log_safe_does_not_call_basicconfig(monkeypatch):
    called = {"basic": False}

    def _fake_basicconfig(*a, **k):
        called["basic"] = True

    monkeypatch.setattr(logging, "basicConfig", _fake_basicconfig)
    log_safe(LifecycleEvent.READY)
    assert called["basic"] is False


def test_log_safe_does_not_mutate_root_logger():
    root = logging.getLogger()
    before_level = root.level
    before_handlers = list(root.handlers)
    log_safe(LifecycleEvent.READY, level=logging.INFO)
    assert root.level == before_level
    assert list(root.handlers) == before_handlers


def test_sdk_logger_propagate_default_unchanged():
    # The SDK does not flip propagate off (that would swallow records in apps
    # that configure the root logger).
    assert sdk_logger.propagate is True
