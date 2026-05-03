# hookify v0.2.0 — Design Document

**Date:** 2026-05-03
**Status:** Approved (intent-discovery phase complete)
**Author:** Chris Irving (Architected) + Claude Code (Drafted)

## Goal

A patched fork of Anthropic's hookify plugin that fixes two latent
bugs (silent failures of global rules and Write-tool rules), adds a
JSON-based rule cache, and incorporates seven cherry-picks from the
hookify-plus community fork. Distributed publicly so users can install
the working version while we pitch the bug fixes upstream for merging.

## Non-goals

- Renaming, rebranding, or competing with upstream hookify
- New rule features beyond the cherry-picks (YAGNI)
- Skill/command improvements (`/hookify`, `/hookify:configure`,
  `/hookify:list`) — out of scope for v0.2.0
- Marketplace submission to Anthropic in v0.2.0 — only after the
  upstream-issue route has been exhausted

## Distribution strategy

- **Repo:** `reyequis/hookify`, public on GitHub
- **Plugin name:** `hookify` (matches upstream — clear lineage; no
  marketplace name conflict because plugin IDs are
  `<name>@<marketplace>`)
- **Version:** `0.2.0` — we add a `version` field to `plugin.json`;
  upstream has none, which is why their cache currently lands at
  `~/.claude/plugins/cache/.../hookify/unknown/`
- **Self-marketplacing:** repo includes `.claude-plugin/marketplace.json`
  so users install via:
  ```
  /plugin marketplace add reyequis/hookify
  /plugin install hookify@hookify
  ```
