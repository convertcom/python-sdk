# Debugging

When an evaluation or tracking call returns `None` (or an empty result), you
often want to know **why** without resorting to `try`/`except` or guesswork. The
SDK exposes a typed **diagnostic surface** that answers "what happened?" with a
closed, machine-readable reason code — the Python end of the cross-SDK
diagnostic contract (Story 4.3).

> This surface is **additive and partial**: it explains the most common
> no-result outcomes. It does not replace the typed results from the evaluation
> calls — `run_experience` / `run_feature` / `track_conversion` keep their
> existing return shapes unchanged.

## The diagnose_* methods

Each evaluation surface has a paired `diagnose_*` method that returns a frozen,
typed diagnostic instead of `None`:

| Method | Returns | Resolves against |
|--------|---------|------------------|
| `diagnose_experience(key)` | `ExperienceDiagnostic` | experiences |
| `diagnose_feature(key)` | `FeatureDiagnostic` | features |
| `diagnose_goal(key)` | `GoalDiagnostic` | goals |
| `diagnose_entity(entity_type, key)` | `EntityDiagnostic` | any config entity |

Every diagnostic carries:

- `reason` — a `DiagnosticReason` (a closed `str` enum, see below)
- `message` — a short, human-readable explanation
- `details` — a read-only, redaction-safe mapping (never raw attributes, keys,
  or PII)
- `resolved` — a convenience boolean, `True` when `reason is DiagnosticReason.RESOLVED`

```python  # doctest: run
from convert_sdk import Core, SDKConfig, DiagnosticReason, ExperienceDiagnostic
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001", visitor_attributes={"country": "US"})

# A resolved experience:
diag = context.diagnose_experience("checkout-experiment")
assert isinstance(diag, ExperienceDiagnostic)
assert diag.resolved is True
assert diag.reason is DiagnosticReason.RESOLVED
_doc_diag_resolved = diag.reason.value          # "resolved"

# A miss carries the specific closed reason:
miss = context.diagnose_experience("does-not-exist")
assert miss.resolved is False
assert miss.reason is DiagnosticReason.EXPERIENCE_NOT_FOUND
_doc_diag_miss = miss.reason.value              # "experience_not_found"

core.close()
```

## The closed reason vocabulary

`DiagnosticReason` is a closed `str` enum — exactly these eight codes, identical
to the values the Convert SDKs share so diagnostics correlate across languages:

| `DiagnosticReason` | Value |
|--------------------|-------|
| `RESOLVED` | `"resolved"` |
| `AUDIENCE_MISMATCH` | `"audience_mismatch"` |
| `EXPERIENCE_NOT_FOUND` | `"experience_not_found"` |
| `FEATURE_NOT_IN_SELECTED_VARIATIONS` | `"feature_not_in_selected_variations"` |
| `FEATURE_NOT_FOUND` | `"feature_not_found"` |
| `GOAL_NOT_FOUND` | `"goal_not_found"` |
| `ENTITY_NOT_FOUND` | `"entity_not_found"` |
| `PROJECT_MAPPING_REQUIRED` | `"project_mapping_required"` |

Because it subclasses `str`, you can compare against the value directly
(`diag.reason == "resolved"`) or against the enum member.

```python  # doctest: run
from convert_sdk import Core, SDKConfig, DiagnosticReason
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001")

# Goals and entities diagnose the same way:
assert context.diagnose_goal("purchase_completed").reason is DiagnosticReason.RESOLVED
assert context.diagnose_goal("ghost").reason is DiagnosticReason.GOAL_NOT_FOUND
assert (
    context.diagnose_entity("experiences", "nope").reason
    is DiagnosticReason.ENTITY_NOT_FOUND
)
core.close()
```

## The log seam is redaction-safe

The same diagnostic is mirrored to the SDK's logging seam (Story 4.1) with the
**identical closed reason code**, so logs and returned diagnostics agree. The
logged fields are limited to the redaction-safe set — `reason`, `environment`,
`bucket_value`, `variation_key`, and a **hashed** `visitor` reference produced
by `fingerprint_visitor`. The raw visitor id is never logged, and `details`
carries only allowlist-safe values. This is how you correlate a production miss
in your logs without leaking PII.

```python  # doctest: run
from convert_sdk import Core, SDKConfig
from tests.docs_sample_config import SAMPLE_CONFIG

core = Core(SDKConfig(data=SAMPLE_CONFIG)).initialize()
context = core.create_context("visitor-001", visitor_attributes={"country": "US"})

diag = context.diagnose_experience("checkout-experiment")
# details exposes only redaction-safe fields — including a hashed visitor_ref,
# never the raw visitor id.
assert "visitor_ref" in diag.details
assert diag.details["visitor_ref"] != "visitor-001"
core.close()
```

## Public API this guide relies on

- `Context.diagnose_experience(key)` → `ExperienceDiagnostic`
- `Context.diagnose_feature(key)` → `FeatureDiagnostic`
- `Context.diagnose_goal(key)` → `GoalDiagnostic`
- `Context.diagnose_entity(entity_type, key)` → `EntityDiagnostic`
- `DiagnosticReason` (closed 8-value enum), and the frozen diagnostic
  dataclasses with `.reason`, `.message`, `.details`, `.resolved`
- The hashed `visitor` reference (`fingerprint_visitor`) on the log seam
