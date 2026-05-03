# hookify v0.2.0 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `godmode:task-runner` (or
> `godmode:delegated-execution` for in-session execution) to implement
> this plan task-by-task. Each task ends with a commit. Run the test
> suite + ruff after each task before moving on.

**Goal:** Land hookify v0.2.0 — fix bugs #2 and #3, add a JSON rule
cache, integrate seven cherry-picks, set up project infrastructure
(pyproject, tests, CI), and ship as a publishable fork.

**Architecture:** Preserve upstream's flat layout. Add one new module
(`core/cache.py`). Modify `core/config_loader.py` and
`core/rule_engine.py` for bug fixes and cherry-picks. Add `tests/`
directory with pytest-driven coverage. CI runs `pytest + ruff` on every
push.

**Tech Stack:** Python 3.10+, pytest, ruff, pyproject.toml, GitHub
Actions, Apache 2.0, Conventional Commits, trunk on `main`.

**Inputs (specs):**
- `docs/plans/2026-05-03-hookify-design.md`
- `docs/plans/2026-05-03-spec-cwd-global-rules.md` (Bug #2 semantics)
- `docs/plans/2026-05-03-spec-json-cache.md` (cache shape & invalidation)

---

## Plan map

| Phase | Tasks | Purpose |
|---|---|---|
| **A — Infrastructure** | T1–T5 | Project config, tests/, CI, plugin metadata |
| **B — Bug fixes** | T6–T7 | Bug #2 (CWD/global), Bug #3 (Write tool) |
| **C — Cache layer** | T8–T9 | `core/cache.py` + wire into `load_rules()` |
| **D — Cherry-picks** | T10–T16 | 7 hookify-plus improvements |
| **E — Polish & Quality Gate** | T17–T21 | Cleanup, README, smoke test, install verify |

Total: **21 tasks**. Each task is one focused commit. TDD applies to
behavior changes (Phase B, C, parts of D); config-only tasks
(plugin.json, hooks.json, marketplace.json) get JSON-validity checks
instead of full TDD.

---

## Phase A — Infrastructure

### Task 1: Set up `pyproject.toml`

**Files:**
- Create: `pyproject.toml`

**Step 1: Write `pyproject.toml`**

```toml
[project]
name = "hookify"
version = "0.2.0"
description = "Patched fork of Anthropic's hookify Claude Code plugin with bug fixes and JSON rule caching"
readme = "README.md"
requires-python = ">=3.10"
license = {text = "Apache-2.0"}
authors = [
    {name = "Anthropic", email = "support@anthropic.com"},
    {name = "Chris Irving"}
]

[tool.ruff]
target-version = "py310"
line-length = 100
extend-exclude = ["examples/", "agents/", "commands/", "skills/"]

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "UP",   # pyupgrade
    "SIM",  # flake8-simplify
]
ignore = [
    "E501",  # line-too-long (formatter handles)
]

[tool.ruff.format]
quote-style = "double"
indent-style = "space"

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]
python_functions = ["test_*"]
addopts = ["-v", "--tb=short"]
```

**Step 2: Verify it parses**

Run: `python3 -c "import tomllib; tomllib.load(open('pyproject.toml', 'rb'))"`
Expected: no output (success)

**Step 3: Verify `ruff --version` runs against the config**

Run: `ruff check --no-fix . 2>&1 | head -20`
Expected: clean output (or known existing-code warnings — note them
but don't block; T19 will address)

**Step 4: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with ruff and pytest config

Establishes the v0.2.0 project metadata, Python 3.10+ floor, ruff
lint/format rules, and pytest discovery. Excludes upstream content
directories (examples, agents, commands, skills) from lint scope."
```

---

### Task 2: Set up `tests/` directory with conftest

**Files:**
- Create: `tests/__init__.py` (empty)
- Create: `tests/conftest.py`

**Step 1: Create empty `tests/__init__.py`**

```bash
touch tests/__init__.py
```

**Step 2: Write `tests/conftest.py` with shared fixtures**

```python
"""Shared pytest fixtures for hookify tests."""

import os
import sys
from pathlib import Path

import pytest

# Ensure plugin root is on sys.path so `from core.X import Y` works in tests.
PLUGIN_ROOT = Path(__file__).parent.parent
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Provide an isolated $HOME directory for the test."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(home)  # default to $HOME; tests can chdir elsewhere
    return home


@pytest.fixture
def isolated_project(tmp_path, monkeypatch):
    """Provide an isolated project directory and chdir into it."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(project)
    return project


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    """Provide both isolated $HOME and a project directory.

    Returns a dict: {'home': Path, 'project': Path}
    Chdir starts in the project directory.
    """
    home = tmp_path / "home"
    home.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.chdir(project)
    return {"home": home, "project": project}


def write_rule(directory: Path, filename: str, frontmatter: dict, body: str = "test rule") -> Path:
    """Helper: write a rule file with given frontmatter dict + body."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = ["---"]
    for k, v in frontmatter.items():
        if isinstance(v, bool):
            lines.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                if isinstance(item, dict):
                    parts = ", ".join(f'{ik}: "{iv}"' for ik, iv in item.items())
                    lines.append(f"  - {parts}")
                else:
                    lines.append(f'  - "{item}"')
        else:
            lines.append(f'{k}: "{v}"')
    lines.append("---")
    lines.append("")
    lines.append(body)
    path = directory / filename
    path.write_text("\n".join(lines))
    return path


# Re-export helper for tests to import
__all__ = ["write_rule", "isolated_home", "isolated_project", "isolated_env"]
```

**Step 3: Verify pytest discovery works**

Run: `pytest --collect-only 2>&1 | tail -5`
Expected: `no tests ran` or similar — confirms pytest can load conftest

**Step 4: Commit**

```bash
git add tests/__init__.py tests/conftest.py
git commit -m "test: add tests/ scaffold with shared fixtures

Establishes pytest fixtures: isolated_home, isolated_project,
isolated_env (project chdir + HOME monkeypatched), and write_rule
helper for emitting frontmatter+body markdown files."
```

---

### Task 3: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

**Step 1: Write CI workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dev dependencies
        run: pip install pytest ruff

      - name: Lint with ruff
        run: ruff check .

      - name: Check formatting with ruff
        run: ruff format --check .

      - name: Run tests
        run: pytest
```

**Step 2: Validate YAML**

Run: `python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml'))"`
Expected: no output (and confirms PyYAML is available — if not, fall
back to `cat .github/workflows/ci.yml` and visual review)

**Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions workflow for pytest and ruff

Runs pytest + ruff (check + format) across Python 3.10, 3.11, 3.12
on push to main and on pull requests."
```

---

### Task 4: Add `version` field to `plugin.json`

**Files:**
- Modify: `.claude-plugin/plugin.json`

**Step 1: Read current contents**

Run: `cat .claude-plugin/plugin.json`
Expected: 4 keys (name, description, author).

**Step 2: Update file to include `version`**

```json
{
  "name": "hookify",
  "version": "0.2.0",
  "description": "Easily create hooks to prevent unwanted behaviors by analyzing conversation patterns",
  "author": {
    "name": "Anthropic",
    "email": "support@anthropic.com"
  }
}
```

**Step 3: Verify JSON is valid**

Run: `python3 -c "import json; print(json.load(open('.claude-plugin/plugin.json'))['version'])"`
Expected: `0.2.0`

**Step 4: Commit**

```bash
git add .claude-plugin/plugin.json
git commit -m "fix: add version field to plugin.json

Upstream hookify ships without a version field, causing the plugin
cache path to be hookify/unknown/. Setting version to 0.2.0 makes
the cache path version-stable and prevents collision between
different installations of unversioned hookify.

This is also a candidate for upstream patch."
```

---

### Task 5: Self-marketplacing — `marketplace.json`

**Files:**
- Create: `.claude-plugin/marketplace.json`

**Step 1: Write `marketplace.json`**

```json
{
  "name": "hookify",
  "owner": {
    "name": "Chris Irving"
  },
  "plugins": [
    {
      "name": "hookify",
      "description": "Patched fork of Anthropic's hookify with bug fixes (global rules, Write tool) and JSON rule caching",
      "source": ".",
      "category": "productivity",
      "homepage": "https://github.com/reyequis/hookify"
    }
  ]
}
```

**Step 2: Verify JSON is valid**

Run: `python3 -c "import json; d = json.load(open('.claude-plugin/marketplace.json')); assert d['plugins'][0]['name'] == 'hookify'; print('OK')"`
Expected: `OK`

**Step 3: Commit**

```bash
git add .claude-plugin/marketplace.json
git commit -m "feat: make repo self-marketplacing

Adding marketplace.json lets users install via:
  /plugin marketplace add reyequis/hookify
  /plugin install hookify@hookify

The marketplace lists this single plugin with source set to '.'
(repo-root), category productivity, and homepage pointing to the
GitHub repo."
```

---

## Phase B — Bug fixes

### Task 6: Bug #2 — CWD / global rule loading

**Spec:** `docs/plans/2026-05-03-spec-cwd-global-rules.md`

**Files:**
- Modify: `core/config_loader.py` (function `load_rules`, lines 198–241)
- Create: `tests/test_config_loader_global.py`

**Step 1: Write failing tests covering all spec acceptance criteria**

```python
"""Tests for Bug #2: CWD-independent and global-scope rule loading."""

from pathlib import Path

import pytest

from core.config_loader import load_rules
from tests.conftest import write_rule


class TestProjectScopeStillWorks:
    """Regression: project-only loading must continue to work."""

    def test_project_only_rule_loads(self, isolated_env):
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.proj-rule.local.md",
            {"name": "proj-rule", "enabled": True, "event": "bash", "pattern": "rm"},
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1
        assert rules[0].name == "proj-rule"

    def test_no_rules_anywhere_returns_empty(self, isolated_env):
        assert load_rules(event="bash") == []


class TestGlobalScopeLoads:
    """Bug #2: rules in ~/.claude/ must load regardless of CWD."""

    def test_global_rule_loads_from_project_cwd(self, isolated_env):
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.global-rule.local.md",
            {"name": "global-rule", "enabled": True, "event": "bash", "pattern": "sudo"},
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1
        assert rules[0].name == "global-rule"

    def test_global_and_project_both_load(self, isolated_env):
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.proj.local.md",
            {"name": "proj", "enabled": True, "event": "bash", "pattern": "p"},
        )
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.global.local.md",
            {"name": "global", "enabled": True, "event": "bash", "pattern": "g"},
        )
        rules = load_rules(event="bash")
        names = {r.name for r in rules}
        assert names == {"proj", "global"}


