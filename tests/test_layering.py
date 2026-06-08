"""Story 3.1 — module-layering enforcement (import-linter intent, as a test).

The architecture mandates CI-enforced layering: ``ports/storage.py`` is L1,
``adapters/storage/in_memory.py`` is L3, and ``core.py`` (L4) is the SINGLE
composition root allowed to import the concrete ``InMemoryDataStore``. No L0/L1/
L2 module (``domain/``, ``ports/``, ``evaluation/``, ``tracking/``,
``context.py``) may import the concrete storage adapter.

import-linter is not installed in the MVP toolchain on this branch, so this test
realizes the same contract by statically scanning the source tree for forbidden
imports of ``adapters.storage.in_memory`` / ``InMemoryDataStore`` from inner
layers. It fails loudly if a future change leaks the concrete adapter inward.
"""

from __future__ import annotations

import ast
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src" / "convert_sdk"

# Inner-layer modules (L0/L1/L2) that must NOT import the concrete adapter.
_FORBIDDEN_INNER = [
    _SRC / "domain",
    _SRC / "ports",
    _SRC / "evaluation",
    _SRC / "tracking",
    _SRC / "context.py",
]

_CONCRETE_MODULE = "convert_sdk.adapters.storage.in_memory"
_CONCRETE_NAME = "InMemoryDataStore"


def _python_files(target: Path):
    if target.is_file():
        yield target
    elif target.is_dir():
        yield from target.rglob("*.py")


