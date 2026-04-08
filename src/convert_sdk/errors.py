"""Typed SDK error hierarchy."""


class ConvertSDKError(Exception):
    """Base error for the Convert Python SDK."""


class InitializationError(ConvertSDKError):
    """Base error for initialization and readiness failures."""


class ConfigValidationError(InitializationError):
    """Raised when configuration input is malformed or incomplete."""


class ConfigLoadError(InitializationError):
    """Raised when remote configuration loading fails."""
