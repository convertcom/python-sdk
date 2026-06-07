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
    """Fetches raw config payloads and delivers tracking events for the SDK.

    Implementations must enforce TLS-only transport (NFR8), apply the JS-parity
    config and tracking route shapes, and raise
    :class:`~convert_sdk.errors.ConfigLoadError` on config-fetch failures and a
    typed :class:`~convert_sdk.errors.ConvertSDKError` on tracking-delivery
    failures.
    """

    def fetch_config(self, config: "SDKConfig") -> Dict[str, Any]:
        """Fetch the raw config payload for the given SDK config.

        Returns the decoded JSON body as a dict. Raises
        :class:`~convert_sdk.errors.ConfigLoadError` on any transport/HTTP/decode
        failure.
        """
        ...

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> None:
        """Deliver a serialized tracking-events batch over HTTPS (Story 2.3).

        POSTs ``payload`` (the verbose JS-SDK batch envelope produced by
        ``tracking/payloads.py``) to the JS-parity route ``/track/{sdkKey}``.
        Performs no retry/backoff — transport-level retries (if any) live in the
        adapter, and the tracking layer calls this exactly once per release.
        Raises a typed :class:`~convert_sdk.errors.ConvertSDKError` (subclass) on
        any transport/HTTP failure so the caller can leave the queue intact.
        """
        ...

    def close(self) -> None:
        """Release any held resources (e.g. the underlying HTTP client)."""
        ...

    def __enter__(self) -> "Transport": ...

    def __exit__(self, *exc: Any) -> bool: ...
