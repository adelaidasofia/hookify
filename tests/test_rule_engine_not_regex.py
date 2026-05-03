"""Tests for the not_regex_match operator."""

from core.config_loader import Condition, Rule
from core.rule_engine import RuleEngine


def test_not_regex_match_fires_when_pattern_absent():
    rule = Rule(
        name="x",
        enabled=True,
        event="bash",
        conditions=[Condition(field="command", operator="not_regex_match", pattern=r"safe-prefix")],
        action="warn",
        message="m",
    )
    engine = RuleEngine()
    result = engine.evaluate_rules(
        [rule],
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "rm -rf /"},
        },
    )
    assert result != {}, "should fire when pattern is NOT present"


def test_not_regex_match_silent_when_pattern_present():
    rule = Rule(
        name="x",
        enabled=True,
        event="bash",
        conditions=[Condition(field="command", operator="not_regex_match", pattern=r"safe-prefix")],
        action="warn",
        message="m",
    )
    engine = RuleEngine()
    result = engine.evaluate_rules(
        [rule],
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "safe-prefix mything"},
        },
    )
    assert result == {}, "should NOT fire when pattern is present"