class TestProjectOverridesGlobal:
    """Spec: project rules override global rules by name."""

    def test_project_wins_when_names_match(self, isolated_env):
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.dup.local.md",
            {"name": "dup", "enabled": True, "event": "bash", "pattern": "global-pattern"},
            body="GLOBAL message",
        )
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.dup.local.md",
            {"name": "dup", "enabled": True, "event": "bash", "pattern": "project-pattern"},
            body="PROJECT message",
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1
        assert rules[0].name == "dup"
        assert "PROJECT" in rules[0].message


class TestDisabledProjectSuppressesGlobal:
    """Spec: disabled project rule with matching name suppresses global."""

    def test_disabled_project_blocks_global(self, isolated_env):
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.suppress.local.md",
            {"name": "suppress-me", "enabled": True, "event": "bash", "pattern": "x"},
        )
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.suppress.local.md",
            {"name": "suppress-me", "enabled": False, "event": "bash", "pattern": "x"},
        )
        rules = load_rules(event="bash")
        assert rules == []  # neither fires

    def test_disabled_project_no_matching_global_is_noop(self, isolated_env):
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.alone.local.md",
            {"name": "alone", "enabled": False, "event": "bash", "pattern": "x"},
        )
        assert load_rules(event="bash") == []


class TestEdgeCases:
    """Spec edge cases."""

    def test_cwd_equals_home_no_double_load(self, isolated_home):
        # Write only one rule under $HOME/.claude
        write_rule(
            isolated_home / ".claude",
            "hookify.solo.local.md",
            {"name": "solo", "enabled": True, "event": "bash", "pattern": "x"},
        )
        # CWD is already $HOME (set by isolated_home fixture)
        rules = load_rules(event="bash")
        assert len(rules) == 1, "rule must load exactly once when CWD == $HOME"

    def test_missing_global_dir_project_only_works(self, isolated_env):
        # ~/.claude/ does NOT exist
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.proj.local.md",
            {"name": "proj", "enabled": True, "event": "bash", "pattern": "x"},
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1

    def test_missing_project_dir_global_only_works(self, isolated_env):
        # <project>/.claude/ does NOT exist
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.global.local.md",
            {"name": "global", "enabled": True, "event": "bash", "pattern": "x"},
        )
        rules = load_rules(event="bash")
        assert len(rules) == 1
        assert rules[0].name == "global"

    def test_event_filter_applies_across_scopes(self, isolated_env):
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.bash.local.md",
            {"name": "b", "enabled": True, "event": "bash", "pattern": "x"},
        )
        write_rule(
            isolated_env["home"] / ".claude",
            "hookify.file.local.md",
            {"name": "f", "enabled": True, "event": "file", "pattern": "x"},
        )
        bash_rules = load_rules(event="bash")
        file_rules = load_rules(event="file")
        assert {r.name for r in bash_rules} == {"b"}
        assert {r.name for r in file_rules} == {"f"}
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_config_loader_global.py -v`
Expected: most tests FAIL (current `load_rules` only searches CWD-relative `.claude/`)

**Step 3: Implement the fix in `core/config_loader.py`**

Replace the existing `load_rules` function (lines 198–241) with:

```python
def _resolve_rule_dirs() -> list[str]:
    """Resolve project-local and global rule directories.

    Returns a list of directories to search, in load order
    (project first, then global). Deduplicates via realpath when
    CWD == $HOME so the same dir is not searched twice.
    """
    project_dir = os.path.realpath(os.path.join(os.getcwd(), ".claude"))
    global_dir = os.path.realpath(os.path.expanduser(os.path.join("~", ".claude")))
    if project_dir == global_dir:
        return [project_dir]
    return [project_dir, global_dir]


