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


def test_core_is_the_only_concrete_adapter_import_site():
    # The composition root (core.py, L4) is the ONLY allowed import site for the
    # concrete adapter across the whole package.
    importers = []
    for path in _SRC.rglob("*.py"):
        # The adapter module itself defines the class — skip it.
        if path == _SRC / "adapters" / "storage" / "in_memory.py":
            continue
        if _imports_concrete_adapter(path):
            importers.append(str(path.relative_to(_SRC)))
    assert importers == ["core.py"], (
        "Only core.py may import the concrete InMemoryDataStore; "
        f"found importers: {importers}"
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
