"""Tests for Bug #2 fix: CWD/global rule loading in config_loader.load_rules().

Covers project-only, global-only, merged, override, disabled-rule suppression,
and edge cases per docs/plans/2026-05-03-spec-cwd-global-rules.md.
"""

from core.config_loader import load_rules
from tests.conftest import write_rule

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _project_claude_dir(env):
    """Return the .claude directory inside the project."""
    return env["project"] / ".claude"


def _global_claude_dir(env):
    """Return the .claude directory inside the fake $HOME."""
    return env["home"] / ".claude"


# ---------------------------------------------------------------------------
# TestProjectScopeStillWorks
# ---------------------------------------------------------------------------


class TestProjectScopeStillWorks:
    """Project-only rules load; no rules anywhere returns empty."""

    def test_project_rule_loads(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.no-rm.local.md",
            {"name": "no-rm", "enabled": True, "event": "bash", "pattern": "rm -rf"},
            body="Do not run rm -rf.",
        )
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "no-rm"
        assert rules[0].message == "Do not run rm -rf."

    def test_no_rules_anywhere_returns_empty(self, isolated_env):
        rules = load_rules()
        assert rules == []

    def test_multiple_project_rules_load(self, isolated_env):
        d = _project_claude_dir(isolated_env)
        write_rule(d, "hookify.alpha.local.md", {"name": "alpha", "enabled": True, "event": "all"})
        write_rule(d, "hookify.beta.local.md", {"name": "beta", "enabled": True, "event": "all"})
        rules = load_rules()
        names = {r.name for r in rules}
        assert names == {"alpha", "beta"}


# ---------------------------------------------------------------------------
# TestGlobalScopeLoads
# ---------------------------------------------------------------------------


class TestGlobalScopeLoads:
    """Global rules load from ~/.claude/ regardless of CWD."""

    def test_global_rule_loads_from_project_cwd(self, isolated_env):
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.global-warn.local.md",
            {"name": "global-warn", "enabled": True, "event": "all"},
            body="Global warning.",
        )
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "global-warn"
        assert rules[0].message == "Global warning."

    def test_both_project_and_global_rules_load(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.proj-rule.local.md",
            {"name": "proj-rule", "enabled": True, "event": "bash"},
            body="Project rule body.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.global-rule.local.md",
            {"name": "global-rule", "enabled": True, "event": "bash"},
            body="Global rule body.",
        )
        rules = load_rules()
        names = {r.name for r in rules}
        assert names == {"proj-rule", "global-rule"}


# ---------------------------------------------------------------------------
# TestProjectOverridesGlobal
# ---------------------------------------------------------------------------


class TestProjectOverridesGlobal:
    """Project rule wins when names match; message body confirms the right one."""

    def test_project_overrides_global_same_name(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.dangerous-rm.local.md",
            {"name": "dangerous-rm", "enabled": True, "event": "bash", "pattern": "rm"},
            body="Project version of the rule.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.dangerous-rm.local.md",
            {"name": "dangerous-rm", "enabled": True, "event": "bash", "pattern": "rm"},
            body="Global version of the rule.",
        )
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "dangerous-rm"
        assert rules[0].message == "Project version of the rule."

    def test_override_only_affects_matching_name(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.shared.local.md",
            {"name": "shared", "enabled": True, "event": "all"},
            body="Project shared.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.shared.local.md",
            {"name": "shared", "enabled": True, "event": "all"},
            body="Global shared.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.unique-global.local.md",
            {"name": "unique-global", "enabled": True, "event": "all"},
            body="Only in global.",
        )
        rules = load_rules()
        names = {r.name for r in rules}
        assert names == {"shared", "unique-global"}
        shared = [r for r in rules if r.name == "shared"][0]
        assert shared.message == "Project shared."


# ---------------------------------------------------------------------------
# TestDisabledProjectSuppressesGlobal
# ---------------------------------------------------------------------------


