"""Single source of truth for the Convert Python SDK version.

Canonical naming decision (qs-01): the version is sourced from exactly one
location — this module. The distribution name on PyPI is ``convert-python-sdk``
while the import package is ``convert_sdk``; the two differ by design.

The release pipeline (``semantic-release`` via ``.github/workflows/release.yml``)
stamps the real version into this file at build time as an **uncommitted**
working-tree edit — ``uv build`` (hatchling) then reads ``__version__`` via the
``[tool.hatch.version] path`` config. The value ``"0.0.0"`` is a dev placeholder;
do **not** hand-bump it (the pipeline owns versioning).

``version_info`` is the ``(major, minor, patch)`` tuple of ints parsed from
``__version__``. Parsing runs at import, so a malformed stamp fails the build
loudly instead of shipping a package whose version cannot be compared.
"""

import re
from typing import Tuple

__version__ = "0.0.0"

# ASCII digits only: ``\d`` would accept other Unicode digits, and the release
# stamp is always plain ``MAJOR.MINOR.PATCH``.
_VERSION_PATTERN = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")


def _parse_version_info(value: str) -> Tuple[int, int, int]:
    """Parse ``MAJOR.MINOR.PATCH`` into a tuple of ints, or raise ``ValueError``."""
    match = _VERSION_PATTERN.fullmatch(value)
    if match is None:
        raise ValueError(f"__version__ must be MAJOR.MINOR.PATCH, got {value!r}")
    major, minor, patch = match.groups()
    return int(major), int(minor), int(patch)


version_info = _parse_version_info(__version__)
