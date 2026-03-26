from __future__ import annotations

import json
from pathlib import Path

import pytest

from convertcom_sdk import (
    BucketingManager,
    DataManager,
    ExperienceManager,
    FeatureManager,
    RuleManager,
    SegmentsManager,
)


@pytest.fixture
def config():
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "test_config.json"
    return json.loads(fixture_path.read_text())


@pytest.fixture
def managers(config):
    bucketing_manager = BucketingManager(config)
    rule_manager = RuleManager(config)
    data_manager = DataManager(
        config,
        bucketing_manager=bucketing_manager,
        rule_manager=rule_manager,
    )
    segments_manager = SegmentsManager(
        config,
        data_manager=data_manager,
        rule_manager=rule_manager,
    )
    experience_manager = ExperienceManager(config, data_manager=data_manager)
    feature_manager = FeatureManager(config, data_manager=data_manager)
    return {
        "bucketing_manager": bucketing_manager,
        "rule_manager": rule_manager,
        "data_manager": data_manager,
        "segments_manager": segments_manager,
        "experience_manager": experience_manager,
        "feature_manager": feature_manager,
    }
