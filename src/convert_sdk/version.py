"""Single source of truth for the Convert Python SDK version.

Canonical naming decision (qs-01): the version is sourced from exactly one
location — this module. The distribution name on PyPI is ``convert-python-sdk``
while the import package is ``convert_sdk``; the two differ by design.

The release pipeline (``semantic-release`` via ``.github/workflows/release.yml``)
stamps the real version into this file at build time as an **uncommitted**
working-tree edit — ``uv build`` (hatchling) then reads ``__version__`` via the
``[tool.hatch.version] path`` config. The value ``"0.0.0"`` is a dev placeholder;
do **not** hand-bump it (the pipeline owns versioning).
"""

__version__ = "0.0.0"
