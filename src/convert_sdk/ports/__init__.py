"""Ports (interfaces) for the Convert Python SDK.

Ports define the boundaries the core orchestration layer depends on, decoupled
from concrete implementations (adapters). Story 1.2 introduces the transport
port; concrete adapters live under ``convert_sdk.adapters``.

Story 3.1 re-exports the :class:`~convert_sdk.ports.storage.DataStore`
persistence protocol here so adapter authors can type-annotate against the
boundary via ``from convert_sdk.ports import DataStore`` without reaching into
``ports.storage`` internals.
"""

from convert_sdk.ports.storage import DataStore

__all__ = ["DataStore"]
