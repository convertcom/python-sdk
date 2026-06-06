"""Transport port for the Convert Python SDK (Story 1.2).

Defines the interface ``Core`` depends on to fetch config, decoupled from the
concrete HTTP implementation. Keeping transport behind a ``Protocol`` lets the
evaluation core stay free of HTTP concerns and lets tests substitute a fake
transport without touching the network.

The transport is sync-first for MVP (the public API is sync-first; long-lived
``httpx.Client`` is preferred over one-off request helpers).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Protocol, runtime_checkable

if TYPE_CHECKING:  # pragma: no cover - typing only
    from convert_sdk.config import SDKConfig


@runtime_checkable
class Transport(Protocol):
    """Fetches raw config payloads for the SDK.

    Implementations must enforce TLS-only transport (NFR8), apply the JS-parity
    config route shape, and raise
    :class:`~convert_sdk.errors.ConfigLoadError` on fetch failures.
    """

    def fetch_config(self, config: "SDKConfig") -> Dict[str, Any]:
        """Fetch the raw config payload for the given SDK config.

        Returns the decoded JSON body as a dict. Raises
        :class:`~convert_sdk.errors.ConfigLoadError` on any transport/HTTP/decode
        failure.
        """
        ...

    def close(self) -> None:
        """Release any held resources (e.g. the underlying HTTP client)."""
        ...

    def __enter__(self) -> "Transport": ...

    def __exit__(self, *exc: Any) -> bool: ...
