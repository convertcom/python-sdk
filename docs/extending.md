# Extending the SDK

The SDK is built around a small set of **extension seams** — `@runtime_checkable`
`typing.Protocol`s that let you swap the SDK's I/O boundaries for your own
implementations without subclassing or monkey-patching. This is the Python end
of the hybrid-injection contract (Story 4.4).

There are exactly three Protocol seams, each with a default adapter the SDK uses
out of the box:

| Seam | Protocol (`src/convert_sdk/`) | Default adapter | Injected via |
|------|-------------------------------|-----------------|--------------|
| Transport | `ports/transport.py` → `Transport` | `adapters/transport/httpx_transport.py` | `Core(config, *, transport=...)` (keyword-only) |
| Storage | `ports/storage.py` → `DataStore` | `adapters/storage/in_memory.py` → `InMemoryDataStore` | `SDKConfig(data_store=...)` (a config **field**) |
| Event bus | `ports/event_bus.py` → `EventBus` | `adapters/events/in_process.py` | internal; observe via `Core.on(...)` |

> **There is no logger Protocol.** Logging is the standard-library `logging`
> seam — pass your own `logging.Logger` as `SDKConfig.logger`. The SDK does not
> define a logging port; stdlib logging is the seam by design.

## Where each seam is injected

The two injection points are deliberately different, and the difference is part
of the contract:

- **Transport** is a constructor argument on `Core`, and it is **keyword-only**:
  `Core(config, transport=my_transport)`.
- **Storage** is a **field on `SDKConfig`**, not a `Core` argument:
  `SDKConfig(data=..., data_store=my_store)`.

## A custom Transport

Because `Transport` is `@runtime_checkable`, any object with the right methods
satisfies it — no base class to inherit. A transport is also a context manager,
so the full method set is `fetch_config(config)`,
`send_tracking(payload, *, sdk_key)`, `close()`, and the `__enter__` /
`__exit__` pair. (The SDK calls these methods directly; implementing the context
manager methods is what makes `isinstance(obj, Transport)` return `True`.)

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from convert_sdk.ports.transport import Transport
from tests.docs_sample_config import SAMPLE_CONFIG

class InMemoryTransport:
    """Delivers tracking into a list instead of over the network."""
    def __init__(self):
        self.sent = []
    def fetch_config(self, config):
        return SAMPLE_CONFIG
    def send_tracking(self, payload, *, sdk_key):
        self.sent.append(payload)
    def close(self):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        self.close()
        return False

transport = InMemoryTransport()
# @runtime_checkable lets you assert duck-typed conformance:
assert isinstance(transport, Transport)

# transport= is KEYWORD-ONLY.
core = Core(SDKConfig(data=SAMPLE_CONFIG), transport=transport).initialize()
context = core.create_context("visitor-001")
context.track_conversion("purchase_completed")
core.flush()

assert transport.sent            # our transport handled delivery
_doc_custom_transport_used = bool(transport.sent)
core.close()
```

## A custom DataStore

Implement the `DataStore` Protocol — `get`, `set(key, value, ttl=None)`, `has`,
`delete` — to back visitor state with Redis, a database, or anything else. Inject
it through the `SDKConfig.data_store` **field**:

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from convert_sdk.ports.storage import DataStore
from tests.docs_sample_config import SAMPLE_CONFIG

class DictStore:
    def __init__(self):
        self._data = {}
        self.writes = 0
    def get(self, key):
        return self._data.get(key)
    def set(self, key, value, ttl=None):
        self._data[key] = value
        self.writes += 1
    def has(self, key):
        return key in self._data
    def delete(self, key):
        self._data.pop(key, None)

store = DictStore()
assert isinstance(store, DataStore)

# data_store is a CONFIG FIELD, not a Core argument.
core = Core(SDKConfig(data=SAMPLE_CONFIG, data_store=store)).initialize()
context = core.create_context("visitor-001")
context.set_segments({"loyalty_tier": "gold"})   # persists through the store

assert store.writes >= 1
_doc_custom_store_used = store.writes >= 1
core.close()
```

When `data_store` is left unset, the SDK uses `InMemoryDataStore` (the per-process
default). A configured store is honored as-is.

## Observing lifecycle events

You do not implement the `EventBus` Protocol directly — the SDK owns the bus.
You **observe** it through `Core.on`, registering handlers for `LifecycleEvent`
values (see [Queue control](queue-control.md) for the queue-release example).
Handlers receive `(payload, error=None)` and must not raise — a raising handler
is isolated and logged so it cannot break delivery.

## Public API this guide relies on

- Protocol seams: `convert_sdk.ports.transport.Transport`,
  `convert_sdk.ports.storage.DataStore`, `convert_sdk.ports.event_bus.EventBus`
  (all `@runtime_checkable`)
- Injection: `Core(config, *, transport=...)` (keyword-only) and
  `SDKConfig(data_store=...)` (config field)
- Logging seam: `SDKConfig.logger` (a stdlib `logging.Logger`) — no Protocol
- Default adapters: `InMemoryDataStore`, the `httpx` transport, the in-process
  event bus