class TestDisabledProjectSuppressesGlobal:
    """Disabled project rule with matching name blocks global; no-match is no-op."""

    def test_disabled_project_suppresses_matching_global(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.dangerous-rm.local.md",
            {"name": "dangerous-rm", "enabled": False, "event": "bash"},
            body="Disabled locally.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.dangerous-rm.local.md",
            {"name": "dangerous-rm", "enabled": True, "event": "bash"},
            body="Global version.",
        )
        rules = load_rules()
        assert len(rules) == 0

    def test_disabled_project_no_global_match_is_noop(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.only-local.local.md",
            {"name": "only-local", "enabled": False, "event": "all"},
            body="Disabled local, no global counterpart.",
        )
        rules = load_rules()
        assert len(rules) == 0

    def test_disabled_project_does_not_affect_other_global_rules(self, isolated_env):
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.suppress-this.local.md",
            {"name": "suppress-this", "enabled": False, "event": "all"},
            body="Disabled.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.suppress-this.local.md",
            {"name": "suppress-this", "enabled": True, "event": "all"},
            body="Global suppressed.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.keep-this.local.md",
            {"name": "keep-this", "enabled": True, "event": "all"},
            body="Global kept.",
        )
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "keep-this"

    def test_disabled_global_rule_is_noop(self, isolated_env):
        """A global rule with enabled: false simply doesn't fire (no special handling)."""
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.disabled-global.local.md",
            {"name": "disabled-global", "enabled": False, "event": "all"},
            body="Disabled global.",
        )
        rules = load_rules()
        assert len(rules) == 0


# ---------------------------------------------------------------------------
# TestEdgeCases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """CWD == $HOME, missing dirs, event filter across scopes."""

    def test_cwd_equals_home_loads_rules_once(self, isolated_home):
        """When CWD == $HOME, rules load exactly once (no duplicates)."""
        d = isolated_home / ".claude"
        write_rule(
            d,
            "hookify.home-rule.local.md",
            {"name": "home-rule", "enabled": True, "event": "all"},
            body="Home rule.",
        )
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "home-rule"

    def test_missing_global_claude_dir(self, isolated_env):
        """Missing ~/.claude/ — project-only load works."""
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.proj.local.md",
            {"name": "proj", "enabled": True, "event": "all"},
            body="Project only.",
        )
        # Ensure ~/.claude/ does NOT exist
        global_dir = isolated_env["home"] / ".claude"
        assert not global_dir.exists()
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "proj"

    def test_missing_project_claude_dir(self, isolated_env):
        """Missing <cwd>/.claude/ — global-only load works."""
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.glob.local.md",
            {"name": "glob", "enabled": True, "event": "all"},
            body="Global only.",
        )
        # Ensure <cwd>/.claude/ does NOT exist
        project_dir = isolated_env["project"] / ".claude"
        assert not project_dir.exists()
        rules = load_rules()
        assert len(rules) == 1
        assert rules[0].name == "glob"

    def test_event_filter_applies_across_both_scopes(self, isolated_env):
        """Event filter works for project and global rules alike."""
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.proj-bash.local.md",
            {"name": "proj-bash", "enabled": True, "event": "bash"},
            body="Project bash rule.",
        )
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.proj-file.local.md",
            {"name": "proj-file", "enabled": True, "event": "file"},
            body="Project file rule.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.glob-bash.local.md",
            {"name": "glob-bash", "enabled": True, "event": "bash"},
            body="Global bash rule.",
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.glob-stop.local.md",
            {"name": "glob-stop", "enabled": True, "event": "stop"},
            body="Global stop rule.",
        )

        bash_rules = load_rules(event="bash")
        assert {r.name for r in bash_rules} == {"proj-bash", "glob-bash"}

        file_rules = load_rules(event="file")
        assert {r.name for r in file_rules} == {"proj-file"}

        stop_rules = load_rules(event="stop")
        assert {r.name for r in stop_rules} == {"glob-stop"}

    def test_event_all_matches_any_filter(self, isolated_env):
        """A rule with event: all should match any event filter."""
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.catch-all.local.md",
            {"name": "catch-all", "enabled": True, "event": "all"},
            body="Catch all.",
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1
        assert rules[0].name == "catch-all"

    def test_no_event_filter_returns_all_enabled(self, isolated_env):
        """Calling load_rules() with no event returns all enabled rules."""
        write_rule(
            _project_claude_dir(isolated_env),
            "hookify.a.local.md",
            {"name": "a", "enabled": True, "event": "bash"},
        )
        write_rule(
            _global_claude_dir(isolated_env),
            "hookify.b.local.md",
            {"name": "b", "enabled": True, "event": "stop"},
        )
        rules = load_rules()
        assert {r.name for r in rules} == {"a", "b"}
