"""Privacy-safe diagnostic logging helpers for SDK internals."""

from __future__ import annotations

import logging
from typing import Any, Mapping

from .domain.config_snapshot import ConfigSnapshot
from .events import visitor_reference


DIAGNOSTIC_LOGGER_NAME = "convert_sdk.diagnostics"
REDACTED = "<redacted>"

logger = logging.getLogger(DIAGNOSTIC_LOGGER_NAME)

SENSITIVE_KEY_PARTS = (
    "authorization",
    "config_data",
    "conversion_data",
    "cookie",
    "headers",
    "password",
    "payload",
    "raw",
    "request_attributes",
    "sdk_key",
    "secret",
    "token",
    "visitor_attributes",
    "visitor_id",
    "visitor_properties",
)


def log_diagnostic_event(
    event_name: str,
    *,
    level: int = logging.DEBUG,
    **details: object,
) -> None:
    """Emit an event-oriented diagnostic log record if diagnostics are enabled."""

    if not logger.isEnabledFor(level):
        return

    safe_details = redact_diagnostic_details(details)
    logger.log(
        level,
        "convert_sdk.%s",
        event_name,
        extra={
            "sdk_event": event_name,
            "sdk_details": safe_details,
        },
    )


def redact_diagnostic_details(details: Mapping[str, object]) -> Mapping[str, object]:
    """Return a log-safe copy of diagnostic details."""

    safe_details: dict[str, object] = {}
    for key, value in details.items():
        safe_key, safe_value = _redact_item(str(key), value)
        safe_details[safe_key] = safe_value
    return safe_details


def config_source(config_data: object, sdk_key: str | None) -> str:
    """Return a safe config source label."""

    if config_data is not None:
        return "direct_config"
    if sdk_key:
        return "sdk_key"
    return "unknown"


def snapshot_entity_counts(snapshot: ConfigSnapshot) -> Mapping[str, int]:
    """Return safe aggregate counts for a loaded config snapshot."""

    return {
        "audiences": len(snapshot.audiences_by_key),
        "experiences": len(snapshot.experiences_by_key),
        "features": len(snapshot.features_by_key),
        "goals": len(snapshot.goals_by_key),
        "segments": len(snapshot.segments_by_key),
    }


def mapping_count(value: Mapping[str, Any] | None) -> int:
    """Return a safe count for request-scoped mapping data."""

    return len(value) if isinstance(value, Mapping) else 0


def _redact_item(key: str, value: object) -> tuple[str, object]:
    key_lower = key.lower()
    if key_lower == "visitor_id":
        return "visitor_ref", visitor_reference(str(value))
    if _is_sensitive_key(key_lower):
        return key, REDACTED
    return key, _redact_value(value)


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return redact_diagnostic_details(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return tuple(_redact_value(item) for item in value)
    return f"<{type(value).__name__}>"


def _is_sensitive_key(key: str) -> bool:
    if key in {"transport", "transport_config"}:
        return True
    return any(part in key for part in SENSITIVE_KEY_PARTS)
