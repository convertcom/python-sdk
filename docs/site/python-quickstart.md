# Python Quickstart

Install the Convert Python SDK, configure your SDK key, and run your first
experience evaluation and conversion track in under a minute.

The SDK is framework-agnostic: it works in Django, Flask, FastAPI, Celery,
AWS Lambda, plain CLI scripts, or any Python `>=3.9` runtime. There is no
JavaScript runtime or web framework dependency.

## 1. Install

```bash
pip install convert-python-sdk
```

## 2. Full working example

```python
import os

from convert_sdk import (
    Core,
    GoalNotFoundError,
    RefreshConfig,
    SDKConfig,
)


def main() -> None:
    core = Core(
        SDKConfig(
            sdk_key=os.environ["CONVERT_SDK_KEY"],
            sdk_key_secret=os.getenv("CONVERT_SDK_KEY_SECRET"),
            environment="production",
            refresh=RefreshConfig(interval_seconds=300.0),
        )
    )
    assert core.is_ready

    context = core.create_context(
        "user-unique-id",
        {"country": "US", "language": "en", "device": "mobile"},
    )

    experience = context.run_experience(
        "experience-key",
        location_attributes={"screen": "pricing"},
    )
    if experience is not None:
        print("Experience:", experience.experience_key,
              "Variation:", experience.variation_key)

    feature = context.run_feature("feature-key")
    if feature is not None:
        print("Feature:", feature.status.value, dict(feature.variables))

    try:
        context.track_conversion(
            "goal-key",
            conversion_data={
                "revenue": 10.3,
                "products_count": 2,
                "order_id": "order-unique-id",
            },
            force_multiple_transactions=False,
        )
    except GoalNotFoundError as exc:
        print("Goal not found:", exc.code)

    context.release_queues(reason="end_of_request")
    core.close()


if __name__ == "__main__":
    main()
```

## Key points

- **Synchronous by default.** `Core(...)` blocks during config fetch; once
  it returns, `core.is_ready` is `True` and you can create contexts.
- **One `Core` per application.** Treat it as a singleton; create it at
  startup and reuse across requests. Per-request work happens on `Context`.
- **`Context` is per-visitor.** Reuse a single context for all evaluations
  within one request; do not create a new one per call.
- **Tracking is queued.** `track_conversion()` queues events; nothing leaves
  the process until you call `context.release_queues()`. Flush at end of
  request, end of task, or end of script.
- **Background refresh is opt-in.** Pass `RefreshConfig` to `SDKConfig` to
  refresh config every N seconds in long-running services. The default is
  no background activity.
- **Direct config supported.** Replace `sdk_key=...` with
  `config_data={...}` to skip the network and run against an inline
  payload — ideal for local dev and tests.

## Next steps

- [Installation](python-installation.md) — supported Python versions and
  optional install groups
- [Initialization](python-initialization.md) — SDK key vs direct config,
  readiness, lifecycle
- [Configuration Options](python-configuration.md) — full
  `SDKConfig` / `TransportConfig` / `TrackingConfig` / `RefreshConfig`
  field reference
- [Code Examples](python-code-examples.md) — running experiences,
  features, segments, tracking, and queue control
- [Return Types & DTOs](python-return-types.md) — every typed result
  the SDK returns
- [Segments Manager](python-segments-manager.md) — default and custom
  segments on the visitor context
