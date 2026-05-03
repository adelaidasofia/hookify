"""Tests for Bug #3 fix: Write tool field extraction in rule_engine._extract_field().

The Write tool sends {content: "..."} but _extract_field only checks
for 'new_string', so rules with field: new_text never fire on Write.
"""

from core.config_loader import Condition, Rule
from core.rule_engine import RuleEngine


class TestWriteToolContentMatch:
    """Write tool input should match rules that use field: new_text."""

    def test_write_tool_content_matches_new_text_pattern(self):
        """A rule with field: new_text should match Write tool input (content key)."""
        rule = Rule(
            name="no-api-keys",
            enabled=True,
            event="file",
            conditions=[
                Condition(
                    field="new_text",
                    operator="contains",
                    pattern="SECRET_API_KEY",
                )
            ],
            action="block",
            message="Do not write API keys to files.",
        )

        engine = RuleEngine()
        input_data = {
            "tool_name": "Write",
            "tool_input": {
                "file_path": "/tmp/config.py",
                "content": 'API_TOKEN = "SECRET_API_KEY_12345"',
            },
        }

        result = engine.evaluate_rules([rule], input_data)
        assert result != {}, "Write tool input with 'content' key must match new_text condition"
        assert "systemMessage" in result

    def test_edit_tool_new_string_still_works(self):
        """Regression: Edit tool input (new_string key) must still match new_text condition."""
        rule = Rule(
            name="no-api-keys",
            enabled=True,
            event="file",
            conditions=[
                Condition(
                    field="new_text",
                    operator="contains",
                    pattern="SECRET_API_KEY",
                )
            ],
            action="block",
            message="Do not write API keys to files.",
        )

        engine = RuleEngine()
        input_data = {
            "tool_name": "Edit",
            "tool_input": {
                "file_path": "/tmp/config.py",
                "old_string": 'API_TOKEN = "placeholder"',
                "new_string": 'API_TOKEN = "SECRET_API_KEY_12345"',
            },
        }

        result = engine.evaluate_rules([rule], input_data)
        assert result != {}, "Edit tool input with 'new_string' key must match new_text condition"
        assert "systemMessage" in result
