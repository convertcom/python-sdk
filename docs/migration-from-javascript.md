# Migrating from the JavaScript SDK

If you know the Convert FullStack **JavaScript** SDK, the Python SDK will feel
conceptually familiar — same bucketing, same feature resolution, same
queue-and-flush tracking model, the same cross-SDK diagnostic reason codes. But
it is **not a syntax port**. The Python SDK is deliberately Pythonic, and a few
shapes differ on purpose. This guide maps the concepts and then calls out the
differences so you do not fight the grain of the language.

## Concept map

| JavaScript SDK | Python SDK | Notes |
|----------------|------------|-------|
| `runExperience(key)` | `context.run_experience(key)` | Returns a typed `ExperienceResult` or `None`. |
| `runExperiences()` | `context.run_experiences()` | Iterable of typed results. |
| `runFeature(key)` | `context.run_feature(key)` | Returns a typed `FeatureResult` or `None`; variables are cast to declared types. |
| `runFeatures()` | `context.run_features()` | Iterable of typed results. |
| `setDefaultSegments(...)` | `context.set_segments({...})` | Persists default segments, kept separate from visitor attributes. |
| `runCustomSegments(...)` | `context.run_custom_segments(keys, rule_data=...)` | Returns a typed `CustomSegmentsResult`. |
| queue control / `onQueueRelease` | `core.flush()` + `Core.on(LifecycleEvent.API_QUEUE_RELEASED, ...)` | Same enqueue-then-release model. |
| lifecycle events | `LifecycleEvent` + `Core.on(event, handler)` | Handlers receive `(payload, error=None)`. |

## The same model in Python

This is the JS mental model — initialize, get a visitor context, run an
experience — expressed Pythonically against the offline docs fixture:

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

# JS: const sdk = new ConvertSDK({ data }); await sdk.onReady();
core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()

# JS: const context = sdk.createContext("visitor-001");
context = core.create_context("visitor-001")

# JS: const result = context.runExperience("checkout-experiment");
result = context.run_experience("checkout-experiment")
_doc_js_variation = result.variation_key if result else None
assert _doc_js_variation in {"control", "treatment", None}

# JS: context.setDefaultSegments({ tier: "gold" });
context.set_segments({"tier": "gold"})

# JS: context.runCustomSegments(["us-visitors"], { country: "US" });
seg = context.run_custom_segments(["us-visitors"], {"country": "US"})
assert seg.matched is True

core.close()
```

## Deliberate Pythonic differences

These are intentional — embrace them rather than emulating JS idioms:

- **snake_case, not camelCase.** Methods and keyword arguments use
  `run_experience`, `set_segments`, `force_multiple`, `auto_flush_interval_ms`.
  This is PEP 8, not an oversight.
- **`Context` is a mutator, not a builder.** In JS you often chain a builder.
  In Python the `Context` carries visitor state and you mutate it in place
  (`context.set_attributes(...)`, `context.set_segments(...)`); each mutation
  rebinds an immutable internal state and persists through the configured store.
  For one-off overlays, pass `attributes=` to a single call instead of mutating.
- **Typed dataclasses, not plain objects.** Results are frozen dataclasses with
  named fields (`ExperienceResult.variation_key`, `FeatureResult.variables`,
  `ConversionResult.status`) and closed enums (`FeatureStatus`,
  `ConversionStatus`, `DiagnosticReason`). Let your IDE follow the type — there
  is no untyped result bag.
- **Protocols for extension, not classes/callbacks.** Where JS takes adapter
  objects or callbacks, Python uses `@runtime_checkable` `typing.Protocol`s for
  the transport, storage, and event-bus seams. Implement the protocol's methods
  (no base class) and inject — `Core(config, *, transport=...)` and
  `SDKConfig(data_store=...)`. See [Extending](extending.md).
- **Normal misses return `None` / empty typed results, never exceptions.** Same
  as the JS "no result" semantics, expressed as `Optional[...]` returns.

## Evidence of behavioral equivalence

The SDKs are kept in parity deliberately:

- The **parity test layout** (Story 3.5) exercises the Python SDK against the
  shared cross-SDK fixtures, so bucketing and resolution match the JS SDK
  deterministically (default MurmurHash seed `9999`).
- The **cross-SDK diagnostic contract** (Story 4.3) shares the closed
  `DiagnosticReason` vocabulary, so a Python diagnosis correlates with a JS one.
  See [Debugging](debugging.md).

So when you migrate, the *answers* (which variation, which variables, whether a
conversion deduplicates) match the JS SDK — only the *spelling* is Pythonic.

## Where to go next

- [Initialization](initialization.md), [Evaluation](evaluation.md),
  [Tracking](tracking.md), [Queue control](queue-control.md)
- [Extending](extending.md) — the Protocol seams in place of JS adapters
- [Debugging](debugging.md) — the shared diagnostic reason codes
