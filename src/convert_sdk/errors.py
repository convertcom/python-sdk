"""Typed SDK error hierarchy."""

from __future__ import annotations

from types import MappingProxyType
from typing import Any, Mapping


class ConvertSDKError(Exception):
    """Base error for the Convert Python SDK."""

    def __init__(
        self,
        message: str = "",
        *,
        code: str | None = None,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.context = MappingProxyType(
            {str(key): value for key, value in (context or {}).items()}
        )


class InitializationError(ConvertSDKError):
    """Base error for initialization and readiness failures."""


class ConfigValidationError(InitializationError):
    """Raised when configuration input is malformed or incomplete."""


class ConfigLoadError(InitializationError):
    """Raised when remote configuration loading fails."""


class TrackingError(ConvertSDKError):
    """Base error for conversion-tracking failures."""


class GoalNotFoundError(TrackingError):
    """Raised when a conversion references a goal missing from the config."""


class ConversionDataError(TrackingError):
    """Raised when conversion data is malformed for tracking."""


class TrackingDeliveryError(TrackingError):
    """Raised by ``TrackingQueue.release()`` when a batch fails mid-flush.

    Carries the partial-success bookkeeping so callers can tell how
    many events did go out before the failure. The underlying transport
    or serialization exception is available via ``__cause__``.
    """

    def __init__(
        self,
        message: str = "Tracking delivery failed",
        *,
        code: str | None = "tracking.delivery_failed",
        delivered_event_count: int = 0,
        delivered_batch_count: int = 0,
        remaining_event_count: int = 0,
        context: Mapping[str, Any] | None = None,
    ) -> None:
        merged_context = dict(context or {})
        merged_context.setdefault("delivered_event_count", delivered_event_count)
        merged_context.setdefault("delivered_batch_count", delivered_batch_count)
        merged_context.setdefault("remaining_event_count", remaining_event_count)
        super().__init__(message, code=code, context=merged_context)
        self.delivered_event_count = delivered_event_count
        self.delivered_batch_count = delivered_batch_count
        self.remaining_event_count = remaining_event_count