def _imports_concrete_adapter(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == _CONCRETE_MODULE:
                return True
            # `from convert_sdk.adapters.storage import in_memory`
            if module == "convert_sdk.adapters.storage" and any(
                alias.name == "in_memory" for alias in node.names
            ):
                return True
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == _CONCRETE_MODULE:
                    return True
    return False


def test_inner_layers_do_not_import_concrete_in_memory_store():
    offenders = []
    for target in _FORBIDDEN_INNER:
        for path in _python_files(target):
            if _imports_concrete_adapter(path):
                offenders.append(str(path.relative_to(_SRC)))
    assert offenders == [], (
        "L0/L1/L2 modules must not import the concrete InMemoryDataStore "
        f"(import-linter contract violated by: {offenders})"
    )


def test_core_is_the_only_inner_concrete_adapter_import_site():
    # core.py (L4 composition root) is the ONLY ORCHESTRATION site allowed to
    # import the concrete adapter. The package root __init__.py (L4 public
    # surface) and the adapter package's own __init__.py (L3 re-export) are the
    # only other legitimate import sites — they expose the class as a public API,
    # they do not wire it into evaluation/tracking. Everything else is forbidden.
    allowed = {
        "core.py",
        "__init__.py",  # package root public surface (re-export)
        "adapters/storage/__init__.py",  # adapter package re-export
        "adapters/storage/in_memory.py",  # the module that defines the class
    }
    offenders = []
    for path in _SRC.rglob("*.py"):
        rel = str(path.relative_to(_SRC))
        if rel in allowed:
            continue
        if _imports_concrete_adapter(path):
            offenders.append(rel)
    assert offenders == [], (
        "Only core.py (composition root) and the public/adapter re-export "
        "__init__ modules may import the concrete InMemoryDataStore; "
        f"unexpected importers: {offenders}"
    )


def _imported_modules(path: Path) -> list[str]:
    """Return the dotted module names imported by ``path`` (from/plain imports)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.append(node.module or "")
        elif isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
    return modules


def test_evaluation_segments_only_imports_allowed_layers():
    # Story 3.3: evaluation/segments.py is L2. It may import L0 (domain/) and the
    # sibling evaluation/rules.py, but must NOT import tracking/, adapters/,
    # ports/ concretes, context.py, or core.py (architecture Forbidden-imports).
    segments = _SRC / "evaluation" / "segments.py"
    assert segments.exists(), "evaluation/segments.py (Story 3.3) must exist"
    modules = _imported_modules(segments)
    forbidden_fragments = (
        "convert_sdk.tracking",
        "convert_sdk.adapters",
        "convert_sdk.context",
        "convert_sdk.core",
    )
    offenders = [
        m for m in modules if any(frag in m for frag in forbidden_fragments)
    ]
    assert offenders == [], (
        "evaluation/segments.py (L2) must not import tracking/adapters/context/core; "
        f"forbidden imports found: {offenders}"
    )
    # It SHOULD delegate rule matching to the sibling rule engine, not reimplement.
    assert any("evaluation.rules" in m for m in modules), (
        "evaluation/segments.py must delegate rule matching to evaluation/rules.py"
    )


def test_evaluation_entity_lookup_only_imports_allowed_layers():
    # Story 3.4: evaluation/entity_lookup.py is L2. It may import L0 (domain/)
    # and L1 (ports/) for typing, but must NOT import tracking/, adapters/,
    # context.py, or core.py (architecture Forbidden-imports).
    lookup = _SRC / "evaluation" / "entity_lookup.py"
    assert lookup.exists(), "evaluation/entity_lookup.py (Story 3.4) must exist"
    modules = _imported_modules(lookup)
    forbidden_fragments = (
        "convert_sdk.tracking",
        "convert_sdk.adapters",
        "convert_sdk.context",
        "convert_sdk.core",
    )
    offenders = [
        m for m in modules if any(frag in m for frag in forbidden_fragments)
    ]
    assert offenders == [], (
        "evaluation/entity_lookup.py (L2) must not import "
        f"tracking/adapters/context/core; forbidden imports found: {offenders}"
    )


def test_domain_config_snapshot_stays_l0_clean():
    # Story 3.4 only extends the snapshot's by-key/by-id indexes; domain/ stays
    # L0 (stdlib + _internal only) — it must NOT import ports/, evaluation/,
    # adapters/, tracking/, context.py, or core.py.
    snapshot = _SRC / "domain" / "config_snapshot.py"
    modules = _imported_modules(snapshot)
    forbidden_fragments = (
        "convert_sdk.ports",
        "convert_sdk.evaluation",
        "convert_sdk.adapters",
        "convert_sdk.tracking",
        "convert_sdk.context",
        "convert_sdk.core",
    )
    offenders = [
        m for m in modules if any(frag in m for frag in forbidden_fragments)
    ]
    assert offenders == [], (
        "domain/config_snapshot.py (L0) must import only stdlib + _internal; "
        f"upward imports found: {offenders}"
    )


def test_internal_redaction_is_stdlib_only_leaf():
    # Story 4.1: _internal/redaction.py is the L0 leaf utility — it must import
    # stdlib ONLY and reach back into NO other convert_sdk module (no upward
    # imports). Everything else may import it inward.
    redaction = _SRC / "_internal" / "redaction.py"
    assert redaction.exists(), "_internal/redaction.py (Story 4.1) must exist"
    modules = _imported_modules(redaction)
    offenders = [m for m in modules if m.startswith("convert_sdk")]
    assert offenders == [], (
        "_internal/redaction.py (L0 leaf) must import stdlib only; "
        f"upward convert_sdk imports found: {offenders}"
    )


def test_logging_module_does_not_import_higher_layers():
    # Story 4.1: logging.py may import the L0 leaf _internal/ utilities and the
    # L0 LifecycleEvent enum (events.py), but must NOT import adapters/transport/
    # evaluation/tracking/context/core — it is a low-level cross-cutting utility
    # consumed by higher layers; it must not pull the composition root inward.
    logging_mod = _SRC / "logging.py"
    modules = _imported_modules(logging_mod)
    forbidden_fragments = (
        "convert_sdk.adapters",
        "convert_sdk.evaluation",
        "convert_sdk.tracking",
        "convert_sdk.context",
        "convert_sdk.core",
        "convert_sdk.ports",
    )
    offenders = [
        m for m in modules if any(frag in m for frag in forbidden_fragments)
    ]
    assert offenders == [], (
        "logging.py must not import adapters/evaluation/tracking/context/core/ports; "
        f"forbidden imports found: {offenders}"
    )


def test_ports_storage_does_not_import_concrete_adapter():
    # The L1 port defines only the protocol; the concrete class must have moved
    # out of ports/storage.py.
    ports_storage = _SRC / "ports" / "storage.py"
    source = ports_storage.read_text(encoding="utf-8")
    # No class definition for the concrete adapter should remain here.
    tree = ast.parse(source, filename=str(ports_storage))
    class_names = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)
    }
    assert _CONCRETE_NAME not in class_names, (
        "InMemoryDataStore must be relocated out of ports/storage.py (L1) into "
        "adapters/storage/in_memory.py (L3)."
    )
