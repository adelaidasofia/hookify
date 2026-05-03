"""Tests for permissionDecisionReason in block-rule output."""

from core.config_loader import Condition, Rule
from core.rule_engine import RuleEngine


def test_block_rule_includes_permission_decision_reason():
    rule = Rule(
        name="block-x",
        enabled=True,
        event="bash",
        conditions=[Condition(field="command", operator="regex_match", pattern="rm -rf /")],
        action="block",
        message="absolute danger",
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
    hso = result["hookSpecificOutput"]
    assert hso["permissionDecision"] == "deny"
    assert "permissionDecisionReason" in hso
    assert "absolute danger" in hso["permissionDecisionReason"]
