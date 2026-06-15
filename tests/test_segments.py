"""Story 3.3 — custom-segment evaluation tests (SDK-3).

Covers the local custom-segment matcher (``evaluation/segments.py``) and the
public :meth:`convert_sdk.context.Context.run_custom_segments` surface (FR15).

Custom-segment evaluation is fully LOCAL and deterministic: it resolves named
``ConfigSegment`` entities from the immutable snapshot and matches each segment's
rule against the visitor's segment-rule input via the EXISTING Story 1.4 rule
engine (``evaluation/rules.py``). It performs NO network I/O. Matched segment IDs
are recorded into the DISTINCT default-segment state under a ``customSegments``
list (JS ``VisitorSegments`` parity), and the result is a TYPED non-exception
outcome (never a raw dict, never raising on a normal no-match).
"""

from __future__ import annotations

from convert_sdk import Context, Core, CustomSegmentsResult, SDKConfig
from convert_sdk.domain.config_snapshot import ConfigSnapshot
from convert_sdk.evaluation.segments import select_custom_segments


def _rule_country(value: str) -> dict:
    """A simple single-condition rule matching ``country == value``."""
    return {
        "OR": [
            {
                "AND": [
                    {
                        "OR_WHEN": [
                            {
                                "matching": {"match_type": "equals", "negated": False},
                                "key": "country",
                                "value": value,
                            }
                        ]
                    }
                ]
            }
        ]
    }


CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "segments": [
        {"id": "s_us", "key": "us-visitors", "rules": _rule_country("US")},
        {"id": "s_de", "key": "de-visitors", "rules": _rule_country("DE")},
        {"id": "s_all", "key": "everyone"},  # no rules → always matches
    ],
    "experiences": [],
}


def _snapshot() -> ConfigSnapshot:
    return ConfigSnapshot.from_normalized(CONFIG)


def _ready_core() -> Core:
    return Core(SDKConfig(data=CONFIG)).initialize()


# --- evaluation/segments.py local matcher -----------------------------------


def test_select_custom_segments_matches_segment_whose_rule_matches():
    matched = select_custom_segments(
        _snapshot(), ["us-visitors"], {"country": "US"}, existing_ids=[]
    )
    assert matched == ["s_us"]


def test_select_custom_segments_skips_non_matching_segment():
    matched = select_custom_segments(
        _snapshot(), ["us-visitors"], {"country": "DE"}, existing_ids=[]
    )
    assert matched == []


def test_select_custom_segments_unknown_key_is_safe_non_match():
    matched = select_custom_segments(
        _snapshot(), ["does-not-exist"], {"country": "US"}, existing_ids=[]
    )
    assert matched == []


def test_select_custom_segments_ruleless_segment_always_matches():
    # A segment with no rules matches unconditionally (JS parity: no rule → add).
    matched = select_custom_segments(
        _snapshot(), ["everyone"], {"country": "ZZ"}, existing_ids=[]
    )
    assert matched == ["s_all"]


def test_select_custom_segments_skips_already_recorded_ids():
    # Duplicate segment IDs are not re-added (JS parity: customSegments includes).
    matched = select_custom_segments(
        _snapshot(), ["us-visitors"], {"country": "US"}, existing_ids=["s_us"]
    )
    assert matched == []


def test_select_custom_segments_multiple_keys_records_each_match():
    matched = select_custom_segments(
        _snapshot(), ["us-visitors", "everyone"], {"country": "US"}, existing_ids=[]
    )
    assert set(matched) == {"s_us", "s_all"}


def test_select_custom_segments_latches_across_ordered_list():
    # JS/PHP parity (segments-manager.ts:100-121): once an earlier segment's rule
    # matches, the latch records SUBSEQUENT segments without re-evaluating their
    # own rules. A US visitor querying [us-visitors, de-visitors] gets BOTH ids
    # even though the DE rule does not match.
    matched = select_custom_segments(
        _snapshot(), ["us-visitors", "de-visitors"], {"country": "US"}, existing_ids=[]
    )
    assert matched == ["s_us", "s_de"]


