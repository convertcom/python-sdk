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

    def send_tracking(self, payload: Dict[str, Any], *, sdk_key: str) -> int:
        """Deliver a serialized tracking-events batch over HTTPS (Story 2.3).

        POSTs ``payload`` (the verbose JS-SDK batch envelope produced by
        ``tracking/payloads.py``) to the JS-parity route ``/track/{sdkKey}``.
        Performs no retry/backoff — transport-level retries (if any) live in the
        adapter, and the tracking layer calls this exactly once per release.
        Returns the HTTP status code (int, e.g. 200) on a successful delivery
        so the caller can populate ``QueueReleasedPayload.status_code`` on the
        success path.
        Raises a typed :class:`~convert_sdk.errors.ConvertSDKError` (subclass) on
        any transport/HTTP failure so the caller can leave the queue intact.
        """
        ...

    def close(self) -> None:
        """Release any held resources (e.g. the underlying HTTP client)."""
        ...

    def __enter__(self) -> "Transport": ...

    def __exit__(self, *exc: Any) -> None: ...


@runtime_checkable
class SupportsPreviewFetch(Protocol):
    """Additive capability Protocol for experiment-preview support (qs-02 PY-5).

    ``Transport`` itself is a PUBLIC, semver-governed extension point (a real
    integrator can construct ``Core(config, transport=MyTransport())``), so it
    never gains a new REQUIRED method for a rare, opt-in capability — doing so
    would be a breaking change for any existing/future custom ``Transport``
    implementation (decision-log I22). Instead, a concrete transport that ALSO
    implements this one method opts into ``Context.set_preview``'s ``?exp=``
    fetch-through automatically via structural typing: ``Core`` duck-checks
    ``isinstance(transport, SupportsPreviewFetch)`` before attempting the fetch,
    and degrades gracefully (no fetch attempted, ``Context.set_preview`` warns
    and stays inert) for a transport that does not implement it. The concrete
    :class:`~convert_sdk.adapters.transport.httpx_transport.HttpxTransport`
    already implements this method, so it satisfies this Protocol with no
    changes.
    """

    def fetch_config_by_experience(
        self, config: "SDKConfig", experience_id: str
    ) -> Dict[str, Any]:
        """Fetch config scoped to a single experience via ``?exp={experience_id}``.

        Returns the decoded JSON body as a dict. Raises
        :class:`~convert_sdk.errors.ConfigLoadError` on any transport/HTTP/decode
        failure — the caller (``Core``/``Context.set_preview``) is responsible
        for catching it and downgrading to the AC7 inert-with-warning contract.
        """
        ...
