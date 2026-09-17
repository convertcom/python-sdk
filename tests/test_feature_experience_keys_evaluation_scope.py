"""CAP-1: `experience_keys` narrows evaluation itself, not just the result."""

from __future__ import annotations

from unittest.mock import patch

import convert_sdk.evaluation.features as features_mod
from tests.test_feature_experience_keys import SHARED_FEATURE_CONFIG, _ctx


def test_excluded_experience_is_never_passed_to_select_experience():
    # Patch features_mod's own binding -- context.py imports a separate
    # name for the same function, so a spy there misses these calls.
    ctx = _ctx(SHARED_FEATURE_CONFIG, visitor_id="shared-visitor")

    with patch.object(
        features_mod, "select_experience", wraps=features_mod.select_experience
    ) as spy:
        result = ctx.run_feature("shared-feature", experience_keys=["secondary-experiment"])

    assert result is not None
    assert result.experience_key == "secondary-experiment"
    called_experience_keys = [call.args[0] for call in spy.call_args_list]
    assert "primary-experiment" not in called_experience_keys
    assert called_experience_keys == ["secondary-experiment"]
