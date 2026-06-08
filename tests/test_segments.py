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


def test_run_custom_segments_performs_no_network_io(monkeypatch):
    # Custom-segment evaluation must be fully local — no transport construction.
    import convert_sdk.evaluation.segments as seg_mod

    # The module must not import any transport/network surface at all.
    import inspect

    source = inspect.getsource(seg_mod)
    assert "httpx" not in source
    assert "transport" not in source.lower()
    assert "adapters" not in source

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