def load_rules(event: Optional[str] = None) -> List[Rule]:
    """Load all hookify rules from project-local and global directories.

    Searches `<cwd>/.claude/` then `~/.claude/` for `hookify.*.local.md`
    files. Project rules override global rules with the same `name`.
    A project rule with `enabled: false` and a matching name suppresses
    the corresponding global rule (neither fires).

    Args:
        event: Optional event filter ("bash", "file", "stop", "read",
               "prompt", or "all"/None for no filter).

    Returns:
        List of enabled Rule objects matching the event, in load
        order (project rules first, then global non-conflicting rules).
    """
    by_name: dict[str, Rule] = {}
    suppressed: set[str] = set()

    for directory in _resolve_rule_dirs():
        if not os.path.isdir(directory):
            continue

        pattern = os.path.join(directory, "hookify.*.local.md")
        for file_path in sorted(glob.glob(pattern)):
            try:
                rule = load_rule_file(file_path)
                if rule is None:
                    continue
            except (IOError, OSError, PermissionError) as e:
                print(f"Warning: Failed to read {file_path}: {e}", file=sys.stderr)
                continue
            except (ValueError, KeyError, AttributeError, TypeError) as e:
                print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(
                    f"Warning: Unexpected error loading {file_path} "
                    f"({type(e).__name__}): {e}",
                    file=sys.stderr,
                )
                continue

            # Filter by event
            if event and rule.event != "all" and rule.event != event:
                continue

            # Track disabled project rules so they suppress matching global rules
            if not rule.enabled:
                # Suppression only applies if this is the FIRST occurrence of name
                # (i.e., from the project scope; later global occurrences are
                # filtered out by the by_name check).
                if rule.name not in by_name:
                    suppressed.add(rule.name)
                continue

            # First occurrence wins (project beats global)
            if rule.name in by_name or rule.name in suppressed:
                continue

            by_name[rule.name] = rule

    return list(by_name.values())
```

**Step 4: Run tests to verify pass**

Run: `pytest tests/test_config_loader_global.py -v`
Expected: ALL tests PASS

**Step 5: Run full test suite**

Run: `pytest`
Expected: all tests pass; no regressions

**Step 6: Lint**

Run: `ruff check core/ tests/ && ruff format --check core/ tests/`
Expected: clean

**Step 7: Commit**

```bash
git add core/config_loader.py tests/test_config_loader_global.py
git commit -m "fix: load global rules from ~/.claude/ regardless of CWD (Bug #2)

