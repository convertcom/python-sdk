# Support workflows

This guide is for the person answering "why didn't this visitor see the
experiment?" or "why wasn't this conversion recorded?" It shows how to combine
the SDK's typed diagnostics, lifecycle observation, and config-entity lookups
into a repeatable triage routine — and how that ties into keeping cross-SDK
parity coverage current (FR52, FR57).

## A triage routine for a "missing variation" report

When a visitor reports they did not get bucketed, reproduce their context and
ask the diagnostic surface (see [Debugging](debugging.md)) for the closed reason
instead of guessing:

```python  # doctest: run
from convert_sdk import Core, SDKConfig, DiagnosticReason
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()

def triage_experience(visitor_id, attributes, experience_key):
    """Return the closed reason a visitor did/did not bucket — for support."""
    context = core.create_context(visitor_id, visitor_attributes=attributes)
    diag = context.diagnose_experience(experience_key)
    return diag.reason

# A real bucketing succeeds:
assert triage_experience("v-1", {"country": "US"}, "checkout-experiment") is (
    DiagnosticReason.RESOLVED
)
# A typo in the experience key is immediately distinguishable from an audience miss:
assert triage_experience("v-1", {"country": "US"}, "chekout-typo") is (
    DiagnosticReason.EXPERIENCE_NOT_FOUND
)
core.close()
```

The closed `DiagnosticReason` lets you route the ticket precisely:
`EXPERIENCE_NOT_FOUND` is a config/key problem, `AUDIENCE_MISMATCH` is a
targeting question, `RESOLVED` means the SDK did bucket and the problem is
elsewhere (e.g. the integration never read the result).

## Confirming a goal exists before chasing tracking

A "conversion not recorded" report is frequently a goal-key mismatch. Diagnose
the goal and inspect the config entity directly rather than reading logs:

```python  # doctest: run
from convert_sdk import Core, SDKConfig, DiagnosticReason
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("v-1")

# Is the goal even in the loaded config?
if context.diagnose_goal("purchase_completed").reason is DiagnosticReason.RESOLVED:
    # The goal exists; the entity lookup confirms its identity for the ticket.
    goal = context.get_config_entity("goals", "purchase_completed")
    assert goal is not None
core.close()
```

## Observing delivery for live triage

To confirm queued conversions are actually being released, attach a lightweight
observer to `LifecycleEvent.API_QUEUE_RELEASED` (see [Queue control](queue-control.md)).
Handlers receive `(payload, error=None)`, so a non-`None` `error` tells you a
release attempt failed — exactly the signal a support engineer needs.

## Keeping parity coverage current

The diagnostic reason codes are shared across the Convert SDKs deliberately, so
a Python diagnosis correlates with the JavaScript SDK's. When you add or change
behavior, mirror it in the parity test layout (Story 3.5) and the cross-SDK
diagnostic contract (Story 4.3) so support answers stay consistent across
languages. The migration guides ([from REST](migration-from-rest.md),
[from JavaScript](migration-from-javascript.md)) are the customer-facing side of
the same parity discipline.

## Public API this guide relies on

- `Context.diagnose_experience` / `diagnose_goal` and `DiagnosticReason`
- `Context.get_config_entity(entity_type, key)` for entity confirmation
- `Core.on(LifecycleEvent.API_QUEUE_RELEASED, handler)` for delivery observation
