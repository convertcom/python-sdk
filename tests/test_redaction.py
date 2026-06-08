"""Story 4.1 — centralized redaction primitive tests (qs-08, AC #2).

Table-driven unit tests over the single source of redaction logic
(``convert_sdk._internal.redaction``): :func:`redact_key`, :func:`redact_url`,
the :class:`SafeContext` dataclass render, and :func:`fingerprint_visitor`.

The frozen qs-08 contract is the test target:

* ``redact_key`` → first 4 + ``****`` + last 4 (``sdk_key_abcdef1234567890`` →
  ``sdk_****_7890``); short keys (≤ 8 chars) collapse to a fully-masked form so
  the mask never reveals a majority of a short key.
* ``redact_url`` → host + path with the ENTIRE query string elided (stricter
  NFR23 interpretation), never per-parameter stripping.
* ``SafeContext`` carries ONLY the six approved operational fields and renders
  an allowlist-only mapping — it physically cannot hold a raw secret/PII field.
* ``fingerprint_visitor`` → a stable hashed reference, never the raw id.
"""

from __future__ import annotations

import hashlib

import pytest

from convert_sdk._internal.redaction import (
    SafeContext,
    fingerprint_visitor,
    redact_key,
    redact_url,
)


# --- redact_key --------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        # qs-08 canonical example.
        ("sdk_key_abcdef1234567890", "sdk_****_7890"),
        # Another long key — first4 + "****_" + last4.
        ("abcdefghijklmnop", "abcd****_mnop"),
    ],
)
def test_redact_key_long_keys_mask_middle(raw, expected):
    assert redact_key(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "12345678",  # exactly 8 — boundary, fully masked
        "short",
        "a",
        "",
    ],
)
def test_redact_key_short_keys_fully_masked(raw):
    masked = redact_key(raw)
    # A short key must NOT expose a majority of its characters.
    assert raw not in masked or raw == ""
    # No 4-char prefix/suffix leak for short keys.
    assert masked == "****"


def test_redact_key_none_is_safe():
    assert redact_key(None) == "****"


def test_redact_key_never_returns_raw_long_key():
    raw = "sdk_key_abcdef1234567890"
    masked = redact_key(raw)
    assert masked != raw
    assert raw not in masked
    # The middle (secret) characters never appear.
    assert "abcdef123456" not in masked


# --- redact_url --------------------------------------------------------------


@pytest.mark.parametrize(
    "url, expected",
    [
        (
            "https://cdn.convert.com/js/123456-789.json?token=secret",
            "cdn.convert.com/js/123456-789.json",
        ),
        (
            "https://cdn.convert.com/config/sdk_key_abcdef1234567890?_conv_low_cache=1",
            # whole query elided; key segment additionally masked.
            "cdn.convert.com/config/sdk_****_7890",
        ),
        (
            # Short key segment in a /track/ route is fully masked (<=8 chars).
            "https://host.example/track/key?a=1&b=2",
            "host.example/track/****",
        ),
        (
            # A non-route path is left intact apart from query elision.
            "https://host.example/js/abc.json?a=1",
            "host.example/js/abc.json",
        ),
        (
            "https://host.example/path/no/query",
            "host.example/path/no/query",
        ),
    ],
)
def test_redact_url_elides_entire_query(url, expected):
    assert redact_url(url) == expected


def test_redact_url_none_passthrough():
    assert redact_url(None) is None


def test_redact_url_never_leaks_query_secret():
    url = "https://cdn.convert.com/js/c.json?token=topsecret&auth=bearerXYZ"
    redacted = redact_url(url)
    assert "topsecret" not in redacted
    assert "bearerXYZ" not in redacted
    assert "?" not in redacted


def test_redact_url_non_url_value_strips_query():
    # A non-absolute value still has its query stripped (defense in depth).
    assert redact_url("not a url?secret=1") == "not a url"


# --- SafeContext -------------------------------------------------------------

_APPROVED_FIELDS = {
    "endpoint",
    "status_code",
    "config_version",
    "entity_key",
    "batch_size",
    "retry_count",
}


def test_safe_context_only_six_approved_fields():
    import dataclasses

    field_names = {f.name for f in dataclasses.fields(SafeContext)}
    assert field_names == _APPROVED_FIELDS


def test_safe_context_all_default_none():
    ctx = SafeContext()
    assert ctx.endpoint is None
    assert ctx.status_code is None
    assert ctx.config_version is None
    assert ctx.entity_key is None
    assert ctx.batch_size is None
    assert ctx.retry_count is None


def test_safe_context_render_omits_none_fields():
    ctx = SafeContext(endpoint="cdn.convert.com/c.json", status_code=503)
    fields = ctx.as_log_fields()
    assert fields == {"endpoint": "cdn.convert.com/c.json", "status_code": 503}
    # No PII/secret keys can ever appear — only the allowlist.
    assert set(fields).issubset(_APPROVED_FIELDS)


def test_safe_context_render_all_fields():
    ctx = SafeContext(
        endpoint="host/p",
        status_code=200,
        config_version="v7",
        entity_key="exp-1",
        batch_size=15,
        retry_count=2,
    )
    fields = ctx.as_log_fields()
    assert set(fields) == _APPROVED_FIELDS
    assert fields["config_version"] == "v7"
    assert fields["batch_size"] == 15


def test_safe_context_str_is_compact_allowlist_only():
    ctx = SafeContext(endpoint="host/p", status_code=503, config_version=None)
    rendered = str(ctx)
    assert "endpoint=host/p" in rendered
    assert "status_code=503" in rendered
    # None fields are omitted from the compact form.
    assert "config_version" not in rendered


# --- fingerprint_visitor -----------------------------------------------------


def test_fingerprint_visitor_is_stable():
    a = fingerprint_visitor("visitor-123")
    b = fingerprint_visitor("visitor-123")
    assert a == b


def test_fingerprint_visitor_never_raw_id():
    raw = "visitor-123"
    fp = fingerprint_visitor(raw)
    assert raw not in fp
    assert fp != raw


def test_fingerprint_visitor_matches_sha256_prefix():
    raw = "visitor-123"
    fp = fingerprint_visitor(raw)
    full = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    # The fingerprint is a stable prefix of the SHA-256 hex digest.
    assert full.startswith(fp)
    assert len(fp) >= 8


def test_fingerprint_visitor_distinct_inputs_distinct_outputs():
    assert fingerprint_visitor("a") != fingerprint_visitor("b")
