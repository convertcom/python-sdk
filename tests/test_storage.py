from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from convert_sdk import Core, SDKConfig
from convert_sdk.domain.context_state import ContextState
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest

from test_context_creation import sample_config_payload


@dataclass
class RecordingTransport:
    tracking_requests: list[TrackingRequest] = field(default_factory=list)

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        raise AssertionError(f"fetch_config should not be called during this test: {request}")

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        self.tracking_requests.append(request)
        return {"accepted": True}


@dataclass
class RecordingDataStore:
    loaded_visitor_ids: list[str] = field(default_factory=list)
    saved_states: list[ContextState] = field(default_factory=list)
    dedupe_checks: list[tuple[str, str]] = field(default_factory=list)
    marked_goals: list[tuple[str, str]] = field(default_factory=list)
    _states: dict[str, ContextState] = field(default_factory=dict)
    _tracked_goals: set[tuple[str, str]] = field(default_factory=set)

    def load_context_state(self, visitor_id: str) -> ContextState | None:
        self.loaded_visitor_ids.append(visitor_id)
        return self._states.get(visitor_id)

    def save_context_state(self, state: ContextState) -> None:
        self.saved_states.append(state)
        self._states[state.visitor_id] = state

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        key = (visitor_id, goal_id)
        self.dedupe_checks.append(key)
        return key in self._tracked_goals

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        key = (visitor_id, goal_id)
        self.marked_goals.append(key)
        self._tracked_goals.add(key)


def test_core_uses_a_custom_data_store_for_context_state_and_tracking_dedup() -> None:
    store = RecordingDataStore()
    transport = RecordingTransport()
    core = Core(
        SDKConfig(config_data=sample_config_payload()),
        transport=transport,
        data_store=store,
    )

    first = core.create_context("visitor-123", {"plan": "pro"})
    second = core.create_context("visitor-123")
    second.update_visitor_properties({"tier": "premium"})
    second.set_default_segments(["vip-users"])
    first_result = second.track_conversion("purchase")
    reloaded = core.create_context("visitor-123")

    assert first.visitor_attributes == {"plan": "pro"}
    assert second.visitor_attributes == {"plan": "pro"}
    assert second.visitor_properties == {"tier": "premium"}
    assert second.default_segments == ("vip-users",)
    assert first_result.duplicate_prevented is False

    prevented = second.track_conversion("purchase")

    assert prevented.duplicate_prevented is True
    assert reloaded.visitor_properties == {"tier": "premium"}
    assert reloaded.default_segments == ("vip-users",)
    assert store.loaded_visitor_ids == [
        "visitor-123",
        "visitor-123",
        "visitor-123",
    ]
    assert store.saved_states[0].visitor_attributes == {"plan": "pro"}
    assert store.saved_states[-1].visitor_properties == {"tier": "premium"}
    assert store.saved_states[-1].default_segments == ("vip-users",)
    assert store.dedupe_checks == [
        ("visitor-123", "5005"),
        ("visitor-123", "5005"),
    ]
    assert store.marked_goals == [("visitor-123", "5005")]
