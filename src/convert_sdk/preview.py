"""Preview-param parsing for the Convert Python SDK (qs-02 PY-2 / AC9).

A pure, dependency-free helper that parses the canonical experiment-preview
link parameter ``convert_preview={experienceId}.{variationId}`` (dot-separated
numeric-id strings, mirroring the web tracking script's force-param
``_conv_eforce={expId}.{varId}``). The application extracts the raw value from
the request URL and hands the parsed ``(experience_id, variation_id)`` pair to
:meth:`~convert_sdk.context.Context.set_preview` (PY-5 — not implemented by
this module).

Behavioral contract (identical across the JS/PHP/Ruby/Android/iOS siblings —
see the JS reference ``packages/js-sdk/src/parse-preview-param.ts`` and the
Ruby reference ``ConvertSdk.parse_preview_param``, both of which this module
mirrors):

* Splits on the FIRST dot only; a second dot anywhere in the value is
  malformed (``"1.2.3"`` -> ``None``), not "split on the last dot" or
  "ignore extra dots".
* Both segments must be non-empty and numeric-only (``^\\d+$``) — the spec
  text calls the link format "dot-separated numeric ids". A non-numeric
  segment (letters, a leading ``-``, embedded whitespace) is malformed.
* IDs are returned as ``str`` — never coerced to ``int`` — because they are
  numeric-id STRINGS (matched against config entity ids, which are strings
  throughout this SDK; see ``evaluation/entity_lookup.py``).
* Pure function: never raises, performs no logging, and has no side effects.
  A non-``str`` runtime value (despite the ``str`` type annotation) returns
  ``None`` defensively rather than raising, matching the JS/Ruby siblings'
  runtime guard for callers on non-statically-typed input paths.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

# Both segments of a preview param must be non-empty digit-only strings. The
# ``+`` quantifier is what makes an empty segment (e.g. the leading segment of
# ".5" or the trailing segment of "5.") fail to match, so no separate
# empty-string check is needed.
_NUMERIC_ONLY_RE = re.compile(r"^\d+$")


def parse_preview_param(value: str) -> Optional[Tuple[str, str]]:
    """Parse ``"{experience_id}.{variation_id}"`` into a ``(str, str)`` pair.

    Returns ``None`` for any malformed shape: missing dot, more than one dot,
    an empty or non-numeric segment, or a non-``str`` input.
    """
    if not isinstance(value, str):
        return None

    dot_index = value.find(".")
    if dot_index == -1:
        return None
    if value.find(".", dot_index + 1) != -1:
        return None

    experience_id = value[:dot_index]
    variation_id = value[dot_index + 1 :]

    if not _NUMERIC_ONLY_RE.match(experience_id) or not _NUMERIC_ONLY_RE.match(
        variation_id
    ):
        return None

    return experience_id, variation_id
