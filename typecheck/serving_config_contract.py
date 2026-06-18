"""Typed drift-gate contract probe for the Convert Python SDK (qs-13, Task B2).

This module is a **mypy-checked contract probe** — it is NEVER imported at
runtime, NEVER shipped in the wheel (lives outside ``src/``), and NEVER
executed. Its sole purpose is to bind synthetic typed values to the generated
``serving_config.pyi`` TypedDicts and subscript each field the SDK depends on
via **literal-key subscription** (``cfg["field"]``), so that when the backend
regenerates the stub with a depended field renamed or removed, mypy emits:

    error: TypedDict "X" has no key "field"  [typeddict-item]

The subscript (``[]``) form is the ONLY form that triggers ``[typeddict-item]``
on a dropped/unknown key.  ``.get("field")`` falls back to the object/None
overload and returns ``Any`` — it is blind to drift and MUST NOT be used here.
Attribute access (``.field``) emits ``[attr-defined]``, not ``[typeddict-item]``
— also not the right signal.

This pattern mirrors Ruby's Steep probe (qs-03) and events.py:34's
TYPE_CHECKING-guarded import: the generated stub is never imported at runtime.

Depended-field set (derived mechanically from the SDK readers, 2026-06-18):
  * evaluation/experiences.py: variation["status"], variation["traffic_allocation"],
    variation["id"], experience["variations"]
  * evaluation/features.py:    change["type"], change["data"], data["feature_id"],
    data["variables_data"], feature["id"], feature["variables"],
    experience["key"], variable["key"], variable["type"]
  * config_snapshot.py:        goals indexed by goal["key"] and goal["id"];
    goal["type"] is the discriminator field (AC4 — 10 values).

Fields the SDK reads at runtime but the spec stub omits (e.g. goal is_system,
goal status, goal selected_default) are intentionally NOT subscripted here —
they are NOT declared in serving_config.pyi and subscripting them would
false-positive (exit 1 on a field that was never in the spec).

Adding a new reader dependency to the SDK means adding a corresponding
subscript line here.  Removing a probe line means accepting that class of drift
silently — do not remove without updating the gate coverage comment.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - typing only; never imported at runtime
    from convert_sdk._generated.serving_config import (
        ConfigExperience,
        ConfigFeature,
        ConfigGoal,
        ExperienceVariation,
        FeatureChangeData,
        FeatureChangeDataData,
        FeatureVariable,
    )


def _probe_goal(goal: "ConfigGoal") -> None:
    """Probe the fields the SDK reads from a goal entity."""
    _ = goal["id"]
    _ = goal["key"]
    _ = goal["type"]


def _probe_experience(exp: "ConfigExperience") -> None:
    """Probe the fields the SDK reads from an experience entity."""
    _ = exp["key"]
    _ = exp["variations"]


def _probe_variation(var: "ExperienceVariation") -> None:
    """Probe the fields the SDK reads from an experience variation."""
    _ = var["id"]
    _ = var["status"]
    _ = var["traffic_allocation"]
    _ = var["changes"]


def _probe_feature_change(change: "FeatureChangeData") -> None:
    """Probe the fields the SDK reads from a fullStackFeature change object."""
    _ = change["type"]
    _ = change["data"]


def _probe_feature_change_data(data: "FeatureChangeDataData") -> None:
    """Probe the fields the SDK reads from the inner change data object."""
    _ = data["feature_id"]
    _ = data["variables_data"]


def _probe_feature(feature: "ConfigFeature") -> None:
    """Probe the fields the SDK reads from a feature entity."""
    _ = feature["id"]
    _ = feature["variables"]


def _probe_feature_variable(variable: "FeatureVariable") -> None:
    """Probe the fields the SDK reads from a feature variable definition."""
    _ = variable["key"]
    _ = variable["type"]