def test_select_custom_segments_latch_does_not_engage_before_first_match():
    # Order matters: a LEADING non-matching segment does not latch. Querying
    # [de-visitors, us-visitors] as a US visitor skips de-visitors (DE rule fails)
    # and records only us-visitors once it matches.
    matched = select_custom_segments(
        _snapshot(), ["de-visitors", "us-visitors"], {"country": "US"}, existing_ids=[]
    )
    assert matched == ["s_us"]


# --- Context.run_custom_segments public surface -----------------------------


def test_run_custom_segments_returns_typed_result():
    core = _ready_core()
    ctx = core.create_context("v_a")
    result = ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    # TYPED non-exception result, never a raw dict.
    assert isinstance(result, CustomSegmentsResult)
    assert result.matched_segment_ids == ("s_us",)


def test_run_custom_segments_records_matched_ids_into_distinct_field():
    core = _ready_core()
    ctx = core.create_context("v_a")
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    # Matched IDs land under customSegments inside the DISTINCT default_segments
    # field — never in visitor_attributes.
    assert list(ctx.default_segments.get("customSegments", [])) == ["s_us"]
    assert dict(ctx.visitor_attributes) == {}


def test_run_custom_segments_no_match_returns_empty_typed_result():
    core = _ready_core()
    ctx = core.create_context("v_a")
    result = ctx.run_custom_segments(["us-visitors"], {"country": "DE"})
    # A normal no-match is a typed result with no matched ids — never raises,
    # never returns a raw dict.
    assert isinstance(result, CustomSegmentsResult)
    assert result.matched_segment_ids == ()
    assert "customSegments" not in dict(ctx.default_segments) or list(
        ctx.default_segments.get("customSegments", [])
    ) == []


def test_run_custom_segments_uses_persisted_rule_data_when_no_overlay():
    core = _ready_core()
    ctx = core.create_context("v_a", visitor_attributes={"country": "US"})
    # No per-call rule_data → falls back to persisted visitor attributes.
    result = ctx.run_custom_segments(["us-visitors"])
    assert result.matched_segment_ids == ("s_us",)


def test_run_custom_segments_rule_data_overlay_takes_precedence():
    core = _ready_core()
    ctx = core.create_context("v_a", visitor_attributes={"country": "DE"})
    # Per-call rule_data overrides persisted state for THIS call (request > persisted).
    result = ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    assert result.matched_segment_ids == ("s_us",)


def test_run_custom_segments_overlay_is_not_written_back_to_attributes():
    core = _ready_core()
    ctx = core.create_context("v_a", visitor_attributes={"country": "DE"})
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    # The ephemeral rule_data overlay is NEVER persisted into visitor_attributes
    # (AC #5); only matched segment IDs persist into the distinct field.
    assert dict(ctx.visitor_attributes) == {"country": "DE"}
    assert list(ctx.default_segments.get("customSegments", [])) == ["s_us"]


def test_run_custom_segments_does_not_re_add_duplicate_ids():
    core = _ready_core()
    ctx = core.create_context("v_a")
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    # A second matching call for the same segment does not duplicate the id.
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    assert list(ctx.default_segments.get("customSegments", [])) == ["s_us"]


def test_run_custom_segments_persists_through_store_and_rehydrates():
    class _RecordingStore:
        def __init__(self):
            self._d: dict = {}

        def get(self, key):
            return self._d.get(key)

        def set(self, key, value, ttl=None):
            self._d[key] = value

        def has(self, key):
            return key in self._d

        def delete(self, key):
            self._d.pop(key, None)

    store = _RecordingStore()
    core = Core(SDKConfig(data=CONFIG, data_store=store)).initialize()
    ctx = core.create_context("v_a")
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})

    # The matched custom segments persist and rehydrate on a fresh context.
    ctx2 = core.create_context("v_a")
    assert list(ctx2.default_segments.get("customSegments", [])) == ["s_us"]


