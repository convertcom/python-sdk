"""Drift-protection tests for the Story 4.5 advanced documentation set.

The advanced topic guides and migration guides under ``docs/`` embed runnable
Python code samples. This module is the executable guard that keeps those
samples honest: it extracts every fenced ``python`` block from each guide,
executes it against the **current** public API, and asserts the documented
outcomes actually occur. A guide whose sample drifts from the implemented
surface fails here — docs cannot rot silently.

Conventions enforced (Story 4.5 Critical Warnings):

* Every guide referenced from ``docs/index.md`` exists on disk (no dead links).
* No guide embeds a literal ``sdk_key`` secret — keys come from
  ``os.environ["CONVERT_SDK_KEY"]``.
* Executable samples are marked with a ``# doctest: run`` directive on the
  opening fence line (```` ```python  # doctest: run ````) so prose-only or
  shell snippets are not executed, but every *executable* sample is.

The samples run fully offline against a shared sample config — no network, no
SDK key, no framework — mirroring the Story 1.6 examples guard.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = PROJECT_ROOT / "docs"
README = PROJECT_ROOT / "README.md"

# --- Guides expected by each task (build manifest) ---------------------------

DOC1_GUIDES = (
    "index.md",
    "initialization.md",
    "evaluation.md",
    "tracking.md",
    "queue-control.md",
)
DOC2_GUIDES = (
    "debugging.md",
    "extending.md",
    "support-workflows.md",
)
DOC3_GUIDES = (
    "migration-from-rest.md",
    "migration-from-javascript.md",
)
ALL_GUIDES = DOC1_GUIDES + DOC2_GUIDES + DOC3_GUIDES

# Pre-existing guide (Story runtime-integration) — already linked from README.
PREEXISTING_GUIDES = ("runtime-integration.md",)


# --- Sample config the executable guide samples bind to ----------------------
#
# A single self-contained config exercising experiences + a fullStack feature,
# goals (for tracking), and segments (for custom-segment evaluation). The guide
# samples `from tests.docs_sample_config import SAMPLE_CONFIG` so the doc text
# stays focused on the API call, not on rebuilding fixtures.


def _extract_python_samples(text: str) -> list[str]:
    """Return the bodies of every executable fenced python block.

    A block is executable when its opening fence carries the ``# doctest: run``
    directive: ```` ```python  # doctest: run ````.
    """
    pattern = re.compile(
        r"```python[^\n]*#\s*doctest:\s*run[^\n]*\n(.*?)```",
        re.DOTALL,
    )
    return [m.group(1) for m in pattern.finditer(text)]


def _all_python_fences(text: str) -> list[str]:
    """Return the bodies of EVERY fenced python block (executable or not)."""
    pattern = re.compile(r"```python[^\n]*\n(.*?)```", re.DOTALL)
    return [m.group(1) for m in pattern.finditer(text)]


def _run_sample(body: str) -> dict:
    """Execute a sample body and return its module namespace.

    Samples may call ``print``; that is fine. A sample that raises fails the
    test, proving the documented code path is broken.
    """
    namespace: dict = {"__name__": "__doc_sample__"}
    exec(compile(body, "<doc-sample>", "exec"), namespace)
    return namespace


# --- DOC-1: core topic guides exist and their samples run --------------------


@pytest.mark.parametrize("name", DOC1_GUIDES)
def test_doc1_guide_exists(name):
    assert (DOCS_DIR / name).is_file(), f"missing topic guide: docs/{name}"


@pytest.mark.parametrize("name", DOC1_GUIDES)
def test_doc1_guide_samples_execute(name):
    text = (DOCS_DIR / name).read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    # index.md is a landing page; it need not carry executable samples, but the
    # behavior-bearing guides must.
    if name != "index.md":
        assert samples, f"docs/{name} has no executable (# doctest: run) sample"
    for body in samples:
        _run_sample(body)


def test_initialization_guide_documents_env_key_pattern():
    text = (DOCS_DIR / "initialization.md").read_text(encoding="utf-8")
    assert "os.environ" in text and "CONVERT_SDK_KEY" in text, (
        "initialization guide must source sdk_key from the environment"
    )


