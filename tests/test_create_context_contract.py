"""Story 1.3 — create_context signature contract-freeze tests (SDK-2).

The reconciled PRD freezes the visitor-context creation signature as
``create_context(visitor_id, visitor_attributes=None)`` (Pythonic snake_case,
no JavaScript camelCase). Earlier branch lineage used ``attributes=`` at the
creation boundary; this drift must not reappear, because it would propagate
through epic-2+.

These tests pin the creation contract on both ``Core.create_context`` and the
``Context`` constructor, and guard the onboarding examples so the README
and example files keep documenting the frozen ``visitor_attributes=`` name at
the creation boundary rather than the old ``attributes=`` creation keyword.
"""

from __future__ import annotations

import inspect
from pathlib import Path

from convert_sdk import Core, SDKConfig
from convert_sdk.context import Context

PROJECT_ROOT = Path(__file__).resolve().parent.parent
README = PROJECT_ROOT / "README.md"
EXAMPLES_DIR = PROJECT_ROOT / "examples"

CONFIG = {
    "account_id": "100123",
    "project": {"id": "200456"},
    "experiences": [
        {
            "id": "e1",
            "key": "exp-one",
            "variations": [{"id": "v1", "key": "control", "traffic_allocation": 100.0}],
        }
    ],
}


def _ready_core() -> Core:
    return Core(SDKConfig(data=CONFIG)).initialize()


def test_core_create_context_uses_visitor_attributes_keyword():
    sig = inspect.signature(Core.create_context)
    params = list(sig.parameters)
    assert "visitor_attributes" in params, (
        "Core.create_context must expose the frozen `visitor_attributes` parameter"
    )
    assert "attributes" not in params, (
        "Core.create_context must NOT use the old `attributes` creation keyword"
    )


def test_context_constructor_uses_visitor_attributes_keyword():
    sig = inspect.signature(Context.__init__)
    params = list(sig.parameters)
    assert "visitor_attributes" in params
    assert "attributes" not in params, (
        "Context.__init__ must not take the old `attributes` creation keyword"
    )


def test_create_context_accepts_visitor_attributes_keyword():
    core = _ready_core()
    ctx = core.create_context("visitor-1", visitor_attributes={"country": "US"})
    assert ctx.visitor_id == "visitor-1"
    assert dict(ctx.visitor_attributes) == {"country": "US"}


def _create_context_call_bodies(text: str) -> list[str]:
    """Return the argument body of every ``create_context(...)`` call in text."""
    bodies: list[str] = []
    idx = 0
    needle = "create_context("
    while True:
        start = text.find(needle, idx)
        if start == -1:
            break
        # Find the matching close paren from the opening one.
        depth = 0
        i = start + len(needle) - 1
        body_start = i + 1
        while i < len(text):
            ch = text[i]
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    bodies.append(text[body_start:i])
                    idx = i + 1
                    break
            i += 1
        else:
            break
    return bodies


def test_readme_creation_block_documents_visitor_attributes():
    text = README.read_text(encoding="utf-8")
    # The create_context creation block must document the frozen kw.
    assert "visitor_attributes=" in text, (
        "README must document create_context(... visitor_attributes=...)"
    )
    # No create_context(...) call in the README may use the old `attributes=`
    # creation keyword.
    for body in _create_context_call_bodies(text):
        assert "attributes=" not in body or "visitor_attributes=" in body, (
            "README create_context call uses the old `attributes=` creation keyword"
        )
        assert "attributes=" not in body.replace("visitor_attributes=", ""), (
            "README create_context call still passes a bare `attributes=` keyword"
        )


def test_examples_do_not_use_old_creation_keyword():
    for path in EXAMPLES_DIR.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for body in _create_context_call_bodies(text):
            assert "attributes=" not in body.replace("visitor_attributes=", ""), (
                f"examples/{path.name} uses old `attributes=` in create_context"
            )
