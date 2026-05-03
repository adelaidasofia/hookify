"""Tests for the JSON rule cache module (core/cache.py).

Covers cache path computation, save/load round-trips, invalidation
triggers, atomic write safety, and the HOOKIFY_NO_CACHE bypass flag.
"""

import json
import os

import pytest

from core.cache import (
    CACHE_SCHEMA_VERSION,
    SCHEMA_REVISION,
    cache_path_for,
    is_bypass_enabled,
    is_cache_valid,
    load_from_cache,
    save_to_cache,
)
from core.config_loader import Condition, Rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rule(**overrides) -> Rule:
    """Build a Rule with all fields populated, merging *overrides*."""
    defaults = {
        "name": "dangerous-rm",
        "enabled": True,
        "event": "bash",
        "pattern": r"rm\s+-rf",
        "conditions": [
            Condition(field="command", operator="regex_match", pattern=r"rm\s+-rf"),
            Condition(field="file_path", operator="contains", pattern="/tmp"),
        ],
        "action": "block",
        "tool_matcher": "Bash",
        "message": "Dangerous command detected!",
    }
    defaults.update(overrides)
    return Rule(**defaults)


# ---------------------------------------------------------------------------
# TestCachePath
# ---------------------------------------------------------------------------


class TestCachePath:
    """cache_path_for() computes a deterministic, per-scope cache path."""

    def test_uses_claude_plugin_root_when_set(self, tmp_path, monkeypatch):
        plugin_root = str(tmp_path / "plugin-root")
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", plugin_root)
        result = cache_path_for("/proj/.claude", "/home/.claude")
        assert result.startswith(os.path.join(plugin_root, ".cache"))
        assert result.endswith(".json")

    def test_falls_back_to_xdg_cache_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        xdg = str(tmp_path / "xdg-cache")
        monkeypatch.setenv("XDG_CACHE_HOME", xdg)
        result = cache_path_for("/proj/.claude", "/home/.claude")
        assert result.startswith(os.path.join(xdg, "hookify"))
        assert result.endswith(".json")

    def test_falls_back_to_home_dot_cache(self, tmp_path, monkeypatch):
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        home = str(tmp_path / "fakehome")
        os.makedirs(home, exist_ok=True)
        monkeypatch.setenv("HOME", home)
        result = cache_path_for("/proj/.claude", "/home/.claude")
        assert result.startswith(os.path.join(home, ".cache", "hookify"))

    def test_deterministic_same_inputs(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        a = cache_path_for("/proj/.claude", "/home/.claude")
        b = cache_path_for("/proj/.claude", "/home/.claude")
        assert a == b

    def test_different_inputs_produce_different_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        a = cache_path_for("/proj-a/.claude", "/home/.claude")
        b = cache_path_for("/proj-b/.claude", "/home/.claude")
        assert a != b


# ---------------------------------------------------------------------------
# TestSaveAndLoadRoundTrip
# ---------------------------------------------------------------------------


class TestSaveAndLoadRoundTrip:
    """Rules survive a save -> load cycle with no field loss."""

    def test_full_rule_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        cp = cache_path_for("/proj/.claude", "/home/.claude")

        rule = _make_rule()
        sources = {
            "/proj/.claude/hookify.dangerous-rm.local.md": 1735000000.0,
            "/home/.claude/hookify.research-save.local.md": 1735000123.456,
        }

        assert save_to_cache(cp, [rule], sources) is True

        loaded = load_from_cache(cp)
        assert loaded is not None

        loaded_rules, loaded_sources = loaded
        assert len(loaded_rules) == 1
        lr = loaded_rules[0]

        # Verify every field
        assert lr.name == rule.name
        assert lr.enabled == rule.enabled
        assert lr.event == rule.event
        assert lr.pattern == rule.pattern
        assert lr.action == rule.action
        assert lr.tool_matcher == rule.tool_matcher
        assert lr.message == rule.message

        # Verify conditions
        assert len(lr.conditions) == len(rule.conditions)
        for i in range(len(rule.conditions)):
            assert lr.conditions[i].field == rule.conditions[i].field
            assert lr.conditions[i].operator == rule.conditions[i].operator
            assert lr.conditions[i].pattern == rule.conditions[i].pattern

        # Verify sources
        assert loaded_sources == sources

    def test_rule_with_none_fields_round_trips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        cp = cache_path_for("/proj/.claude", "/home/.claude")

        rule = Rule(
            name="minimal",
            enabled=True,
            event="all",
            pattern=None,
            conditions=[],
            action="warn",
            tool_matcher=None,
            message="",
        )
        assert save_to_cache(cp, [rule], {}) is True
        loaded_rules, loaded_sources = load_from_cache(cp)
        assert len(loaded_rules) == 1
        lr = loaded_rules[0]
        assert lr.pattern is None
        assert lr.tool_matcher is None
        assert lr.conditions == []
        assert loaded_sources == {}

    def test_multiple_rules_round_trip(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        cp = cache_path_for("/proj/.claude", "/home/.claude")

        rules = [
            _make_rule(name="rule-a", action="warn"),
            _make_rule(name="rule-b", action="block"),
            _make_rule(name="rule-c", event="file", tool_matcher=None),
        ]
        sources = {"/a.md": 100.0, "/b.md": 200.0}
        assert save_to_cache(cp, rules, sources) is True

        loaded_rules, _ = load_from_cache(cp)
        assert [r.name for r in loaded_rules] == ["rule-a", "rule-b", "rule-c"]

    def test_cache_file_contains_schema_revision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        cp = cache_path_for("/proj/.claude", "/home/.claude")
        save_to_cache(cp, [], {})
        with open(cp) as f:
            data = json.load(f)
        assert data["schema_revision"] == SCHEMA_REVISION
        assert data["version"] == CACHE_SCHEMA_VERSION


# ---------------------------------------------------------------------------
# TestInvalidation
# ---------------------------------------------------------------------------


class TestInvalidation:
    """Cache load returns None for missing, corrupt, or mismatched caches."""

    def test_load_returns_none_when_file_missing(self, tmp_path):
        result = load_from_cache(str(tmp_path / "nonexistent.json"))
        assert result is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{not valid json!!")
        result = load_from_cache(str(bad_file))
        assert result is None

    def test_load_returns_none_on_wrong_schema_version(self, tmp_path):
        bad_file = tmp_path / "old.json"
        bad_file.write_text(json.dumps({
            "version": 9999,
            "schema_revision": "future",
            "sources": {},
            "rules": [],
        }))
        result = load_from_cache(str(bad_file))
        assert result is None

    def test_load_returns_none_on_non_dict_top_level(self, tmp_path):
        bad_file = tmp_path / "list.json"
        bad_file.write_text(json.dumps([1, 2, 3]))
        result = load_from_cache(str(bad_file))
        assert result is None

    def test_load_returns_none_on_bad_sources_type(self, tmp_path):
        bad_file = tmp_path / "bad_sources.json"
        bad_file.write_text(json.dumps({
            "version": CACHE_SCHEMA_VERSION,
            "schema_revision": SCHEMA_REVISION,
            "sources": "not-a-dict",
            "rules": [],
        }))
        result = load_from_cache(str(bad_file))
        assert result is None

    def test_load_returns_none_on_bad_rules_type(self, tmp_path):
        bad_file = tmp_path / "bad_rules.json"
        bad_file.write_text(json.dumps({
            "version": CACHE_SCHEMA_VERSION,
            "schema_revision": SCHEMA_REVISION,
            "sources": {},
            "rules": "not-a-list",
        }))
        result = load_from_cache(str(bad_file))
        assert result is None

    def test_is_cache_valid_true_when_matching(self):
        sources = {"/a.md": 100.0, "/b.md": 200.0}
        current = {"/a.md": 100.0, "/b.md": 200.0}
        assert is_cache_valid(sources, current) is True

    def test_is_cache_valid_false_when_file_added(self):
        sources = {"/a.md": 100.0}
        current = {"/a.md": 100.0, "/b.md": 200.0}
        assert is_cache_valid(sources, current) is False

    def test_is_cache_valid_false_when_file_removed(self):
        sources = {"/a.md": 100.0, "/b.md": 200.0}
        current = {"/a.md": 100.0}
        assert is_cache_valid(sources, current) is False

    def test_is_cache_valid_false_when_mtime_changed(self):
        sources = {"/a.md": 100.0, "/b.md": 200.0}
        current = {"/a.md": 100.0, "/b.md": 201.0}
        assert is_cache_valid(sources, current) is False

    def test_is_cache_valid_empty_sets(self):
        assert is_cache_valid({}, {}) is True


# ---------------------------------------------------------------------------
# TestAtomicWrite
# ---------------------------------------------------------------------------


class TestAtomicWrite:
    """Atomic write leaves no temp files on success."""

    def test_no_temp_file_after_successful_write(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        cp = cache_path_for("/proj/.claude", "/home/.claude")

        save_to_cache(cp, [_make_rule()], {"/a.md": 100.0})

        cache_dir = os.path.dirname(cp)
        entries = os.listdir(cache_dir)
        tmp_files = [e for e in entries if ".tmp" in e]
        assert tmp_files == [], f"Temp files left behind: {tmp_files}"

    def test_cache_dir_created_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path / "deep" / "nested"))
        cp = cache_path_for("/proj/.claude", "/home/.claude")

        assert not os.path.exists(os.path.dirname(cp))
        assert save_to_cache(cp, [], {}) is True
        assert os.path.isfile(cp)


# ---------------------------------------------------------------------------
# TestBypass
# ---------------------------------------------------------------------------


class TestBypass:
    """HOOKIFY_NO_CACHE env var controls bypass behavior."""

    @pytest.mark.parametrize("value", ["1", "true", "True", "TRUE", "yes", "YES", "on", "ON"])
    def test_bypass_enabled_for_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("HOOKIFY_NO_CACHE", value)
        assert is_bypass_enabled() is True

    def test_bypass_disabled_when_unset(self, monkeypatch):
        monkeypatch.delenv("HOOKIFY_NO_CACHE", raising=False)
        assert is_bypass_enabled() is False

    @pytest.mark.parametrize("value", ["0", "false", "no", "off", "", "random"])
    def test_bypass_disabled_for_non_truthy_values(self, monkeypatch, value):
        monkeypatch.setenv("HOOKIFY_NO_CACHE", value)
        assert is_bypass_enabled() is False
