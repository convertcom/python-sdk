# Extending the SDK

The SDK is built around three extension points, each defined as a `Protocol` in
`src/convert_sdk/ports/`. You supply custom implementations through `Core`'s
constructor keyword arguments or through `SDKConfig`.

Relevant source files:

- [`src/convert_sdk/ports/transport.py`](../src/convert_sdk/ports/transport.py) —
  `Transport`, `ConfigRequest`, `TrackingRequest`
- [`src/convert_sdk/ports/storage.py`](../src/convert_sdk/ports/storage.py) —
  `DataStore`
- [`src/convert_sdk/ports/event_bus.py`](../src/convert_sdk/ports/event_bus.py) —
  `EventBus`, `EventHandler`
- [`src/convert_sdk/adapters/transport/httpx_transport.py`](../src/convert_sdk/adapters/transport/httpx_transport.py) —
  built-in `HttpxTransport`
- [`src/convert_sdk/adapters/storage/in_memory.py`](../src/convert_sdk/adapters/storage/in_memory.py) —
  built-in `InMemoryDataStore`

## Substituting the transport

Implement the `Transport` protocol to replace how the SDK fetches config and
delivers tracking events. Common reasons: async HTTP, mTLS, proxy routing, or
stubbing in integration tests.

```python
from typing import Any, Mapping

from convert_sdk import Core, SDKConfig
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest, Transport


class StubTransport:
    """Test transport that returns canned responses."""

    def __init__(self, config_payload: Mapping[str, Any]) -> None:
        self._config = config_payload

    def fetch_config(self, request: ConfigRequest) -> Mapping[str, Any]:
        return self._config

    def send_tracking(self, request: TrackingRequest) -> Mapping[str, Any]:
        return {}


stub = StubTransport(config_payload={
    "account_id": "1001",
    "project": {"id": "2002", "name": "Test"},
    "experiences": [],
    "features": [],
    "goals": [],
})

core = Core(
    SDKConfig(sdk_key="test-key"),
    transport=stub,
)
```

The `Transport` protocol is structural (no base class required). Your class just
needs to implement `fetch_config()` and `send_tracking()` with the matching
signatures.

### ConfigRequest fields

| Field | Type | Description |
|-------|------|-------------|
| `sdk_key` | `str` | The project SDK key |
| `sdk_key_secret` | `str \| None` | Optional HMAC secret |
| `environment` | `str \| None` | Environment filter |
| `transport` | `TransportConfig` | Endpoint and timeout settings |

### TrackingRequest fields

| Field | Type | Description |
|-------|------|-------------|
| `sdk_key` | `str \| None` | The project SDK key, if available |
| `sdk_key_secret` | `str \| None` | Optional HMAC secret |
| `account_id` | `str \| None` | From config snapshot |
| `project_id` | `str \| None` | From config snapshot |
| `payload` | `Mapping[str, Any]` | Serialized tracking payload |
| `transport` | `TransportConfig` | Endpoint and timeout settings |

## Substituting the data store

Implement `DataStore` to persist visitor state and goal dedup records across
process restarts (e.g. Redis, Postgres, Memcache).

`ContextState` is a frozen dataclass exposed at `convert_sdk.domain.context_state`.
It is not part of the public top-level export — treat it as a stable internal
type that custom `DataStore` implementations need to construct and inspect. You
are responsible for choosing a serialization format; the snippet below uses
`json` over `dataclasses.asdict()` for clarity, but Pickle, MessagePack, or any
schema you control work equally well.

