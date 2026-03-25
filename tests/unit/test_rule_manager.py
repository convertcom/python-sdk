from convertcom_sdk.rules import RuleManager


def test_rule_manager_with_default_processor():
    manager = RuleManager({"rules": {"keys_case_sensitive": True}})
    rule_set = {
        "OR": [
            {
                "AND": [
                    {
                        "OR_WHEN": [
                            {
                                "key": "device",
                                "matching": {"match_type": "equals", "negated": False},
                                "value": "pc",
                            },
                            {
                                "key": "price",
                                "matching": {"match_type": "less", "negated": False},
                                "value": 100,
                            },
                        ]
                    }
                ]
            }
        ]
    }

    assert manager.is_rule_matched(
        {"device": "pc", "browser": "Mozilla", "price": 3},
        rule_set,
    ) is True
    assert manager.is_rule_matched(
        {"device": "tablet", "browser": "Mozilla", "price": 3},
        rule_set,
    ) is True
    assert manager.is_rule_matched(
        {"DEVICE": "tablet", "BROWSER": "Mozilla", "PRICE": 3},
        rule_set,
    ) is False


def test_rule_manager_handles_invalid_structures_like_js():
    manager = RuleManager()
    assert manager.is_valid_rule(
        {
            "key": "device",
            "matching": {"match_type": "contains", "negated": False},
            "value": "phone",
        }
    ) is True
    assert manager.is_valid_rule({"matching": "contains", "data": "phone"}) is False
    assert manager.is_rule_matched([], {}) is False
    assert manager.is_rule_matched("a string", 1234567) is False
    assert manager.is_rule_matched({}, [[["a string"]]]) is False


def test_rule_manager_with_custom_processor_and_case_insensitive_keys():
    custom_processor = {
        "isTypeOf": lambda value, test_against, negation=False: (
            type(value).__name__ != test_against
            if negation
            else type(value).__name__ == test_against
        )
    }
    manager = RuleManager(
        {
            "rules": {
                "comparisonProcessor": custom_processor,
                "keys_case_sensitive": False,
            }
        }
    )
    rule_set = {
        "OR": [
            {
                "AND": [
                    {
                        "OR_WHEN": [
                            {
                                "key": "SUM",
                                "matching": {"match_type": "isTypeOf", "negated": False},
                                "value": "int",
                            }
                        ]
                    }
                ]
            }
        ]
    }
    assert manager.get_comparison_processor_methods() == ["isTypeOf"]
    assert manager.is_rule_matched({"sum": 44}, rule_set) is True
