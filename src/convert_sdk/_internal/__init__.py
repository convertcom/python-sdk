"""Internal leaf-utility package for the Convert Python SDK (architecture L0).

``_internal/`` is the lowest layer in the module-dependency graph: a set of
pure, dependency-free utilities that every other layer may import *inward*. It
imports **stdlib only** and reaches back into NO other ``convert_sdk`` module.

This package deliberately exports NOTHING publicly — it is not part of the SDK's
consumer API (``convert_sdk.__init__`` does not re-export from here). Import the
concrete utility modules directly (e.g.
``from convert_sdk._internal.redaction import redact_url``).
"""

from __future__ import annotations
