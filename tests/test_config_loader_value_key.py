"""Tests for the 'value' key alias in condition frontmatter."""
from core.config_loader import Condition


def test_value_key_aliases_pattern():
    c = Condition.from_dict({"field": "command", "operator": "contains", "value": "rm"})
    assert c.pattern == "rm"


def test_pattern_takes_precedence_over_value_when_both_present():
    c = Condition.from_dict({"field": "x", "pattern": "P", "value": "V"})
    assert c.pattern == "P"


def test_pattern_still_works_alone():
    c = Condition.from_dict({"field": "x", "operator": "contains", "pattern": "p"})
    assert c.pattern == "p"