def test_evaluation_guide_buckets_a_real_variation():
    text = (DOCS_DIR / "evaluation.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, "evaluation guide must have an executable sample"
    # At least one sample must produce a bucketed variation outcome.
    saw_variation = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_variation_key") in {"control", "treatment"}:
            saw_variation = True
    assert saw_variation, (
        "evaluation guide sample must bucket a visitor into a real variation "
        "and expose it as _doc_variation_key"
    )


def test_tracking_guide_queues_and_deduplicates():
    text = (DOCS_DIR / "tracking.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, "tracking guide must have an executable sample"
    saw_queued = saw_dedup = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_first_tracked") is True:
            saw_queued = True
        if ns.get("_doc_second_tracked") is False:
            saw_dedup = True
    assert saw_queued, "tracking guide must show a real QUEUED conversion"
    assert saw_dedup, "tracking guide must show a real deduplicated conversion"


# --- DOC-2: debugging, extending, support-workflows guides -------------------


@pytest.mark.parametrize("name", DOC2_GUIDES)
def test_doc2_guide_exists(name):
    assert (DOCS_DIR / name).is_file(), f"missing guide: docs/{name}"


@pytest.mark.parametrize("name", DOC2_GUIDES)
def test_doc2_guide_samples_execute(name):
    text = (DOCS_DIR / name).read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, f"docs/{name} has no executable (# doctest: run) sample"
    for body in samples:
        _run_sample(body)


def test_debugging_guide_shows_closed_reason_codes():
    """The debugging guide must surface real DiagnosticReason codes from the
    diagnose_* surface — both a RESOLVED and a not-found outcome."""
    text = (DOCS_DIR / "debugging.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, "debugging guide must have an executable sample"
    saw_resolved = saw_miss = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_diag_resolved") == "resolved":
            saw_resolved = True
        if ns.get("_doc_diag_miss") in {
            "experience_not_found",
            "feature_not_found",
            "goal_not_found",
            "entity_not_found",
        }:
            saw_miss = True
    assert saw_resolved, "debugging guide must show a RESOLVED diagnostic"
    assert saw_miss, "debugging guide must show a not-found DiagnosticReason"


def test_debugging_guide_documents_hashed_visitor_not_raw():
    """The diagnostic surface fingerprints the visitor — the guide must say so
    and must not imply the raw visitor id is logged."""
    text = (DOCS_DIR / "debugging.md").read_text(encoding="utf-8").lower()
    assert "fingerprint" in text or "hashed" in text or "visitor_ref" in text, (
        "debugging guide must document that the visitor reference is hashed"
    )


def test_extending_guide_injects_custom_protocol_implementations():
    """The extending guide must show a working custom Transport injected via the
    keyword-only transport= arg and a custom DataStore via SDKConfig.data_store."""
    text = (DOCS_DIR / "extending.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, "extending guide must have an executable sample"
    saw_transport = saw_store = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_custom_transport_used") is True:
            saw_transport = True
        if ns.get("_doc_custom_store_used") is True:
            saw_store = True
    assert saw_transport, "extending guide must inject a custom Transport"
    assert saw_store, "extending guide must inject a custom DataStore via data_store"


def test_extending_guide_does_not_invent_a_logger_protocol():
    """stdlib logging is the seam — there is no ports/logger.py Protocol."""
    text = (DOCS_DIR / "extending.md").read_text(encoding="utf-8")
    assert "ports/logger.py" not in text
    assert "Logger Protocol" not in text and "LoggerProtocol" not in text


def test_extending_guide_lists_the_real_protocol_seams():
    text = (DOCS_DIR / "extending.md").read_text(encoding="utf-8")
    for seam in ("ports/transport.py", "ports/storage.py", "ports/event_bus.py"):
        assert seam in text, f"extending guide must reference {seam}"


# --- DOC-3: migration guides + README cross-links ----------------------------


@pytest.mark.parametrize("name", DOC3_GUIDES)
def test_doc3_guide_exists(name):
    assert (DOCS_DIR / name).is_file(), f"missing migration guide: docs/{name}"


@pytest.mark.parametrize("name", DOC3_GUIDES)
def test_doc3_guide_samples_execute(name):
    text = (DOCS_DIR / name).read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    assert samples, f"docs/{name} has no executable (# doctest: run) sample"
    for body in samples:
        _run_sample(body)


def test_rest_migration_guide_maps_endpoints_and_improvements():
    text = (DOCS_DIR / "migration-from-rest.md").read_text(encoding="utf-8").lower()
    # Must map the two raw REST flows onto the SDK surface.
    assert "config" in text and "track" in text
    # Must call out the operational improvements over raw REST.
    for improvement in ("batch", "dedup", "lifecycle", "redact"):
        assert improvement in text, (
            f"REST migration guide must call out the {improvement!r} improvement"
        )


def test_rest_migration_sdk_side_sample_produces_real_outcome():
    text = (DOCS_DIR / "migration-from-rest.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    saw_outcome = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_rest_tracked") is True:
            saw_outcome = True
    assert saw_outcome, (
        "REST migration guide must show the SDK-side flow producing a real "
        "tracked conversion"
    )


def test_js_migration_guide_documents_pythonic_differences():
    text = (DOCS_DIR / "migration-from-javascript.md").read_text(encoding="utf-8")
    lower = text.lower()
    # Maps the JS concepts.
    for js_concept in (
        "runExperience",
        "runFeature",
        "setDefaultSegments",
        "runCustomSegments",
    ):
        assert js_concept in text, f"JS migration guide must map {js_concept}"
    # Maps to the Pythonic equivalents.
    for py_equiv in (
        "run_experience",
        "run_feature",
        "set_segments",
        "run_custom_segments",
    ):
        assert py_equiv in text, f"JS migration guide must name {py_equiv}"
    # Documents the deliberate Pythonic differences (not a syntax port).
    for difference in ("snake_case", "mutator", "dataclass", "protocol"):
        assert difference in lower, (
            f"JS migration guide must document the {difference!r} difference"
        )


def test_js_migration_sdk_side_sample_runs():
    text = (DOCS_DIR / "migration-from-javascript.md").read_text(encoding="utf-8")
    samples = _extract_python_samples(text)
    saw = False
    for body in samples:
        ns = _run_sample(body)
        if ns.get("_doc_js_variation") in {"control", "treatment"}:
            saw = True
    assert saw, "JS migration guide must show the Pythonic equivalent bucketing a visitor"


# --- README cross-links + dead-link guard ------------------------------------


def test_readme_links_to_docs_index():
    text = README.read_text(encoding="utf-8")
    assert "docs/index.md" in text, "README must link to the docs index"


def test_readme_links_to_migration_guides():
    text = README.read_text(encoding="utf-8")
    assert "docs/migration-from-rest.md" in text
    assert "docs/migration-from-javascript.md" in text


def test_docs_index_has_no_dead_links_to_guides():
    """Every docs/*.md link in the index must resolve to a real file."""
    index_text = (DOCS_DIR / "index.md").read_text(encoding="utf-8")
    linked = set(re.findall(r"\(([a-z0-9-]+\.md)\)", index_text))
    # The index links to every guide except itself.
    must_link = (set(ALL_GUIDES) | set(PREEXISTING_GUIDES)) - {"index.md"}
    for name in must_link:
        assert name in linked, f"docs/index.md does not link to {name}"
    for name in linked:
        assert (DOCS_DIR / name).is_file(), f"docs/index.md links to missing docs/{name}"


# --- Secret-handling guard across the entire docs set ------------------------

_LITERAL_KEY = re.compile(r"""sdk_key\s*=\s*['"]([^'"]+)['"]""")
_ALLOWED_PLACEHOLDERS = {"your-sdk-key-here", ""}


@pytest.mark.parametrize("name", ALL_GUIDES)
def test_guides_never_embed_literal_sdk_keys(name):
    path = DOCS_DIR / name
    if not path.is_file():
        pytest.skip(f"docs/{name} not built yet")
    text = path.read_text(encoding="utf-8")
    for match in _LITERAL_KEY.finditer(text):
        value = match.group(1)
        # Allow obvious placeholders and the env-read form os.environ[...].
        assert value in _ALLOWED_PLACEHOLDERS, (
            f"docs/{name} embeds a literal sdk_key {value!r}; "
            f"read it from CONVERT_SDK_KEY instead"
        )