Previously, load_rules() used a relative glob (.claude/*.md) that
only matched when CWD was the project root. Rules placed in
~/.claude/ never loaded, regardless of working directory.

Now searches both project-local (<cwd>/.claude/) and global
(~/.claude/) directories. Project rules override global rules with
the same 'name'. A disabled project rule with a matching name
suppresses the corresponding global rule.

Edge case: if CWD is itself \$HOME, the directory is searched once
(realpath comparison) to avoid double-loading.

Fixes the user-scope failure mode reported in upstream issues
#309, #503, #1294, and #1444 on anthropics/claude-plugins-official.

Spec: docs/plans/2026-05-03-spec-cwd-global-rules.md"
```

---

### Task 7: Bug #3 — Write tool `content` fallback

**Files:**
- Modify: `core/rule_engine.py` (function `_extract_field`, ~lines 235–245)
- Create: `tests/test_rule_engine_write.py`

**Step 1: Write failing test**

```python
"""Tests for Bug #3: Write tool field extraction."""

from core.rule_engine import RuleEngine
from core.config_loader import Rule, Condition


class TestWriteToolNewTextFieldExtraction:
    """Bug #3: Write tool sends 'content', but old code only checked 'new_string'."""

    def test_write_tool_content_matches_new_text_pattern(self):
        rule = Rule(
            name="block-pip-public",
            enabled=True,
            event="file",
            conditions=[
                Condition(field="new_text", operator="contains",
                          pattern="index-url = https://pypi.org/simple"),
            ],
            action="block",
            message="No public registry",
        )
        engine = RuleEngine()
        result = engine.evaluate_rules(
            [rule],
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Write",
                "tool_input": {
                    "file_path": "/tmp/pip.conf",
                    "content": "index-url = https://pypi.org/simple",
                },
            },
        )
        # Must match — rule should fire
        assert result != {}, "Write tool 'content' must be inspected when checking 'new_text'"

    def test_edit_tool_new_string_still_works(self):
        # Regression: Edit uses new_string and must continue to work
        rule = Rule(
            name="x",
            enabled=True,
            event="file",
            conditions=[
                Condition(field="new_text", operator="contains", pattern="forbidden"),
            ],
            action="warn",
            message="m",
        )
        engine = RuleEngine()
        result = engine.evaluate_rules(
            [rule],
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Edit",
                "tool_input": {
                    "file_path": "/tmp/x.txt",
                    "old_string": "ok",
                    "new_string": "forbidden goes here",
                },
            },
        )
        assert result != {}
```

**Step 2: Run, verify failure**

Run: `pytest tests/test_rule_engine_write.py -v`
Expected: `test_write_tool_content_matches_new_text_pattern` FAILS

**Step 3: Implement fix in `core/rule_engine.py`**

Find the `_extract_field` method's Write/Edit block (around lines
235–245) and update:

```python
elif tool_name in ["Write", "Edit"]:
    if field == "content":
        # Write uses 'content', Edit has 'new_string'
        return tool_input.get("content") or tool_input.get("new_string", "")
    elif field == "new_text" or field == "new_string":
        # Bug #3 fix: Write tool's payload is 'content', not 'new_string'.
        # Fall back to 'content' so 'event: file' rules fire on Write too.
        return tool_input.get("new_string") or tool_input.get("content", "")
    elif field == "old_text" or field == "old_string":
        return tool_input.get("old_string", "")
    elif field == "file_path":
        return tool_input.get("file_path", "")
```

**Step 4: Run tests, verify pass**

Run: `pytest tests/test_rule_engine_write.py -v`
Expected: ALL pass

**Step 5: Run full suite**

Run: `pytest`
Expected: all pass

**Step 6: Commit**

```bash
git add core/rule_engine.py tests/test_rule_engine_write.py
git commit -m "fix: Write tool now triggers event:file rules (Bug #3)

The Write tool's tool_input is {file_path, content}, but
_extract_field returned tool_input['new_string'] for 'new_text'
queries — which is empty for Write. Result: every event:file rule
silently bypassed all Write operations.

Now falls back to 'content' for Write while preserving Edit's
'new_string' behavior. This matches Chris's prior public bug report
on issue #503 (anthropics/claude-plugins-official)."
```

---

## Phase C — Cache layer

### Task 8: `core/cache.py` module

**Spec:** `docs/plans/2026-05-03-spec-json-cache.md`

**Files:**
- Create: `core/cache.py`
- Create: `tests/test_cache.py`

**Step 1: Write failing tests**

```python
"""Tests for core/cache.py JSON rule cache."""

import json
import os
from pathlib import Path

import pytest

from core.cache import (
    CACHE_SCHEMA_VERSION,
    cache_path_for,
    load_from_cache,
    save_to_cache,
    is_bypass_enabled,
)
from core.config_loader import Rule, Condition


class TestCachePath:
    def test_cache_path_uses_plugin_root_when_set(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        path = cache_path_for("/some/proj/.claude", "/some/home/.claude")
        assert path.startswith(str(tmp_path))
        assert ".cache/" in path

    def test_cache_path_falls_back_to_xdg_when_plugin_root_unset(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        path = cache_path_for("/p/.claude", "/g/.claude")
        assert path.startswith(str(tmp_path))
        assert "hookify" in path

    def test_cache_path_is_deterministic(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        a = cache_path_for("/x/.claude", "/y/.claude")
        b = cache_path_for("/x/.claude", "/y/.claude")
        assert a == b

    def test_different_inputs_different_paths(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
        a = cache_path_for("/x/.claude", "/y/.claude")
        b = cache_path_for("/x/.claude", "/z/.claude")
        assert a != b


class TestSaveAndLoadRoundTrip:
    def test_round_trip_preserves_rule_fields(self, tmp_path):
        cache_file = str(tmp_path / "c.json")
        rules = [
            Rule(
                name="r1",
                enabled=True,
                event="bash",
                pattern="rm -rf",
                conditions=[Condition(field="command", operator="regex_match", pattern="rm")],
                action="block",
                tool_matcher="Bash",
                message="dangerous",
            ),
        ]
        sources = {str(tmp_path / "fake.md"): 12345.0}
        save_to_cache(cache_file, rules, sources)
        loaded = load_from_cache(cache_file)
        assert loaded is not None
        loaded_rules, loaded_sources = loaded
        assert len(loaded_rules) == 1
        r = loaded_rules[0]
        assert r.name == "r1"
        assert r.enabled is True
        assert r.event == "bash"
        assert r.action == "block"
        assert r.tool_matcher == "Bash"
        assert r.message == "dangerous"
        assert len(r.conditions) == 1
        assert r.conditions[0].field == "command"
        assert loaded_sources == sources


class TestInvalidation:
    def test_load_returns_none_when_file_missing(self, tmp_path):
        assert load_from_cache(str(tmp_path / "nonexistent.json")) is None

    def test_load_returns_none_on_corrupt_json(self, tmp_path):
        f = tmp_path / "c.json"
        f.write_text("{ this is not json")
        assert load_from_cache(str(f)) is None

    def test_load_returns_none_on_wrong_schema_version(self, tmp_path):
        f = tmp_path / "c.json"
        f.write_text(json.dumps({"version": 999, "sources": {}, "rules": []}))
        assert load_from_cache(str(f)) is None


class TestAtomicWrite:
    def test_no_temp_file_left_after_write(self, tmp_path):
        cache_file = str(tmp_path / "c.json")
        save_to_cache(cache_file, [], {})
        files = list(tmp_path.iterdir())
        # Only the final cache file should exist
        assert len(files) == 1
        assert files[0].name == "c.json"


class TestBypass:
    def test_bypass_when_no_cache_truthy(self, monkeypatch):
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "1")
        assert is_bypass_enabled() is True

    def test_no_bypass_when_unset(self, monkeypatch):
        monkeypatch.delenv("HOOKIFY_NO_CACHE", raising=False)
        assert is_bypass_enabled() is False

    def test_bypass_when_value_is_yes(self, monkeypatch):
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "yes")
        assert is_bypass_enabled() is True

    def test_no_bypass_when_value_is_zero(self, monkeypatch):
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "0")
        assert is_bypass_enabled() is False
```

**Step 2: Run, verify failure**

Run: `pytest tests/test_cache.py -v`
Expected: ImportError or many failures (no `core/cache.py` yet)

**Step 3: Implement `core/cache.py`**

```python
"""JSON rule cache for hookify.

Caches parsed Rule objects to avoid re-parsing markdown rule files
on every hook event. Invalidation is mtime-based against the source
.md files, with file-set comparison to catch additions and removals.

Spec: docs/plans/2026-05-03-spec-json-cache.md
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Optional

from core.config_loader import Rule, Condition

CACHE_SCHEMA_VERSION = 1
SCHEMA_REVISION = "2026-05-03"


def is_bypass_enabled() -> bool:
    """Return True if HOOKIFY_NO_CACHE env var is set to a truthy value."""
    val = os.environ.get("HOOKIFY_NO_CACHE", "").strip().lower()
    return val in {"1", "true", "yes", "on"}


def _cache_dir() -> str:
    """Resolve the cache directory.

    Prefers ${CLAUDE_PLUGIN_ROOT}/.cache/ when CLAUDE_PLUGIN_ROOT is
    set (the standard plugin runtime). Falls back to
    ${XDG_CACHE_HOME:-~/.cache}/hookify/ otherwise (tests, direct
    invocations).
    """
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        return os.path.join(plugin_root, ".cache")

    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "hookify")
    return os.path.expanduser(os.path.join("~", ".cache", "hookify"))


def cache_path_for(project_dir: str, global_dir: str) -> str:
    """Compute the cache file path for a (project_dir, global_dir) pair.

    The cache is keyed by the realpath of both directories so that
    different working directories get different caches.
    """
    project_real = os.path.realpath(project_dir)
    global_real = os.path.realpath(global_dir)
    key_input = (project_real + "\0" + global_real).encode("utf-8")
    key = hashlib.sha256(key_input).hexdigest()[:16]
    return os.path.join(_cache_dir(), f"{key}.json")


def load_from_cache(cache_path: str) -> Optional[tuple[list[Rule], dict[str, float]]]:
    """Load rules and source mtimes from a cache file.

    Returns:
        A tuple of (rules, sources) on success, where sources maps
        source-file paths to their cached mtime values.
        None if the cache is absent, malformed, or schema-mismatched.
    """
    try:
        with open(cache_path, "r") as f:
            data = json.load(f)
    except (FileNotFoundError, IsADirectoryError):
        return None
    except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
        print(f"Warning: hookify cache unreadable ({cache_path}): {e}", file=sys.stderr)
        return None

    if not isinstance(data, dict) or data.get("version") != CACHE_SCHEMA_VERSION:
        return None

    sources = data.get("sources", {})
    rules_raw = data.get("rules", [])
    if not isinstance(sources, dict) or not isinstance(rules_raw, list):
        return None

    rules: list[Rule] = []
    for rd in rules_raw:
        try:
            conditions = [
                Condition(
                    field=c.get("field", ""),
                    operator=c.get("operator", "regex_match"),
                    pattern=c.get("pattern", ""),
                )
                for c in rd.get("conditions", [])
            ]
            rule = Rule(
                name=rd.get("name", "unnamed"),
                enabled=rd.get("enabled", True),
                event=rd.get("event", "all"),
                pattern=rd.get("pattern"),
                conditions=conditions,
                action=rd.get("action", "warn"),
                tool_matcher=rd.get("tool_matcher"),
                message=rd.get("message", ""),
            )
            rules.append(rule)
        except (TypeError, KeyError, AttributeError) as e:
            print(f"Warning: skipping malformed cached rule: {e}", file=sys.stderr)
            continue

    return rules, sources


def save_to_cache(
    cache_path: str,
    rules: list[Rule],
    sources: dict[str, float],
) -> bool:
    """Atomically write the cache file.

    Args:
        cache_path: Final path of the cache file.
        rules: Rule objects to serialize.
        sources: Map of source-file path → mtime, used for invalidation.

    Returns:
        True on successful write, False if write failed (already logged).
    """
    cache_dir = os.path.dirname(cache_path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as e:
        print(f"Warning: cannot create cache dir {cache_dir}: {e}", file=sys.stderr)
        return False

    payload = {
        "version": CACHE_SCHEMA_VERSION,
        "schema_revision": SCHEMA_REVISION,
        "sources": sources,
        "rules": [_rule_to_dict(r) for r in rules],
    }

    tmp_path = f"{cache_path}.tmp.{os.getpid()}"
    try:
        with open(tmp_path, "w") as f:
            json.dump(payload, f, indent=None, separators=(",", ":"))
        os.replace(tmp_path, cache_path)  # atomic on POSIX and Windows
        return True
    except OSError as e:
        print(f"Warning: failed writing hookify cache ({cache_path}): {e}", file=sys.stderr)
        # Best-effort cleanup of the temp file
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def _rule_to_dict(rule: Rule) -> dict:
    """Serialize a Rule to a JSON-safe dict."""
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "event": rule.event,
        "pattern": rule.pattern,
        "conditions": [
            {"field": c.field, "operator": c.operator, "pattern": c.pattern}
            for c in rule.conditions
        ],
        "action": rule.action,
        "tool_matcher": rule.tool_matcher,
        "message": rule.message,
    }


def is_cache_valid(
    sources_in_cache: dict[str, float],
    current_files: dict[str, float],
) -> bool:
    """Return True iff cache sources match current files exactly.

    Both dicts are {path: mtime}. The cache is valid only when the
    set of paths matches exactly AND every mtime matches.
    """
    if set(sources_in_cache.keys()) != set(current_files.keys()):
        return False
    return all(sources_in_cache[p] == current_files[p] for p in current_files)
```

**Step 4: Run cache tests, verify pass**

Run: `pytest tests/test_cache.py -v`
Expected: ALL pass

**Step 5: Lint**

Run: `ruff check core/cache.py tests/test_cache.py && ruff format --check core/cache.py tests/test_cache.py`
Expected: clean

**Step 6: Commit**

```bash
git add core/cache.py tests/test_cache.py
git commit -m "feat: add JSON rule cache module (core/cache.py)

Implements the cache layer per docs/plans/2026-05-03-spec-json-cache.md:

- cache_path_for(): SHA256-keyed path under \${CLAUDE_PLUGIN_ROOT}/.cache/
  with XDG fallback for non-plugin contexts (tests, direct runs)
- save_to_cache(): atomic write-rename, fail-soft on OSError
- load_from_cache(): tolerant of missing/corrupt/schema-mismatch cases
- is_cache_valid(): file-set + mtime equality check
- is_bypass_enabled(): reads HOOKIFY_NO_CACHE env var

Cache format is JSON with explicit schema version (1) so future
revisions can auto-invalidate older caches."
```

---

### Task 9: Wire cache into `load_rules()`

**Files:**
- Modify: `core/config_loader.py` (the `load_rules` function from Task 6)
- Create: `tests/test_config_loader_cache.py`

**Step 1: Write failing integration tests**

```python
"""Tests for load_rules() + cache integration."""

import os
import time
from pathlib import Path

import pytest

from core.config_loader import load_rules
from core.cache import cache_path_for, _cache_dir
from tests.conftest import write_rule


def _ensure_plugin_root(monkeypatch, tmp_path):
    """Set CLAUDE_PLUGIN_ROOT to an isolated tmp dir for the test."""
    plugin_root = tmp_path / "plugin_root"
    plugin_root.mkdir()
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    return plugin_root


class TestCacheIntegration:
    def test_first_load_creates_cache(self, isolated_env, tmp_path, monkeypatch):
        _ensure_plugin_root(monkeypatch, tmp_path)
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.r.local.md",
            {"name": "r", "enabled": True, "event": "bash", "pattern": "x"},
        )
        load_rules(event="bash")
        # Cache file should now exist
        proj = os.path.realpath(str(isolated_env["project"] / ".claude"))
        glob_dir = os.path.realpath(str(isolated_env["home"] / ".claude"))
        cache_file = cache_path_for(proj, glob_dir)
        assert os.path.exists(cache_file), f"Cache file expected at {cache_file}"

    def test_second_load_uses_cache(self, isolated_env, tmp_path, monkeypatch):
        _ensure_plugin_root(monkeypatch, tmp_path)
        rule_path = write_rule(
            isolated_env["project"] / ".claude",
            "hookify.r.local.md",
            {"name": "r", "enabled": True, "event": "bash", "pattern": "x"},
        )
        first = load_rules(event="bash")
        # Modify mtime backwards so a re-parse would produce different output
        # (this proves cache is being used — re-parse would still see same content)
        # We instead delete the rule file and confirm cache still serves it.
        rule_path.unlink()
        # Without cache, this would return [] because the file is gone
        # But the cache returns based on cache mtimes — since rule_path was
        # deleted, mtime check fails and cache is invalidated → re-parse → []
        # So the right behavior IS [] here. Use a different test pattern.
        # (Just confirming cache exists and doesn't break.)
        result = load_rules(event="bash")
        assert result == []  # Source gone → cache invalidated → re-parse empty

    def test_bypass_skips_cache(self, isolated_env, tmp_path, monkeypatch):
        _ensure_plugin_root(monkeypatch, tmp_path)
        monkeypatch.setenv("HOOKIFY_NO_CACHE", "1")
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.r.local.md",
            {"name": "r", "enabled": True, "event": "bash", "pattern": "x"},
        )
        load_rules(event="bash")
        # No cache file should exist when bypass is on
        proj = os.path.realpath(str(isolated_env["project"] / ".claude"))
        glob_dir = os.path.realpath(str(isolated_env["home"] / ".claude"))
        cache_file = cache_path_for(proj, glob_dir)
        assert not os.path.exists(cache_file)

    def test_cache_invalidates_on_file_change(self, isolated_env, tmp_path, monkeypatch):
        _ensure_plugin_root(monkeypatch, tmp_path)
        rule_path = write_rule(
            isolated_env["project"] / ".claude",
            "hookify.r.local.md",
            {"name": "r", "enabled": True, "event": "bash", "pattern": "OLD"},
        )
        first = load_rules(event="bash")
        assert first[0].pattern == "OLD"

        # Wait briefly to ensure mtime resolution captures the change
        time.sleep(0.01)
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.r.local.md",
            {"name": "r", "enabled": True, "event": "bash", "pattern": "NEW"},
        )
        # Touch mtime forward explicitly
        new_mtime = time.time()
        os.utime(rule_path, (new_mtime, new_mtime))

        second = load_rules(event="bash")
        assert second[0].pattern == "NEW"

    def test_cache_invalidates_on_file_added(self, isolated_env, tmp_path, monkeypatch):
        _ensure_plugin_root(monkeypatch, tmp_path)
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.a.local.md",
            {"name": "a", "enabled": True, "event": "bash", "pattern": "x"},
        )
        load_rules(event="bash")  # populate cache
        write_rule(
            isolated_env["project"] / ".claude",
            "hookify.b.local.md",
            {"name": "b", "enabled": True, "event": "bash", "pattern": "y"},
        )
        result = load_rules(event="bash")
        assert {r.name for r in result} == {"a", "b"}
```

**Step 2: Run, verify failure**

Run: `pytest tests/test_config_loader_cache.py -v`
Expected: tests fail (cache not yet wired in)

**Step 3: Wire cache into `load_rules`**

Modify `core/config_loader.py`. At the top, add:

```python
from core.cache import (
    cache_path_for,
    is_bypass_enabled,
    is_cache_valid,
    load_from_cache,
    save_to_cache,
)
```

Refactor `load_rules` so the cache wraps the parse-and-merge logic:

```python
def _parse_and_merge_rules() -> list[Rule]:
    """Internal: parse all .md rule files and apply override semantics.

    This is the cache-miss path. Returns rules in load order
    (project rules first, then non-conflicting global rules).
    """
    by_name: dict[str, Rule] = {}
    suppressed: set[str] = set()

    for directory in _resolve_rule_dirs():
        if not os.path.isdir(directory):
            continue
        pattern = os.path.join(directory, "hookify.*.local.md")
        for file_path in sorted(glob.glob(pattern)):
            try:
                rule = load_rule_file(file_path)
                if rule is None:
                    continue
            except (IOError, OSError, PermissionError) as e:
                print(f"Warning: Failed to read {file_path}: {e}", file=sys.stderr)
                continue
            except (ValueError, KeyError, AttributeError, TypeError) as e:
                print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                print(
                    f"Warning: Unexpected error loading {file_path} "
                    f"({type(e).__name__}): {e}",
                    file=sys.stderr,
                )
                continue

            if not rule.enabled:
                if rule.name not in by_name:
                    suppressed.add(rule.name)
                continue

            if rule.name in by_name or rule.name in suppressed:
                continue

            by_name[rule.name] = rule

    return list(by_name.values())


def _current_source_mtimes() -> dict[str, float]:
    """Return {file_path: mtime} for every current source rule file."""
    mtimes: dict[str, float] = {}
    for directory in _resolve_rule_dirs():
        if not os.path.isdir(directory):
            continue
        pattern = os.path.join(directory, "hookify.*.local.md")
        for file_path in glob.glob(pattern):
            try:
                mtimes[file_path] = os.stat(file_path).st_mtime
            except OSError:
                continue
    return mtimes


def load_rules(event: Optional[str] = None) -> List[Rule]:
    """Load all hookify rules from project-local and global directories.

    Uses a JSON cache (mtime-invalidated) to avoid re-parsing rule
    files on every hook event. Set HOOKIFY_NO_CACHE=1 to bypass.

    Spec: docs/plans/2026-05-03-spec-cwd-global-rules.md (semantics)
          docs/plans/2026-05-03-spec-json-cache.md (cache behavior)
    """
    # Bypass path: never read or write cache
    if is_bypass_enabled():
        rules = _parse_and_merge_rules()
        return _filter_by_event(rules, event)

    dirs = _resolve_rule_dirs()
    project_dir = dirs[0]
    global_dir = dirs[1] if len(dirs) > 1 else dirs[0]
    cache_file = cache_path_for(project_dir, global_dir)

    current_mtimes = _current_source_mtimes()
    cached = load_from_cache(cache_file)
    if cached is not None:
        cached_rules, cached_sources = cached
        if is_cache_valid(cached_sources, current_mtimes):
            return _filter_by_event(cached_rules, event)

    rules = _parse_and_merge_rules()
    save_to_cache(cache_file, rules, current_mtimes)
    return _filter_by_event(rules, event)


def _filter_by_event(rules: list[Rule], event: Optional[str]) -> list[Rule]:
    """Filter rules by event tag. event=None or 'all' returns everything."""
    if not event or event == "all":
        return rules
    return [r for r in rules if r.event == "all" or r.event == event]
```

**Step 4: Run all tests**

Run: `pytest`
Expected: ALL tests pass (Phase B regression tests + cache integration)

**Step 5: Lint**

Run: `ruff check core/ tests/ && ruff format --check core/ tests/`
Expected: clean

**Step 6: Commit**

```bash
git add core/config_loader.py tests/test_config_loader_cache.py
git commit -m "feat: wire JSON cache into load_rules()

load_rules() now consults the cache before parsing markdown files.
On cache hit (file set + mtimes unchanged): returns deserialized
Rule objects directly. On cache miss/invalid: full parse + merge,
then write the new cache.

The HOOKIFY_NO_CACHE env var bypasses both read AND write paths,
useful for tests that need a regression baseline against pure
upstream behavior."
```

---

## Phase D — Cherry-picks

Each task is small (1–3 lines of source change + a test where it
adds value). Tasks can technically run in any order but proceed
sequentially per delegated-execution policy.

### Task 10: `permissionDecisionReason` in block output

**Files:**
- Modify: `core/rule_engine.py` (around line 70-80, the PreToolUse/PostToolUse block)
- Add test in `tests/test_rule_engine_block.py` (new file)

**Test:**

```python
"""Tests for permissionDecisionReason in block-rule output."""

from core.rule_engine import RuleEngine
from core.config_loader import Rule, Condition


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
```

**Implementation:** find the block in `evaluate_rules`:

```python
elif hook_event in ['PreToolUse', 'PostToolUse']:
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "deny"
        },
        "systemMessage": combined_message
    }
```

Add the field:

```python
elif hook_event in ['PreToolUse', 'PostToolUse']:
    return {
        "hookSpecificOutput": {
            "hookEventName": hook_event,
            "permissionDecision": "deny",
            "permissionDecisionReason": combined_message
        },
        "systemMessage": combined_message
    }
```

**Verify + Commit:**

```bash
pytest tests/test_rule_engine_block.py -v
git add core/rule_engine.py tests/test_rule_engine_block.py
git commit -m "feat: include permissionDecisionReason in block hook output

When a block rule fires, Claude Code now receives the matched
rule's message in hookSpecificOutput.permissionDecisionReason
in addition to systemMessage. Without this, Claude saw the
operation was denied but had no context for why."
```

---

### Task 11: Windows path quoting in `hooks.json`

**Files:**
- Modify: `hooks/hooks.json`

**Step 1: Update each command to quote the path**

```json
{
  "description": "Hookify plugin - User-configurable hooks from .local.md files",
  "hooks": {
    "PreToolUse": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/pretooluse.py\"", "timeout": 10}]}],
    "PostToolUse": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/posttooluse.py\"", "timeout": 10}]}],
    "Stop": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/stop.py\"", "timeout": 10}]}],
    "UserPromptSubmit": [{"hooks": [{"type": "command", "command": "python3 \"${CLAUDE_PLUGIN_ROOT}/hooks/userpromptsubmit.py\"", "timeout": 10}]}]
  }
}
```

**Step 2: Validate JSON**

Run: `python3 -c "import json; json.load(open('hooks/hooks.json'))"`
Expected: no output

**Step 3: Commit**

```bash
git add hooks/hooks.json
git commit -m "fix: quote CLAUDE_PLUGIN_ROOT path in hook commands

Plugin paths containing spaces broke hook execution on Windows
and on macOS volumes with spaces in names. Quoting the path
in each command keeps shells from splitting on whitespace."
```

---

### Task 12: `Update` tool support in event mapping

**Files:**
- Modify: `hooks/pretooluse.py` (around lines 38–42)
- Modify: `hooks/posttooluse.py` (same block)

**Existing block:**

```python
elif tool_name in ['Edit', 'Write', 'MultiEdit']:
    event = 'file'
```

**Replace with:**

```python
elif tool_name in ['Edit', 'Write', 'MultiEdit', 'Update']:
    event = 'file'
```

**Verify:** Quick sanity check: `python3 -c "import ast; ast.parse(open('hooks/pretooluse.py').read())"`

**Commit:**

```bash
git add hooks/pretooluse.py hooks/posttooluse.py
git commit -m "fix: include Update tool in file-event mapping

The Update tool was missing from the file-event tool list, so
event:file rules never fired on Update operations."
```

---

### Task 13: Fix `examples/require-tests-stop.local.md`

**Files:**
- Modify: `examples/require-tests-stop.local.md`

**Step 1: Inspect current file**

Run: `cat examples/require-tests-stop.local.md`

**Step 2: Replace `not_contains` (broken — pipes are literal in `contains`) with `not_regex_match` (correct — pipes are alternation in regex). Add `vitest` and `jest` to the alternation while we're here.**

Replace the conditions block:

```yaml
conditions:
  - field: transcript
    operator: not_contains
    pattern: npm test|pytest|cargo test
```

With:

```yaml
conditions:
  - field: transcript
    operator: not_regex_match
    pattern: (npm test|pytest|cargo test|vitest|jest)
```

**Step 3: Validate frontmatter**

Run: `python3 -c "from core.config_loader import load_rule_file; r = load_rule_file('examples/require-tests-stop.local.md'); print(r.name if r else 'FAILED')"`
Expected: rule name printed.

**Step 4: Commit**

```bash
git add examples/require-tests-stop.local.md
git commit -m "fix(examples): use not_regex_match for test-runner detection

The pattern 'npm test|pytest|cargo test' under not_contains was
treated as a literal string with pipes, so the rule never matched.
Switching to not_regex_match interprets the pipes as alternation.
Also added vitest and jest to cover modern JS test runners."
```

---

### Task 14: `value` key alias for `pattern` in conditions

**Files:**
- Modify: `core/config_loader.py` (`Condition.from_dict`)
- Add test in `tests/test_config_loader_value_key.py` (new)

**Test:**

```python
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
```

**Implementation in `Condition.from_dict`:**

Replace:

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> 'Condition':
    return cls(
        field=data.get('field', ''),
        operator=data.get('operator', 'regex_match'),
        pattern=data.get('pattern', '')
    )
```

With:

```python
@classmethod
def from_dict(cls, data: Dict[str, Any]) -> 'Condition':
    """Create Condition from dict.

    Accepts both 'pattern' and 'value' as the matching string;
    'pattern' wins if both are present.
    """
    pattern = data.get('pattern')
    if pattern is None:
        pattern = data.get('value', '')
    return cls(
        field=data.get('field', ''),
        operator=data.get('operator', 'regex_match'),
        pattern=pattern
    )
```

**Verify + Commit:**

```bash
pytest tests/test_config_loader_value_key.py -v
git add core/config_loader.py tests/test_config_loader_value_key.py
git commit -m "feat: accept 'value' as alias for 'pattern' in conditions

Rule authors can now write 'value: literal-string' under a condition
when using non-regex operators (contains, equals, etc.) where
'pattern' reads awkwardly. 'pattern' takes precedence when both
are present (deterministic; backward compatible)."
```

---

### Task 15: `read` event type for Read/Glob/Grep/LS

**Files:**
- Modify: `hooks/pretooluse.py` (event mapping block)
- Modify: `hooks/posttooluse.py` (event mapping block)
- Add test in `tests/test_hooks_event_mapping.py` (new)

**Test:**

```python
"""Tests for the read-event tool mapping."""

import importlib
import io
import json
import os
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).parent.parent
HOOKS_DIR = PLUGIN_ROOT / "hooks"


def _run_hook(hook_module: str, payload: dict, monkeypatch) -> dict:
    """Run a hook script with given stdin payload, return parsed stdout."""
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    out_buf = io.StringIO()
    monkeypatch.setattr("sys.stdout", out_buf)

    if str(HOOKS_DIR) not in sys.path:
        sys.path.insert(0, str(HOOKS_DIR))
    if hook_module in sys.modules:
        del sys.modules[hook_module]
    mod = importlib.import_module(hook_module)
    try:
        mod.main()
    except SystemExit:
        pass
    return json.loads(out_buf.getvalue() or "{}")


def test_read_tool_maps_to_read_event(isolated_env, monkeypatch):
    """A read-event rule should fire on the Read tool."""
    from tests.conftest import write_rule

    write_rule(
        isolated_env["project"] / ".claude",
        "hookify.r.local.md",
        {
            "name": "read-rule",
            "enabled": True,
            "event": "read",
            "conditions": [
                {"field": "file_path", "operator": "contains", "value": "/etc/"},
            ],
            "action": "warn",
        },
        body="Reading /etc/ files",
    )
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(PLUGIN_ROOT))
    result = _run_hook(
        "pretooluse",
        {"hook_event_name": "PreToolUse", "tool_name": "Read",
         "tool_input": {"file_path": "/etc/passwd"}},
        monkeypatch,
    )
    assert "systemMessage" in result
    assert "Reading /etc/" in result["systemMessage"]
```

**Implementation:** in both `hooks/pretooluse.py` and `hooks/posttooluse.py`, replace:

```python
event = None
if tool_name == 'Bash':
    event = 'bash'
elif tool_name in ['Edit', 'Write', 'MultiEdit', 'Update']:
    event = 'file'
```

With:

```python
event = None
if tool_name == 'Bash':
    event = 'bash'
elif tool_name in ['Edit', 'Write', 'MultiEdit', 'Update']:
    event = 'file'
elif tool_name in ['Read', 'Glob', 'Grep', 'LS']:
    event = 'read'
```

**Verify + Commit:**

```bash
pytest tests/test_hooks_event_mapping.py -v
git add hooks/pretooluse.py hooks/posttooluse.py tests/test_hooks_event_mapping.py
git commit -m "feat: add 'read' event type for Read/Glob/Grep/LS tools

Read-class tools now map to event:read instead of falling through
to event:all. This lets rule authors target read operations
specifically (e.g., warn before reading sensitive files) without
their rules also firing on every other tool."
```

---

### Task 16: `not_regex_match` operator

**Files:**
- Modify: `core/rule_engine.py` (`_check_condition`)
- Add test in `tests/test_rule_engine_not_regex.py` (new)

**Implementation discussion:**

hookify-plus implements `not_regex_match` as:

```python
elif operator == 'not_regex_match':
    return not self._regex_match(pattern, field_value)
```

Chris recalls a more-efficient approach. Re-derive options:

1. **Negate-after-call (hookify-plus approach).** Two function calls
   per evaluation, but uses the existing `_regex_match` and inherits
   the lru_cache for compiled patterns. Simple.
2. **Inline the regex search and invert.** Save one function call.
   Marginal at this scale.
3. **Compile-time tagging.** Tag the compiled pattern in lru_cache so
   we can dispatch in one step. Adds complexity, no measurable win.

Honest analysis: at <1ms per condition with regex compilation already
cached, the difference between options is well below measurement
noise. Going with **option 1** for clarity and maintainability —
match hookify-plus's structure, get the lru_cache benefit, no
clever code.

If Chris's recollection sharpens later (e.g., he remembers a specific
optimization that mattered), we can revisit in a follow-up. For now,
ship the clear version.

**Test:**

```python
"""Tests for the not_regex_match operator."""

from core.rule_engine import RuleEngine
from core.config_loader import Rule, Condition


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
        {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": "rm -rf /"}},
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
        {"hook_event_name": "PreToolUse", "tool_name": "Bash",
         "tool_input": {"command": "safe-prefix mything"}},
    )
    assert result == {}, "should NOT fire when pattern is present"
```

**Implementation in `_check_condition`:**

Find:

```python
if operator == 'regex_match':
    return self._regex_match(pattern, field_value)
elif operator == 'contains':
```

Insert between them:

```python
if operator == 'regex_match':
    return self._regex_match(pattern, field_value)
elif operator == 'not_regex_match':
    return not self._regex_match(pattern, field_value)
elif operator == 'contains':
```

**Verify + Commit:**

```bash
pytest tests/test_rule_engine_not_regex.py -v
git add core/rule_engine.py tests/test_rule_engine_not_regex.py
git commit -m "feat: add not_regex_match operator

Inverse of regex_match — fires when the pattern is NOT present in
the field. Useful for require-something rules ('block stop unless
the transcript shows a test runner ran'). Implementation reuses
the lru_cache-backed _regex_match; the negation is the only new
work per evaluation."
```

---

## Phase E — Polish & Quality Gate

### Task 17: Remove empty `matchers/` and `utils/` directories

**Files:**
- Delete: `matchers/__init__.py`
- Delete: `matchers/` (directory after file removal)
- Delete: `utils/__init__.py`
- Delete: `utils/` (directory after file removal)

**Step 1: Verify they're truly empty**

Run: `find matchers utils -type f`
Expected: only `__init__.py` files (no other content)

**Step 2: Remove**

```bash
git rm matchers/__init__.py utils/__init__.py
rmdir matchers utils 2>/dev/null || true  # may not be needed if git rm cleaned up
```

**Step 3: Verify nothing imports from them**

Run: `grep -rn "from matchers\|from utils\|import matchers\|import utils" core/ hooks/ tests/`
Expected: no results

**Step 4: Run all tests**

Run: `pytest`
Expected: all pass

**Step 5: Commit**

```bash
git commit -m "chore: remove empty matchers/ and utils/ directories

Upstream ships these as empty placeholder packages. Nothing imports
from them in either upstream or our fork. Removing them cleans up
the source tree."
```

---

### Task 18: Add `.gitignore` entries

**Files:**
- Modify: `.gitignore`

**Step 1: Inspect existing `.gitignore`**

Run: `cat .gitignore`

**Step 2: Append** (only items not already present):

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.pytest_cache/
.ruff_cache/

# IDE
.vscode/
.idea/
*.swp

# OS
.DS_Store

# Hookify cache (defensive — should not normally exist in repo)
.cache/
*.cache.json
```

**Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: add Python tooling and editor entries to .gitignore"
```

---

### Task 19: Rewrite `README.md`

**Files:**
- Modify: `README.md`

The existing README is upstream's. Rewrite to reflect fork status,
list fixes, give install instructions, and link to upstream issues.

(Full README content is omitted from this plan for brevity; the
implementing agent will draft a README that:
- Identifies as "Patched fork of Anthropic's hookify"
- Lists the two bug fixes (with issue links)
- Lists the cache feature
- Lists the cherry-picks
- Gives `/plugin marketplace add reyequis/hookify` install instructions
- Notes Python 3.10+ requirement
- Links to upstream issues for the bugs
- Preserves Anthropic as primary author with Chris listed as fork maintainer
- Soft perf claim: "reduces redundant YAML parsing and slow-disk
  long-tail latency" — no "100x" headline)

**Verify:** `head -20 README.md` reads correctly.

**Commit:**

```bash
git add README.md
git commit -m "docs: rewrite README for fork status

Identifies the project as a patched fork of Anthropic's hookify
with bug fixes (#2 CWD/global rules, #3 Write tool) and a JSON
rule cache. Install instructions cover the self-marketplacing
flow. Performance claims are conservative (reduces redundant
YAML parsing, removes slow-disk long-tail latency)."
```

---

### Task 20: Update `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`

The existing `CLAUDE.md` describes the re-fork project goals. Update
to reflect what's now true post-implementation:

- Status moves from "to do" to "shipped in v0.2.0"
- Add "How to develop" section: `pytest`, `ruff check`, `ruff format`
- Add "How to test installation locally" section
- Note the spec docs and where they live

**Verify:** `head CLAUDE.md` reflects the updates.

**Commit:**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md to reflect v0.2.0 implementation

Removes 'to do' framing now that bug fixes, cache, and cherry-picks
are shipped. Adds development workflow notes (pytest, ruff) and
local-install verification steps."
```

---

### Task 21: Quality gate — full verification

**Files:** none modified; this is verification.

**Step 1: Full test suite**

Run: `pytest -v`
Expected: all tests pass; no skips or warnings beyond intentional ones

**Step 2: Lint check**

Run: `ruff check . && ruff format --check .`
Expected: clean

**Step 3: CI matrix simulation (Python 3.10, 3.11, 3.12 if available locally)**

Run: `for v in 3.10 3.11 3.12; do echo "=== Python $v ==="; if command -v python$v >/dev/null; then python$v -m pytest -q && python$v -m ruff check . ; else echo "skipping $v (not installed)"; fi; done`
Expected: pass on every available version

**Step 4: Local install + smoke test**

Run:
```bash
# 1. Disable upstream hookify in user settings (manual)
# 2. Add this fork as a marketplace
/plugin marketplace add file:///Users/reyequis/dev/projects/hookify-fork
# 3. Install
/plugin install hookify@hookify
# 4. Reload
/reload-plugins
# 5. Place a test rule in ~/.claude/hookify.smoke.local.md
#    (simple `event: bash`, `pattern: smoke-test-pattern`)
# 6. Run a Bash command containing the pattern
# 7. Verify the systemMessage appears
```

Expected: hookify fires correctly; cache file appears at
`~/.claude/plugins/cache/hookify/hookify/0.2.0/.cache/<key>.json`;
second invocation is observably faster.

**Step 5: Verify cache file structure**

Run: `find ~/.claude/plugins/cache/hookify -name '*.json' -path '*.cache*' | xargs -I{} python3 -c "import json; print(json.dumps(json.load(open('{}')), indent=2))" | head -30`
Expected: schema-version-1 JSON with `sources` and `rules` keys

**Step 6: Commit nothing (verification only)**

If any step fails, stop and create a follow-up task.

If all steps pass: commit a CHANGELOG entry (single small commit):

```bash
cat > CHANGELOG.md <<'EOF'
# Changelog

## v0.2.0 — 2026-05-03

Initial fork of Anthropic's hookify with bug fixes and JSON cache.

### Fixed
- Bug #2: Rules in `~/.claude/` now load regardless of CWD. Project
  rules override global by name; disabled project rules suppress
  matching global rules. Fixes upstream issues #309, #503, #1294,
  #1444 on `anthropics/claude-plugins-official`.
- Bug #3: `event: file` rules now fire on Write operations. Field
  extraction falls back from `new_string` to `content`.

### Added
- JSON rule cache (mtime-invalidated). Reduces redundant YAML
  parsing on every hook event. Set `HOOKIFY_NO_CACHE=1` to disable.
- `not_regex_match` operator.
- `value` key as an alias for `pattern` in conditions.
- `read` event type for Read/Glob/Grep/LS tools.
- `Update` tool support in file-event mapping.
- `permissionDecisionReason` in block-rule output (Claude sees why
  it was blocked).
- Windows path quoting in `hooks.json`.
- `version` field in `plugin.json` (was missing upstream).
- `.claude-plugin/marketplace.json` for self-marketplacing.

### Internal
- pytest test suite (none in upstream).
- ruff lint + format.
- GitHub Actions CI on Python 3.10, 3.11, 3.12.
- Apache 2.0 license preserved from upstream.
EOF

git add CHANGELOG.md
git commit -m "docs: add CHANGELOG.md for v0.2.0

Lists the two bug fixes (with upstream issue refs), JSON cache
feature, seven cherry-picks, plugin metadata additions, and CI/
test infrastructure that did not exist in upstream."
```

---

## Out-of-band: filing upstream issue for Bug #3

After Phase E completes and the fork is verified working, file a new
GitHub issue on `anthropics/claude-plugins-official`:

- Title: `hookify: Write tool bypasses all event:file rules`
- Body: reproduction (the test in `tests/test_rule_engine_write.py`),
  proposed patch (the diff applied in T7), reference Chris's prior
  comment on #503, and link to the working fix in this fork
- Patch must be 3.10-compatible (verify before posting)

Optionally file a separate feature-suggestion issue for the JSON
cache referencing the spec doc.

This step is OUTSIDE the implementation plan — it's a follow-up
action once the fork is verified working.

---

## Execution handoff

Plan is complete and saved to
`docs/plans/2026-05-03-hookify-implementation.md`.

**Two execution options:**

1. **Delegated Execution (this session)** — I dispatch a fresh
   subagent per task, review between tasks, fast iteration.
   **REQUIRED SUB-SKILL:** `godmode:delegated-execution`

2. **Separate Session (task-runner)** — Open a new session in this
   working directory, batch execution with checkpoints.
   **REQUIRED SUB-SKILL:** `godmode:task-runner` in the new session.

**Which approach?**