- **Upstream patch route:** file detailed issues with proposed patches
  against `anthropics/claude-plugins-official` once fixes are
  implemented and verified. Issues will reference Chris's prior
  comment on issue #503 and the existing duplicates (#309, #1294,
  #1444). PRs auto-close on that repo, so issue-as-patch is the only
  viable path. (This is how Daisy's Dec 2025 import-bug fix landed.)
- **License:** Apache 2.0, preserved from upstream — supports clean
  upstream-merge of patches without CLA friction

## Tech stack

- **Python 3.10+** — broad compatibility (Ubuntu 22.04 LTS, RHEL 9 via
  `python3.10`, modern macOS, Debian 12); active security support
  through October 2026. Floor will bump to 3.11 in v0.3.0 when 3.10
  EOLs.
- **`pytest`** for tests; `pytest.tmp_path` + `monkeypatch` for
  filesystem isolation; no mocks (real-filesystem testing)
- **`ruff`** for lint and formatting (replaces flake8/isort/pyupgrade);
  no separate type checker (mypy overkill for ~600 lines)
- **`pyproject.toml`** — single config file for project metadata,
  ruff, and pytest
- **GitHub Actions CI** — `pytest + ruff` on push/PR
- **Conventional Commits** — `fix:`, `feat:`, `chore:`, `docs:`,
  `test:`, etc.; matches upstream style and helps changelog generation
- **Trunk-based on `main`** — solo project; PRs only when isolating
  risky work
- **No pre-commit hooks** — CI catches the same things; less friction

## Repo structure

Preserving upstream's flat layout so future patch issues stay
diff-friendly. (Restructuring to `src/` package layout would make
every line of every file appear "moved" when diffing against upstream,
which would render the issue-as-patch workflow unusable.)

```
hookify/
├── .claude-plugin/
│   ├── plugin.json          (UPDATE: add version "0.2.0")
│   └── marketplace.json     (NEW: self-marketplacing)
├── core/
│   ├── config_loader.py     (Bug #2 fix; cache integration)
│   ├── rule_engine.py       (Bug #3 fix; not_regex_match;
│   │                         permissionDecisionReason)
│   └── cache.py             (NEW: JSON rule cache)
├── hooks/
│   ├── hooks.json           (UPDATE: Windows path quoting)
│   ├── pretooluse.py        (UPDATE: read event type)
│   ├── posttooluse.py       (UPDATE: read event type)
│   ├── stop.py
│   └── userpromptsubmit.py
├── tests/                   (NEW)
│   ├── test_config_loader.py
│   ├── test_rule_engine.py
│   └── test_cache.py
├── examples/                (existing rule examples; one fixed)
├── .github/
│   └── workflows/
│       └── ci.yml           (NEW)
├── docs/
│   └── plans/               (this design doc + specs + plan)
├── pyproject.toml           (NEW)
├── LICENSE                  (Apache 2.0, unchanged)
├── README.md                (REWRITTEN: fork status)
└── CLAUDE.md                (project memory, unchanged)
```

The empty `matchers/` and `utils/` directories from upstream will be
removed (they ship with no content).

## Scope summary

### Bug fixes

1. **Bug #2 — CWD/global rules silently never load.**
   `core/config_loader.py:210` uses a relative glob
   `.claude/hookify.*.local.md` that requires CWD to be the project
   root. Rules in `~/.claude/` never load regardless of CWD. Reported
   in issues #309, #503, #1294, #1444; auto-closed PR #1622 attempted
   a fix.

2. **Bug #3 — Write tool bypasses all `event: file` rules.**
   `core/rule_engine.py._extract_field` returns `tool_input['new_string']`
   for Write tool, but Write uses `content`, not `new_string`. Rule
   never fires. Combined with Bug #2 this means `action: block` rules
   for Write at user scope provide zero protection. Documented
   publicly in Chris's prior comment on #503; not yet filed as its
   own issue.

### New features

1. **JSON rule cache layer** — parse once, serialize parsed rules to
   JSON, reload via `json.loads()` on subsequent hook events.
   mtime-based invalidation against `.md` source files. Target: <1ms
   cold cache, <0.1ms warm cache (vs upstream ~5ms per event).

2. **`version` field in `plugin.json`** — fixes the cache path being
   `hookify/unknown/`. Will also be filed as a separate upstream
   patch (bug-class).

### Cherry-picks from hookify-plus

| # | Item | Class |
|---|---|---|
| 1 | `permissionDecisionReason` in block output (Claude sees *why* it was blocked) | bug-class |
| 2 | Windows path quoting in `hooks.json` | bug-class |
| 3 | `Update` tool support added to file-event tool list | bug-class |
| 4 | Fixed `require-tests-stop.local.md` example (use `not_regex_match` correctly) | doc-class |
| 5 | `not_regex_match` operator (Chris recalls a more-efficient implementation than hookify-plus's negation approach; specific implementation deferred to spec/planning) | feature |
| 6 | `value` key alias for `pattern` in conditions | feature |
| 7 | `read` event type for Read/Glob/Grep/LS tools | feature |

### Skipped from hookify-plus

- `from __future__ import annotations` (Python 3.8 compat) — we're on
  3.10+, not needed
- hookify-plus's specific global-rules implementation — replaced by
  our own Bug #2 fix with explicit override semantics in spec
- hookify-plus's specific Write `content` fallback — replaced by our
  own Bug #3 fix

## Open design questions deferred to specifications

These have multiple defensible answers and warrant explicit specs
before implementation:

1. **`docs/plans/2026-05-03-spec-cwd-global-rules.md`** — Bug #2
   override semantics
   - Project precedence vs global precedence on rule name collision
   - Disabled-rule suppression semantics (does
     `enabled: false` in project suppress a global rule with the same
     `name`?)
   - Edge cases: CWD == $HOME, missing directories, malformed rules

2. **`docs/plans/2026-05-03-spec-json-cache.md`** — JSON cache shape
   and invalidation
   - Cache file location (per-project, global, keyed by hash)
   - Invalidation strategy (mtime, content hash, hybrid)
   - Multi-process safety (lock file? atomic write-rename?)
   - Cache schema — what serializable form to use for parsed `Rule`
     and `Condition` objects
   - **SQLite explicitly ruled out as prior-art-rejected.** Chris's
     earlier work at Ally tried SQLite (storing frontmatter,
     SQL-style lookups) and it didn't improve performance — the
     bottleneck is YAML parse cost, not lookup speed. JSON wins
     because it stores already-parsed structures that `json.loads()`
     returns ready-to-use.

## Test strategy

- Unit tests per module: `tests/test_config_loader.py`,
  `tests/test_rule_engine.py`, `tests/test_cache.py`
- Real filesystem via `pytest.tmp_path` and `monkeypatch.setenv("HOME", ...)`
  — closer to production than mocks; YAML/file edge cases are part
  of what we're testing
- Spec acceptance criteria become the test cases
  (specification-first → test-first)
- Per-task TDD cycle: failing test → minimal code to pass → commit
- CI runs full suite on every push and PR
- Aim: full coverage of bug-fix code paths; light coverage on
  cherry-picks (most are 1–3 line changes that don't merit per-line
  tests)

## Acceptance criteria

- [ ] All upstream behavior preserved (no regressions)
- [ ] **Bug #2 verifiable:** rules in `~/.claude/` load from any CWD;
      project rules override global rules by name; disabled project
      rule suppresses matching global rule (per spec)
- [ ] **Bug #3 verifiable:** rules with `event: file` fire correctly
      on Write operations
- [ ] **Cache benchmark:** <1ms cold, <0.1ms warm on M-series Mac
      (matches Chris's prior fork numbers)
- [ ] All seven cherry-picks landed and tested (or covered by
      existing tests where small enough)
- [ ] `pytest` passes, `ruff` clean, CI green on `main`
- [ ] README reflects fork status with install instructions, fix list,
      and links to upstream issues
- [ ] `/plugin marketplace add reyequis/hookify` then
      `/plugin install hookify@hookify` works end-to-end on a clean
      machine

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Python 3.10 EOLs October 2026 | Bump floor to 3.11 in v0.3.0 (~5 months out) |
| Upstream merges fixes (good!) but breaks our patches | Rebase; cache and feature cherry-picks remain our differentiator |
| Upstream rejects/ignores fixes | Fork is self-sufficient; users get fixes via our marketplace |
| Cache file corruption | Write-rename atomicity in spec; fall back to disk reload on read error |
| Multi-process write collisions | Spec to address (lock file or process-isolated cache directories) |
| Plugin name collision in user's plugin list | Plugin IDs are `<name>@<marketplace>`; users can have `hookify@claude-plugins-official` AND `hookify@hookify` — but only one enabled at a time |
| Anthropic considers this a takeover attempt | README and `plugin.json` author field explicitly preserve Anthropic as primary author with Chris listed as fork maintainer |

## Workflow

1. **Phase 1 (now):** Design doc → commit (this file)
2. **Phase 2:** Two specifications → commit each
3. **Phase 3:** `/godmode:write-plan` → implementation plan → commit
4. **Phase 4:** `/godmode:execute-plan` (delegated execution) — TDD
   per task, commit per task
5. **Phase 5:** Quality gate — full pytest, ruff, install + smoke-test
   all 4 hooks, README polish, CI green
6. **Phase 6:** File upstream issue(s) for bugs #2 and #3 with patches
   and link to fix in this fork
7. **Phase 7:** Optionally — feature-suggest the cache layer to
   upstream as a separate issue

## References

- Research doc: `~/dev/docs/research/2026-05-02-hookify-claude-code-plugin.md`
- Upstream: https://github.com/anthropics/claude-plugins-official/tree/main/plugins/hookify
- hookify-plus (community fork): https://github.com/adrozdenko/hookify-plus
- Daisy's Dec 2025 import fix: https://github.com/anthropics/claude-plugins-official/commit/5f2db35c65ac214bc0efcf97d7f2c93964c1e740
- Issue #503 (CWD bug, Chris's write-up): https://github.com/anthropics/claude-plugins-official/issues/503
- coletebou's global-rules branch (one approach to Bug #2): https://github.com/coletebou/claude-plugins-official/tree/feat/hookify-global-rules
