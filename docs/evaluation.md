# Evaluation

Once a `Core` is initialized you create a visitor-scoped `Context` and evaluate
experiences and features. Evaluation is fully local and deterministic — it reads
only the loaded immutable config snapshot plus the visitor's state and performs
**no network I/O**. Normal misses return `None` (or an empty typed result); the
SDK never raises for an ordinary no-match.

> The runnable samples import `SAMPLE_CONFIG` from the docs fixture. Substitute
> your own config in your application.

## Creating a visitor context

`create_context` binds a visitor identity (and optional visitor attributes) to
the current config snapshot. Attributes are copied defensively, so later
mutations to the dict you pass never affect the context.

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context(
    "visitor-001",
    visitor_attributes={"country": "US", "plan": "pro"},
)
core.close()
```

Keep and reuse the returned `context` to evaluate the same visitor repeatedly;
the SDK does not cache contexts for you.

## Experience evaluation

`run_experience` returns a typed `ExperienceResult` when the visitor qualifies
and buckets into a variation, or `None` for any normal miss. `run_experiences`
evaluates every applicable experience at once.

```python  # doctest: run
from convert_sdk import Core, SDKConfig, ExperienceResult
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

result = context.run_experience("checkout-experiment")
if result is not None:
    assert isinstance(result, ExperienceResult)
    print(result.experience_key, result.variation_key, result.variation_id)

# Evaluate all applicable experiences:
for r in context.run_experiences():
    print(r.experience_key, "->", r.variation_key)

# Expose the bucketed variation for the docs drift guard.
_doc_variation_key = result.variation_key if result else None
core.close()
```

Overlay request-time attributes for a single call without mutating the stored
context:

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001", visitor_attributes={"country": "US"})

# The overlay applies to THIS call only; context.visitor_attributes is unchanged.
result = context.run_experience("checkout-experiment", attributes={"country": "DE"})
assert context.visitor_attributes["country"] == "US"
core.close()
```

## Feature evaluation

`run_feature` resolves a feature flag and its typed variables for the visitor.
It reads the feature change from the visitor's selected variation and casts each
variable to the feature's declared type. It returns a typed `FeatureResult` when
the feature is enabled, or `None` for a normal miss.

```python  # doctest: run
from convert_sdk import Core, SDKConfig, FeatureStatus
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

feature = context.run_feature("checkout-banner")
if feature is not None:
    assert feature.status is FeatureStatus.ENABLED
    assert isinstance(feature.variables["enabled"], bool)
    assert isinstance(feature.variables["max_items"], int)
    assert isinstance(feature.variables["headline"], str)

# Resolve all applicable features at once:
for f in context.run_features():
    print(f.feature_key, f.variables)
core.close()
```

## Segments

Default segments feed reporting and conversion attribution. `set_segments`
persistently associates default segments with the visitor (kept strictly
separate from `visitor_attributes`). `run_custom_segments` evaluates named
segment rules against the visitor and records the matched IDs, returning a typed
`CustomSegmentsResult`.

```python  # doctest: run
from convert_sdk import Core, SDKConfig, CustomSegmentsResult
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

context.set_segments({"loyalty_tier": "gold"})

# rule_data is an ephemeral per-call overlay; it is never written back.
result = context.run_custom_segments(["us-visitors"], {"country": "US"})
assert isinstance(result, CustomSegmentsResult)
assert result.matched is True
assert "s_us" in result.matched_segment_ids

# A non-match is a typed empty result, not an exception:
miss = context.run_custom_segments(["us-visitors"], {"country": "DE"})
assert miss.matched is False
assert miss.matched_segment_ids == ()
core.close()
```

## Public API this guide relies on

- `Core.create_context(visitor_id, visitor_attributes=...)`
- `Context.run_experience(key, attributes=...)` → `ExperienceResult | None`
- `Context.run_experiences()` → iterable of `ExperienceResult`
- `Context.run_feature(key)` → `FeatureResult | None`; `Context.run_features()`
- `Context.set_segments(dict)`; `Context.run_custom_segments(keys, rule_data=...)`
  → `CustomSegmentsResult`
- Typed results: `ExperienceResult`, `FeatureResult`, `FeatureStatus`,
  `CustomSegmentsResult`
