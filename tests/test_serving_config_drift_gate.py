"""Drift-gate reproduction fixtures for the serving_config contract probe (qs-13, Task B5).

These tests prove that the mypy contract probe in
``typecheck/serving_config_contract.py`` correctly fires (exits 1 with
``[typeddict-item]``) when a depended field is removed or renamed from the
generated ``serving_config.pyi``, and stays green (exits 0) when a new field
is added (additive-safe, AC2).

Mechanism (verified in the qs-13 D4 empirical spike):
  - MYPYPATH is set to a temp directory containing a mutated COPY of the
    stub (``convert_sdk/_generated/serving_config.pyi``).  mypy resolves the
    import from the MYPYPATH stub rather than the installed package, so the
    probe sees the mutated version without touching the committed file.
  - The real probe file (``typecheck/serving_config_contract.py``) is used
    unchanged — these tests exercise the gate as CI would run it.
  - The committed ``_generated/*.pyi`` files are NEVER modified by these tests.

Why pytest over a shell reproduction script:
  The pytest harness runs in CI's ``test`` job (which runs after ``type-check``),
  uses only stdlib + pytest (already a dev dependency), and is deterministic
  on any platform in the 3.9-3.13 matrix.  A shell script would require bash
  and mypy on PATH directly, making it more brittle across Windows CI cells.
  The subprocess mypy invocation is equivalent to the CI step.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
GENERATED_DIR = REPO_ROOT / "src" / "convert_sdk" / "_generated"
PROBE_FILE = REPO_ROOT / "typecheck" / "serving_config_contract.py"
STUB_FILE = GENERATED_DIR / "serving_config.pyi"
INIT_PYI = GENERATED_DIR / "__init__.pyi"


def _run_mypy_with_stub(stub_content: str) -> subprocess.CompletedProcess[str]:
    """Run mypy --strict on the real probe, resolving the stub from a temp copy.

    The temp directory mirrors the convert_sdk/_generated package structure so
    MYPYPATH makes mypy prefer it over the installed package.
    Returns the CompletedProcess so callers can inspect returncode and stdout.
    """
    tmp = Path(tempfile.mkdtemp())
    try:
        # Build the stub package tree: convert_sdk/_generated/
        gen_dir = tmp / "convert_sdk" / "_generated"
        gen_dir.mkdir(parents=True)
        (gen_dir / "__init__.pyi").write_text(
            INIT_PYI.read_text(encoding="utf-8"), encoding="utf-8"
        )
        (gen_dir / "serving_config.pyi").write_text(stub_content, encoding="utf-8")

        # Provide a convert_sdk package marker so mypy accepts the import path.
        convert_dir = tmp / "convert_sdk"
        (convert_dir / "__init__.pyi").write_text("", encoding="utf-8")
        (convert_dir / "py.typed").write_text("", encoding="utf-8")

        env = os.environ.copy()
        # MYPYPATH prepended: mypy finds the temp stub before the installed package.
        existing_mypypath = env.get("MYPYPATH", "")
        env["MYPYPATH"] = (
            str(tmp) + os.pathsep + existing_mypypath
            if existing_mypypath
            else str(tmp)
        )

        return subprocess.run(
            [
                sys.executable,
                "-m",
                "mypy",
                "--strict",
                "--python-version",
                "3.9",
                "--no-incremental",
                str(PROBE_FILE),
            ],
            capture_output=True,
            text=True,
            env=env,
        )
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture()
def real_stub_content() -> str:
    """The committed serving_config.pyi content (never modified)."""
    return STUB_FILE.read_text(encoding="utf-8")


class TestDriftGateAC1Removal:
    """AC1: a removed depended field turns mypy RED with [typeddict-item]."""

    def test_probe_green_with_committed_stub(self, real_stub_content: str) -> None:
        """Baseline: the committed stub passes the probe (gate is green)."""
        result = _run_mypy_with_stub(real_stub_content)
        assert result.returncode == 0, (
            f"Expected green (exit 0) with the committed stub.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    @pytest.mark.parametrize(
        "entity,field",
        [
            ("ConfigGoal", "id"),
            ("ConfigGoal", "key"),
            ("ConfigGoal", "type"),
            ("ConfigExperience", "key"),
            ("ConfigExperience", "variations"),
            ("ExperienceVariation", "id"),
            ("ExperienceVariation", "status"),
            ("ExperienceVariation", "traffic_allocation"),
            ("ExperienceVariation", "changes"),
            ("FeatureChangeData", "type"),
            ("FeatureChangeData", "data"),
            ("FeatureChangeDataData", "feature_id"),
            ("FeatureChangeDataData", "variables_data"),
            ("ConfigFeature", "id"),
            ("ConfigFeature", "variables"),
            ("FeatureVariable", "key"),
            ("FeatureVariable", "type"),
        ],
    )
    def test_removed_field_turns_gate_red(
        self, real_stub_content: str, entity: str, field: str
    ) -> None:
        """Removing a depended field from the stub must fail with [typeddict-item].

        The field line pattern is: ``    <field>: Optional[...]``
        We drop the line for the specific entity's field, then re-run mypy.
        Because all field names are unique-enough within their entity block,
        we drop the FIRST occurrence of the line under the entity class heading.
        """
        mutated = _drop_field_from_entity(real_stub_content, entity, field)
        result = _run_mypy_with_stub(mutated)
        assert result.returncode == 1, (
            f"Expected RED (exit 1) after removing {entity}['{field}'].\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "[typeddict-item]" in result.stdout, (
            f"Expected [typeddict-item] in mypy output after removing "
            f"{entity}['{field}'], got:\n{result.stdout}"
        )


class TestDriftGateAC7Rename:
    """AC7: a renamed depended field turns mypy RED with [typeddict-item]."""

    @pytest.mark.parametrize(
        "entity,field,renamed_to",
        [
            ("ConfigExperience", "key", "key_renamed"),
            ("ExperienceVariation", "status", "state"),
            ("FeatureChangeData", "data", "payload"),
            ("FeatureChangeDataData", "feature_id", "feature_identifier"),
            ("ConfigFeature", "variables", "variable_list"),
        ],
    )
    def test_renamed_field_turns_gate_red(
        self, real_stub_content: str, entity: str, field: str, renamed_to: str
    ) -> None:
        """Renaming a depended field in the stub must fail with [typeddict-item]."""
        mutated = _rename_field_in_entity(real_stub_content, entity, field, renamed_to)
        result = _run_mypy_with_stub(mutated)
        assert result.returncode == 1, (
            f"Expected RED (exit 1) after renaming {entity}['{field}'] -> '{renamed_to}'.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "[typeddict-item]" in result.stdout, (
            f"Expected [typeddict-item] in mypy output after renaming "
            f"{entity}['{field}'] -> '{renamed_to}', got:\n{result.stdout}"
        )


class TestDriftGateAC2Additive:
    """AC2: adding a new field or new discriminator value keeps mypy GREEN.

    The probe does not subscript fields it doesn't know about, so additive
    backend changes never break the gate.
    """

    def test_new_field_keeps_gate_green(self, real_stub_content: str) -> None:
        """Adding a new field to an existing entity keeps the probe green."""
        mutated = _add_field_to_entity(
            real_stub_content, "ConfigExperience", "new_field", "Optional[str]"
        )
        result = _run_mypy_with_stub(mutated)
        assert result.returncode == 0, (
            f"Expected GREEN (exit 0) after adding a new field (additive change).\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )

    def test_new_discriminator_value_keeps_gate_green(
        self, real_stub_content: str
    ) -> None:
        """A new Literal value in the goal type discriminator keeps the probe green.

        The probe only checks that goal["type"] is subscriptable; it does not
        assert which Literal values are present.
        """
        mutated = real_stub_content.replace(
            '"clicks_element"]]',
            '"clicks_element", "new_goal_type"]]',
        )
        result = _run_mypy_with_stub(mutated)
        assert result.returncode == 0, (
            f"Expected GREEN (exit 0) after adding a new discriminator value.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )


# ---------------------------------------------------------------------------
# Stub mutation helpers — operate on the .pyi text, never on disk files.
# ---------------------------------------------------------------------------


def _drop_field_from_entity(stub: str, entity: str, field: str) -> str:
    """Return a copy of ``stub`` with ``field`` removed from ``entity``'s class block."""
    lines = stub.splitlines(keepends=True)
    in_entity = False
    field_pattern = re.compile(rf"^\s+{re.escape(field)}\s*:")
    class_pattern = re.compile(r"^class\s+(\w+)\(")

    result: list[str] = []
    dropped = False
    for line in lines:
        m = class_pattern.match(line)
        if m:
            in_entity = m.group(1) == entity
        if in_entity and not dropped and field_pattern.match(line):
            dropped = True
            continue  # drop the line
        result.append(line)

    if not dropped:
        raise ValueError(
            f"Field '{field}' not found in entity '{entity}' in the stub. "
            "Check that the depended-field set matches the committed .pyi."
        )
    return "".join(result)


