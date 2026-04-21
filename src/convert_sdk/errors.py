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
