# Specification — Bug #2: CWD / Global Rule Loading

**Date:** 2026-05-03
**Status:** Draft (awaiting Chris's approval)
**Consumer:** `core/config_loader.py:load_rules()`

## Purpose

Load hookify rules from BOTH the project-local `<cwd>/.claude/`
directory AND the user-global `~/.claude/` directory, with explicit
override semantics, so that user-scope rules fire regardless of
current working directory.

This fixes Bug #2 (silent failure of global rules) reported in issues
#309, #503, #1294, #1444 (auto-closed PR #1622).

## Inputs

| Input | Type | Source | Constraints |
|---|---|---|---|
| `event` | `Optional[str]` | Caller argument | One of `"bash"`, `"file"`, `"read"`, `"stop"`, `"prompt"`, `"all"`, or `None` (no filter) |
| Current working directory | filesystem | `os.getcwd()` | Read at call time |
| User home directory | filesystem | `os.path.expanduser("~")` | Read at call time |
| Project rule files | filesystem | `<cwd>/.claude/hookify.*.local.md` | May be absent |
| Global rule files | filesystem | `~/.claude/hookify.*.local.md` | May be absent |

## Outputs

| Scenario | Output |
|---|---|
| Both dirs present with rules | `List[Rule]` — merged with project precedence |
| Only project dir present | `List[Rule]` — project rules only |
| Only global dir present | `List[Rule]` — global rules only |
| Neither present | `[]` |
| CWD == $HOME | `List[Rule]` — single-pass load (no double-counting) |
| Rule file fails to parse | Skipped, logged to stderr, others still loaded |

## Behavior

### Standard path

1. Resolve `project_dir = os.path.realpath(<cwd>/.claude)` and
   `global_dir = os.path.realpath(~/.claude)`
2. If `project_dir == global_dir` (CWD is $HOME), search only one
   directory to avoid double-loading
3. Otherwise search both, in this order: **project first, then global**
4. For each `.md` file matching `hookify.*.local.md`:
   - Parse frontmatter and message body
   - Construct a `Rule` object
   - Apply event filter if specified
   - Apply enabled-status filter (see "Disabled-rule semantics" below)
5. Merge using **first-occurrence-wins by `Rule.name`** — since
   project rules are loaded first, they override global rules with
   the same `name`
6. Return a `List[Rule]`, order-preserved (project rules first, then
   any global rules whose names didn't collide)

### Override semantics

**Decision: project rules override global rules by `name`.**

Rationale: `name` is the canonical rule identifier in frontmatter.
Project-level overrides match standard config precedence (CSS,
gitignore, kubeconfig, etc.) — local context beats global default.

**Example:**

```
~/.claude/hookify.dangerous-rm.local.md     (name: dangerous-rm)
<cwd>/.claude/hookify.dangerous-rm.local.md (name: dangerous-rm)
                ↓
Result: only the project's version loads. Global is shadowed.
```

### Disabled-rule semantics

**Decision: a project rule with `enabled: false` AND a name matching a
global rule SUPPRESSES the global rule.**

Rationale: this enables the "I want to opt out of a global rule for
this specific project" use case, which is the most common reason
someone would disable a rule explicitly. Without this, `enabled: false`
is just dead-code in the project file.

A project rule with `enabled: false` and NO matching global rule is a
no-op (same as upstream: the rule simply doesn't fire).

A global rule with `enabled: false` is also a no-op (same as
upstream).

**Behavior matrix:**

| Project rule | Global rule (same name) | Result |
|---|---|---|
| Not present | Enabled | Global fires |
| Not present | Disabled | Neither fires |
| Enabled | Not present | Project fires |
| Enabled | Enabled | Project fires (override) |
| Enabled | Disabled | Project fires |
| Disabled | Not present | Neither fires (no-op) |
| Disabled | Enabled | **Neither fires** (suppression) |
| Disabled | Disabled | Neither fires |

### Edge cases

| Case | Expected |
|---|---|
| CWD == $HOME (rare but possible) | Search only one directory; no rule loaded twice. Detected via `os.path.realpath` comparison. |
| `~/.claude/` does not exist | Project-only load proceeds normally. No error. |
| `<cwd>/.claude/` does not exist | Global-only load proceeds normally. No error. |
| Rule file unreadable (permissions, broken symlink) | Skip with `print(..., file=sys.stderr)`, continue with others |
| Rule file has malformed YAML frontmatter | Skip with stderr warning, continue with others |
| Rule file missing required `name` field in frontmatter | Skip with stderr warning, continue with others |
| Two project rules with the same `name` (unusual) | Both load; first-occurrence-wins applied. **Out of scope:** detecting/warning on within-scope collisions. Preserve upstream behavior. |
| Global rule with `enabled: false` and no project match | Skipped (existing behavior; no special handling needed) |
| Symlink in `~/.claude/` pointing into project | Resolved via `realpath` at the directory level, not the file level — file-level symlinks load normally as their realpath target |

## Acceptance criteria

- [ ] Rules in `~/.claude/hookify.*.local.md` load when CWD is any
      directory (the original failure mode)
- [ ] Project rules override global rules with the same `name`
- [ ] Project rule with `enabled: false` AND matching global `name`
      → neither fires
- [ ] No rule loads twice when CWD == $HOME
- [ ] Missing `~/.claude/` directory → project-only load works
- [ ] Missing `<cwd>/.claude/` directory → global-only load works
- [ ] Malformed rule file → skipped with stderr warning, others still
      load
- [ ] Event filter (`event="bash"`, etc.) still applies correctly
      across both scopes
- [ ] No regression: every existing project-local-rule scenario from
      upstream continues to work identically
- [ ] First-occurrence-wins is implementation-detail-stable: rules
      load in project-then-global order, deterministic across runs

## Explicitly excluded (YAGNI)

- **`CLAUDE_PROJECT_DIR` env var detection** — issue #309 suggested
  this as the fix. We use CWD-based resolution because that's what
  upstream code currently uses; switching the resolution mechanism is
  a larger change than the bug fix needs. If `CLAUDE_PROJECT_DIR`
  becomes universally set in Claude Code, we can adopt it later.
- **Rule-merging by field** (e.g., merge two rules' conditions arrays
  when they share a name) — overrides replace; they don't merge.
  Simpler mental model.
- **Detection/warning on within-scope name collisions** — preserves
  upstream behavior; out of scope for the bug fix.
- **Custom global directory location** (e.g., `XDG_CONFIG_HOME`
  support) — `~/.claude/` matches Claude Code's convention.
- **Per-rule conditional disabling** (e.g., disable rule based on
  another rule's state) — orthogonal feature, not in v0.2.0.

## Alternatives considered

### Alternative semantics for override

**A1: Global wins.** Rejected — global is a default, not an enforcement
ceiling. Project-local should win for the same reason `.gitignore`,
`.editorconfig`, and similar tools have project-local override.

**A2: Both fire (no override).** Rejected — leads to confusing
duplicate messages and makes it impossible for a project to opt out
of a global rule.

**A3: Configurable merge mode.** Rejected — YAGNI. Pick one sensible
default; users who need different semantics can use different
filenames to avoid collisions.

### Alternative semantics for disabled-rule

**B1: `enabled: false` is just dead code (project's disabled rule
does nothing; global rule fires).** Rejected — makes `enabled: false`
useless in cross-scope context. The whole point of having both
scopes is to support per-project overrides.

**B2: Disabled at any scope blocks the rule globally.** Rejected —
unintuitive (a global `enabled: false` shouldn't be "force off" for
all projects). Asymmetric with override direction.

### Implementation reference (informational, not binding)

`coletebou/claude-plugins-official@feat/hookify-global-rules`
implemented similar semantics. Their implementation is one valid
reference, but we re-derive in our codebase rather than direct
cherry-pick because we want to control the merge logic and tests
ourselves. (The branch is small enough to study but not large enough
to depend on.)

## Open questions for Chris

None — the two judgment calls (override direction, disabled-rule
semantics) have explicit recommendations above. Confirm or push back
on either before commit.