def _rename_field_in_entity(
    stub: str, entity: str, field: str, renamed_to: str
) -> str:
    """Return a copy of ``stub`` with ``field`` renamed to ``renamed_to`` in ``entity``."""
    lines = stub.splitlines(keepends=True)
    in_entity = False
    field_pattern = re.compile(rf"^(\s+){re.escape(field)}(\s*:.*)")
    class_pattern = re.compile(r"^class\s+(\w+)\(")

    result: list[str] = []
    renamed = False
    for line in lines:
        m = class_pattern.match(line)
        if m:
            in_entity = m.group(1) == entity
        if in_entity and not renamed:
            fm = field_pattern.match(line)
            if fm:
                # Preserve the original line ending (keepends=True gives us \n).
                suffix = line[len(fm.group(0)) :]  # trailing \n or empty
                line = f"{fm.group(1)}{renamed_to}{fm.group(2)}{suffix}"
                renamed = True
        result.append(line)

    if not renamed:
        raise ValueError(
            f"Field '{field}' not found in entity '{entity}' in the stub."
        )
    return "".join(result)


def _add_field_to_entity(
    stub: str, entity: str, new_field: str, type_annotation: str
) -> str:
    """Return a copy of ``stub`` with a new field appended to ``entity``'s class block.

    Locates the LAST field line belonging to ``entity``'s class block and
    inserts the new field immediately after it.  This is robust to blank lines
    between entities because we scan for the entity's last declared field
    index rather than tracking cross-line state.
    """
    lines = stub.splitlines(keepends=True)
    class_pattern = re.compile(r"^class\s+(\w+)\(")
    field_pattern = re.compile(r"^\s+\w+\s*:")

    in_entity = False
    last_field_idx: int = -1

    for idx, line in enumerate(lines):
        m = class_pattern.match(line)
        if m:
            in_entity = m.group(1) == entity
        if in_entity and field_pattern.match(line):
            last_field_idx = idx

    if last_field_idx == -1:
        raise ValueError(
            f"Entity '{entity}' not found in the stub or has no field lines."
        )

    new_line = f"    {new_field}: {type_annotation}\n"
    result = [*lines[: last_field_idx + 1], new_line, *lines[last_field_idx + 1 :]]
    return "".join(result)
