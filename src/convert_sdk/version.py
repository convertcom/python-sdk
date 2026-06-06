"""Single source of truth for the Convert Python SDK version.

Canonical naming decision (qs-01): the version is sourced from exactly one
location — this module. The distribution name on PyPI is ``convert-python-sdk``
while the import package is ``convert_sdk``; the two differ by design.
"""

__version__ = "0.1.0"
