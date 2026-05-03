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


CACHE_MIN_RULES = 5


def _project_claude_dir(env):
    return env["project"] / ".claude"


def _setup_plugin_root(tmp_path, monkeypatch):
    """Set CLAUDE_PLUGIN_ROOT to a fresh directory and return the cache dir."""
    plugin_root = tmp_path / "plugin_root"
    plugin_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    return plugin_root / ".cache"


def _write_n_rules(claude_dir, n):
    """Write n rule files so we exceed the CACHE_MIN_RULES threshold."""
    paths = []
    for i in range(n):
        paths.append(
            write_rule(
                claude_dir,
                f"hookify.rule-{i:02d}.local.md",
                {"name": f"rule-{i:02d}", "enabled": True, "event": "bash", "pattern": f"pat-{i}"},
                body=f"Rule {i} body.",
            )
        )
    return paths


# ---------------------------------------------------------------------------
# TestFirstLoadCreatesCache
# ---------------------------------------------------------------------------


class TestFirstLoadCreatesCache:
    """load_rules() should create a cache file under PLUGIN_ROOT/.cache/."""

    def test_first_load_creates_cache(self, isolated_env, tmp_path, monkeypatch):
        cache_dir = _setup_plugin_root(tmp_path, monkeypatch)
        _write_n_rules(_project_claude_dir(isolated_env), CACHE_MIN_RULES)

        rules = load_rules()
        assert len(rules) == CACHE_MIN_RULES

        # Cache directory and file should exist
        assert cache_dir.exists()
        cache_files = list(cache_dir.glob("*.json"))
        assert len(cache_files) == 1

    def test_below_threshold_skips_cache(self, isolated_env, tmp_path, monkeypatch):
        cache_dir = _setup_plugin_root(tmp_path, monkeypatch)
        _write_n_rules(_project_claude_dir(isolated_env), CACHE_MIN_RULES - 1)

        rules = load_rules()
        assert len(rules) == CACHE_MIN_RULES - 1

        # Cache should NOT be created for small rule sets
        assert not cache_dir.exists()


# ---------------------------------------------------------------------------
# TestBypassSkipsCache
# ---------------------------------------------------------------------------


class TestBypassSkipsCache:
    """HOOKIFY_NO_CACHE=1 should prevent cache creation."""

    def test_bypass_skips_cache(self, isolated_env, tmp_path, monkeypatch):
        cache_dir = _setup_plugin_root(tmp_path, monkeypatch)
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "1")
        _write_n_rules(_project_claude_dir(isolated_env), CACHE_MIN_RULES)

        rules = load_rules()
        assert len(rules) == CACHE_MIN_RULES

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

        # Write enough rules to exceed threshold
        paths = _write_n_rules(claude_dir, CACHE_MIN_RULES)

        # First load — populates cache
        rules = load_rules()
        assert len(rules) == CACHE_MIN_RULES
        mutable = [r for r in rules if r.name == "rule-00"][0]
        assert mutable.pattern == "pat-0"

        # Overwrite first rule with new pattern and ensure mtime changes
        time.sleep(0.05)
        write_rule(
            claude_dir,
            "hookify.rule-00.local.md",
            {"name": "rule-00", "enabled": True, "event": "bash", "pattern": "CHANGED"},
            body="Changed body.",
        )
        os.utime(str(paths[0]), None)

        # Second load — cache should be invalidated
        rules = load_rules()
        changed = [r for r in rules if r.name == "rule-00"][0]
        assert changed.pattern == "CHANGED"
        assert changed.message == "Changed body."


# ---------------------------------------------------------------------------
# TestCacheInvalidatesOnFileAdded
# ---------------------------------------------------------------------------


class TestCacheInvalidatesOnFileAdded:
    """Adding a new rule file must invalidate the cache."""

    def test_cache_invalidates_on_file_added(self, isolated_env, tmp_path, monkeypatch):
        _setup_plugin_root(tmp_path, monkeypatch)
        claude_dir = _project_claude_dir(isolated_env)

        # Write enough rules to exceed threshold
        _write_n_rules(claude_dir, CACHE_MIN_RULES)

        # First load — populates cache
        rules = load_rules()
        assert len(rules) == CACHE_MIN_RULES

        # Add one more rule file
        time.sleep(0.05)
        write_rule(
            claude_dir,
            "hookify.extra-rule.local.md",
            {"name": "extra-rule", "enabled": True, "event": "file", "pattern": "TODO"},
            body="Extra rule.",
        )

        # Second load — new rule should be included
        rules = load_rules()
        names = {r.name for r in rules}
        assert "extra-rule" in names
        assert len(rules) == CACHE_MIN_RULES + 1
