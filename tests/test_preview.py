"""qs-02 PY-2 — ``parse_preview_param`` pure helper (AC9).

Covers the pure, side-effect-free preview-param parser: splits the canonical
link format ``{experienceId}.{variationId}`` (dot-separated numeric-id
strings) and returns ``None`` on any malformed shape. No network, no
DataStore, no logging — this is a standalone parsing helper the application
calls before handing the result to ``Context.set_preview`` (PY-5, not this
task).
"""

from typing import Optional, Tuple

import pytest

from convert_sdk import parse_preview_param


def test_parse_preview_param_importable_from_package_root():
    """Public surface: importable directly from ``convert_sdk``, mirroring the
    JS sibling's top-level ``parsePreviewParam`` export."""
    from convert_sdk import parse_preview_param as fn

    assert callable(fn)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("123.456", ("123", "456")),
        ("1.2", ("1", "2")),
    ],
)
def test_parse_preview_param_well_formed(
    value: str, expected: Tuple[str, str]
) -> None:
    assert parse_preview_param(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("123", id="no_dot"),
        pytest.param("1.2.3", id="more_than_one_dot"),
        pytest.param("", id="empty_string"),
        pytest.param(".5", id="leading_dot"),
        pytest.param("5.", id="trailing_dot"),
        pytest.param(" ", id="whitespace_only"),
        pytest.param(".", id="both_parts_empty"),
    ],
)
def test_parse_preview_param_malformed_returns_none(value: str) -> None:
    assert parse_preview_param(value) is None


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("12a.456", id="non_numeric_experience_id"),
        pytest.param("123.45b", id="non_numeric_variation_id"),
        pytest.param("-1.2", id="negative_sign_not_numeric"),
        pytest.param("1.2 ", id="trailing_whitespace_in_variation_id"),
    ],
)
def test_parse_preview_param_non_numeric_segments_return_none(value: str) -> None:
    """Grounded in the JS (``parse-preview-param.ts``) and Ruby
    (``ConvertSdk.parse_preview_param``) sibling implementations, both of
    which require each segment to match ``^\\d+$`` — the spec text itself
    calls the link format "dot-separated numeric ids"."""
    assert parse_preview_param(value) is None


def test_parse_preview_param_ids_kept_as_strings_not_coerced() -> None:
    """IDs are numeric-id strings, never coerced to int (spec: 'IDs are kept
    as strings')."""
    result = parse_preview_param("007.042")
    assert result == ("007", "042")
    assert isinstance(result[0], str)
    assert isinstance(result[1], str)


def test_parse_preview_param_non_str_input_returns_none_defensively() -> None:
    """Static typing declares ``value: str``, but the parser defends against a
    non-str runtime value the same way the JS/Ruby siblings do (``typeof
    value !== 'string'`` / ``value.is_a?(String)``), rather than raising."""
    assert parse_preview_param(None) is None  # type: ignore[arg-type]


def test_parse_preview_param_is_pure_no_side_effects(caplog: pytest.LogCaptureFixture) -> None:
    """Pure function: no logging on malformed input (the caller, PY-5, owns
    warning logging on bad preview input)."""
    with caplog.at_level("WARNING"):
        assert parse_preview_param("bad") is None
    assert caplog.records == []


def test_parse_preview_param_return_type_annotation() -> None:
    import inspect

    sig = inspect.signature(parse_preview_param)
    assert sig.return_annotation in (
        Optional[Tuple[str, str]],
        "Optional[Tuple[str, str]]",
    )
