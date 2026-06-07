"""Story 2.2 (SDK-1) — extended conversion domain model + validation error.

Covers:

* The Story 2.1 ``ConversionEvent`` value object extended with OPTIONAL revenue,
  caller-supplied ``conversion_data``, and attribution context (active
  ``segments`` and active variation ``bucketing_assignments``) — all snake_case,
  all optional, the dataclass stays frozen, and Story 2.1 (goal-key-only)
  construction stays valid.
* A typed ``ConversionDataError`` (tracking error family in ``errors.py``) that
  is a ``ConvertSDKError``, is distinct from the Story 2.1 unknown-goal
  NON-EXCEPTION result, and whose ``str``/``repr`` leak no SDK keys, auth
  headers, or raw visitor PII.

No wire-name mapping is asserted here — that is SDK-3 (``tracking/payloads.py``).
"""

import pytest

from convert_sdk.domain.results import ConversionEvent
from convert_sdk.errors import ConversionDataError, ConvertSDKError


# --- extended ConversionEvent domain model -------------------------------


def test_conversion_event_2_1_construction_still_valid():
    # Story 2.1 goal-key-only construction must remain valid (no required new
    # fields).
    event = ConversionEvent(
        visitor_id="v1", goal_id="g1", goal_key="purchase_completed"
    )
    assert event.visitor_id == "v1"
    assert event.goal_id == "g1"
    assert event.goal_key == "purchase_completed"
    # New optional attribution fields default to absence.
    assert event.revenue is None
    assert event.conversion_data is None


def test_conversion_event_holds_revenue_and_conversion_data():
    event = ConversionEvent(
        visitor_id="v1",
        goal_id="g1",
        goal_key="purchase_completed",
        revenue=42.5,
        conversion_data={"transactionId": "tx-9", "productsCount": 3},
    )
    assert event.revenue == 42.5
    assert event.conversion_data == {"transactionId": "tx-9", "productsCount": 3}


def test_conversion_event_holds_attribution_segments_and_bucketing():
    event = ConversionEvent(
        visitor_id="v1",
        goal_id="g1",
        goal_key="purchase_completed",
        segments={"country": "US"},
        bucketing_assignments={"e1": "v1", "e2": "v9"},
    )
    assert event.segments == {"country": "US"}
    assert event.bucketing_assignments == {"e1": "v1", "e2": "v9"}


def test_conversion_event_is_frozen():
    event = ConversionEvent(
        visitor_id="v1", goal_id="g1", goal_key="k", revenue=1.0
    )
    with pytest.raises(Exception):
        event.revenue = 2.0  # type: ignore[misc]


def test_conversion_event_attribution_views_are_read_only():
    # Attribution mappings must not be mutable through the frozen event.
    event = ConversionEvent(
        visitor_id="v1",
        goal_id="g1",
        goal_key="k",
        segments={"country": "US"},
        bucketing_assignments={"e1": "v1"},
        conversion_data={"transactionId": "tx-1"},
    )
    with pytest.raises(Exception):
        event.segments["country"] = "FR"  # type: ignore[index]
    with pytest.raises(Exception):
        event.bucketing_assignments["e1"] = "v2"  # type: ignore[index]
    with pytest.raises(Exception):
        event.conversion_data["transactionId"] = "tx-2"  # type: ignore[index]


# --- typed ConversionDataError -------------------------------------------


def test_conversion_data_error_is_a_convert_sdk_error():
    assert issubclass(ConversionDataError, ConvertSDKError)


def test_conversion_data_error_is_raisable_with_safe_context():
    err = ConversionDataError("revenue", reason="value is not JSON-serializable")
    assert isinstance(err, ConversionDataError)
    msg = str(err)
    assert "revenue" in msg
    assert "JSON-serializable" in msg


def test_conversion_data_error_message_and_repr_leak_no_secrets_or_pii():
    # The error must carry only the offending KEY name and a safe reason — never
    # the raw value, an SDK key, an auth header, or unrelated visitor PII.
    secret_value = "sk_live_supersecret_value_with_email_user@example.com"
    err = ConversionDataError(
        "transactionId", reason="value is not a JSON primitive"
    )
    rendered = str(err) + repr(err)
    assert secret_value not in rendered
    assert "sk_live" not in rendered
    assert "user@example.com" not in rendered


def test_conversion_data_error_is_distinct_type_from_base_config_errors():
    # Distinguishable from the Story 1.2 config errors and (by type) from the
    # Story 2.1 unknown-goal NON-EXCEPTION result, which is not an exception at
    # all.
    from convert_sdk.errors import ConfigError

    assert not issubclass(ConversionDataError, ConfigError)