```python
import json
from dataclasses import asdict

from convert_sdk import Core, SDKConfig, DataStore
from convert_sdk.domain.context_state import ContextState


class RedisDataStore:
    """Example: Redis-backed visitor state store."""

    def __init__(self, redis_client) -> None:
        self._redis = redis_client

    def load_context_state(self, visitor_id: str) -> ContextState | None:
        raw = self._redis.get(f"ctx:{visitor_id}")
        if raw is None:
            return None
        fields = json.loads(raw)
        return ContextState.create(
            visitor_id=fields["visitor_id"],
            visitor_attributes=fields.get("visitor_attributes") or {},
            visitor_properties=fields.get("visitor_properties") or {},
            default_segments=fields.get("default_segments") or (),
        )

    def save_context_state(self, state: ContextState) -> None:
        self._redis.set(
            f"ctx:{state.visitor_id}",
            json.dumps(
                {
                    "visitor_id": state.visitor_id,
                    "visitor_attributes": dict(state.visitor_attributes),
                    "visitor_properties": dict(state.visitor_properties),
                    "default_segments": list(state.default_segments),
                }
            ),
        )

    def has_tracked_goal(self, visitor_id: str, goal_id: str) -> bool:
        return bool(self._redis.sismember(f"goals:{visitor_id}", goal_id))

    def mark_tracked_goal(self, visitor_id: str, goal_id: str) -> None:
        self._redis.sadd(f"goals:{visitor_id}", goal_id)


core = Core(
    SDKConfig(config_data=project_config),
    data_store=RedisDataStore(redis_client=my_redis),
)
```

Note: `asdict()` works on `ContextState` because it is a frozen dataclass, but
its `Mapping` fields come back as plain `dict`s — this is what the snippet
above relies on. Use `ContextState.create(...)` (not the bare constructor) to
re-hydrate from external storage so frozen-mapping invariants are enforced.

The built-in `InMemoryDataStore` is thread-safe but process-local. Goal
deduplication state resets on process restart with the default store.

### DataStore protocol

`ContextState` lives at `convert_sdk.domain.context_state`. It is not in the
top-level public export, but custom `DataStore` implementations must accept and
return values of this type.

| Method | Signature | Description |
|--------|-----------|-------------|
| `load_context_state` | `(visitor_id: str) -> ContextState \| None` | Return stored state or `None` |
| `save_context_state` | `(state: ContextState) -> None` | Persist latest state |
| `has_tracked_goal` | `(visitor_id: str, goal_id: str) -> bool` | Check dedup record |
| `mark_tracked_goal` | `(visitor_id: str, goal_id: str) -> None` | Write dedup record |

## Substituting the logging

The SDK uses Python's stdlib `logging` module throughout. There is no SDK-level
logging abstraction to replace. To redirect diagnostic output:

- Use `logging.getLogger("convert_sdk.diagnostics")` for evaluation/tracking
  diagnostic events
- Use `logging.getLogger("convert_sdk.tracking")` for delivery-level warnings

```python
import logging

# silence all SDK diagnostics in production
logging.getLogger("convert_sdk.diagnostics").setLevel(logging.WARNING)

# capture tracking failures in your alerting system
handler = MyAlertingHandler()
logging.getLogger("convert_sdk.tracking").addHandler(handler)
```

To attach structured metadata to your log aggregator, configure a custom
`logging.Formatter` that reads `record.sdk_event` and `record.sdk_details`:

```python
class SDKLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        sdk_event = getattr(record, "sdk_event", "")
        sdk_details = getattr(record, "sdk_details", {})
        return f"{sdk_event} {sdk_details}"
```

## Testing with custom adapters

The most common use of the extension points is in tests: supply a `StubTransport`
with canned config payloads to avoid network calls, and use a fresh
`InMemoryDataStore` per test to isolate deduplication state:

```python
from convert_sdk import Core, SDKConfig, InMemoryDataStore
from convert_sdk.ports.transport import ConfigRequest, TrackingRequest


class CannedTransport:
    def __init__(self, payload):
        self._payload = payload

    def fetch_config(self, request: ConfigRequest):
        return self._payload

    def send_tracking(self, request: TrackingRequest):
        return {}


def make_test_core(config_payload):
    return Core(
        SDKConfig(sdk_key="test-key"),
        transport=CannedTransport(config_payload),
        data_store=InMemoryDataStore(),
    )
```

## What to read next

- [Initialization](initialization.md) — `SDKConfig`, `TransportConfig`, `TrackingConfig`
- [Queue control](queue-control.md) — lifecycle events as an alternative to subclassing
- [Debugging](debugging.md) — diagnostic logging configuration
