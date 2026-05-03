"""Integration tests for cache-backed load_rules() in config_loader.

Verifies that load_rules() creates a cache, respects HOOKIFY_NO_CACHE,
and invalidates when rule files change or are added.
"""

import os
import time

from core.config_loader import load_rules
from tests.conftest import write_rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_claude_dir(env):
    return env["project"] / ".claude"


def _setup_plugin_root(tmp_path, monkeypatch):
    """Set CLAUDE_PLUGIN_ROOT to a fresh directory and return the cache dir."""
    plugin_root = tmp_path / "plugin_root"
    plugin_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    return plugin_root / ".cache"


# ---------------------------------------------------------------------------
# TestFirstLoadCreatesCache
# ---------------------------------------------------------------------------


class TestFirstLoadCreatesCache:
    """load_rules() should create a cache file under PLUGIN_ROOT/.cache/."""

    def test_first_load_creates_cache(self, isolated_env, tmp_path, monkeypatch):
        cache_dir = _setup_plugin_root(tmp_path, monkeypatch)

        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.test-rule.local.md",
            {"name": "test-rule", "enabled": True, "event": "bash", "pattern": "rm -rf"},
            body="Don't rm -rf!",
        )

        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "test-rule"

        # Cache directory and file should exist
        assert cache_dir.exists()
        cache_files = list(cache_dir.glob("*.json"))
        assert len(cache_files) == 1


# ---------------------------------------------------------------------------
# TestBypassSkipsCache
# ---------------------------------------------------------------------------


class TestBypassSkipsCache:
    """HOOKIFY_NO_CACHE=1 should prevent cache creation."""

    def test_bypass_skips_cache(self, isolated_env, tmp_path, monkeypatch):
        cache_dir = _setup_plugin_root(tmp_path, monkeypatch)
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "1")

        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.test-rule.local.md",
            {"name": "test-rule", "enabled": True, "event": "bash", "pattern": "rm -rf"},
            body="Don't rm -rf!",
        )

        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "test-rule"

        # No cache file should have been created
        assert not cache_dir.exists()


# ---------------------------------------------------------------------------
# TestCacheInvalidatesOnFileChange
# ---------------------------------------------------------------------------


class TestCacheInvalidatesOnFileChange:
    """Modifying a rule file's content must cause the cache to invalidate."""

    def test_cache_invalidates_on_file_change(self, isolated_env, tmp_path, monkeypatch):
        _setup_plugin_root(tmp_path, monkeypatch)
        claude_dir = _project_claude_dir(isolated_env)

        # Write original rule with pattern "OLD"
        rule_path = write_rule(
            claude_dir,
            "hookify.mutable.local.md",
            {"name": "mutable", "enabled": True, "event": "bash", "pattern": "OLD"},
            body="Old body.",
        )

        # First load — populates cache
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].pattern == "OLD"

        # Overwrite with pattern "NEW" and ensure mtime changes
        time.sleep(0.05)
        write_rule(
            claude_dir,
            "hookify.mutable.local.md",
            {"name": "mutable", "enabled": True, "event": "bash", "pattern": "NEW"},
            body="New body.",
        )
        os.utime(str(rule_path), None)  # bump mtime to now

        # Second load — cache should be invalidated
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].pattern == "NEW"
        assert rules[0].message == "New body."


# ---------------------------------------------------------------------------
# TestCacheInvalidatesOnFileAdded
# ---------------------------------------------------------------------------


class TestCacheInvalidatesOnFileAdded:
    """Adding a new rule file must invalidate the cache."""

    def test_cache_invalidates_on_file_added(self, isolated_env, tmp_path, monkeypatch):
        _setup_plugin_root(tmp_path, monkeypatch)
        claude_dir = _project_claude_dir(isolated_env)

        # Write first rule
        write_rule(
            claude_dir,
            "hookify.first-rule.local.md",
            {"name": "first-rule", "enabled": True, "event": "bash", "pattern": "echo"},
            body="First rule.",
        )

        # First load — populates cache
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "first-rule"

        # Add a second rule file
        time.sleep(0.05)
        write_rule(
            claude_dir,
            "hookify.second-rule.local.md",
            {"name": "second-rule", "enabled": True, "event": "file", "pattern": "TODO"},
            body="Second rule.",
        )

        # Second load — both rules should be returned
        rules = load_rules()
        names = {r.name for r in rules}
        assert names == {"first-rule", "second-rule"}