def test_run_custom_segments_performs_no_network_io():
    # Custom-segment evaluation must be fully local — no transport/adapter
    # IMPORTS at all (network-free, FR15). Inspect actual import statements via
    # the AST so descriptive docstring words don't trip the assertion.
    import ast
    import inspect

    import convert_sdk.evaluation.segments as seg_mod

    tree = ast.parse(inspect.getsource(seg_mod))
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported_modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            imported_modules.extend(alias.name for alias in node.names)
    joined = " ".join(imported_modules)
    assert "httpx" not in joined
    assert "transport" not in joined
    assert "adapters" not in joined
    assert "tracking" not in joined

    core = _ready_core()
    ctx = core.create_context("v_a")
    # Evaluation succeeds without any transport (direct config, no network).
    result = ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    assert result.matched_segment_ids == ("s_us",)


def test_run_custom_segments_without_store_is_safe():
    core = Core(SDKConfig(data=CONFIG)).initialize()
    ctx = Context("v_a", core.current_config)
    result = ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    assert result.matched_segment_ids == ("s_us",)
    assert list(ctx.default_segments.get("customSegments", [])) == ["s_us"]


# --- Story 3.3 AC #4: FR25 determinism under segment association ------------

_EVAL_CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "segments": [
        {"id": "s_us", "key": "us-visitors", "rules": _rule_country("US")},
    ],
    "experiences": [
        {
            "id": "e2",
            "key": "us-experience",
            "audiences": ["a1"],
            "variations": [{"id": "v3", "key": "only", "traffic_allocation": 100.0}],
        }
    ],
    "audiences": [
        {"id": "a1", "key": "us-only", "rules": _rule_country("US")},
    ],
}


def _eval_core() -> Core:
    return Core(SDKConfig(data=_EVAL_CONFIG)).initialize()


def test_set_segments_does_not_perturb_bucketed_variation():
    core = _eval_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    before = ctx.run_experience("us-experience")
    # Associating default segments feeds reporting only — it must NOT change the
    # deterministic bucketed variation (bucketing keyed on identity + snapshot).
    ctx.set_segments({"browser": "chrome"})
    after = ctx.run_experience("us-experience")
    assert before is not None and after is not None
    assert before.variation_id == after.variation_id
    assert before.experience_key == after.experience_key


def test_run_custom_segments_does_not_perturb_bucketed_variation():
    core = _eval_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    before = ctx.run_experience("us-experience")
    ctx.run_custom_segments(["us-visitors"], {"country": "US"})
    after = ctx.run_experience("us-experience")
    assert before is not None and after is not None
    assert before.variation_id == after.variation_id


def test_noop_set_segments_is_content_equal_and_deterministic():
    core = _eval_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    ctx.set_segments({"browser": "chrome"})
    state_before = ctx._state  # noqa: SLF001
    before = ctx.run_experience("us-experience")
    # A no-op association (same values) must not change results (AC #4).
    ctx.set_segments({"browser": "chrome"})
    after = ctx.run_experience("us-experience")
    assert dict(ctx._state.default_segments) == dict(state_before.default_segments)  # noqa: SLF001
    assert before is not None and after is not None
    assert before.variation_id == after.variation_id


# --- Story 3.3 Task 7: public export surface --------------------------------


def test_custom_segments_result_is_public_export():
    import convert_sdk

    assert "CustomSegmentsResult" in convert_sdk.__all__
    assert convert_sdk.CustomSegmentsResult is CustomSegmentsResult


def test_frozen_exports_remain_stable():
    # Story 3.3 is additive — the previously frozen exports must still be present.
    import convert_sdk

    for name in ("Core", "Context", "__version__", "LifecycleEvent", "DataStore", "InMemoryDataStore"):
        assert name in convert_sdk.__all__
