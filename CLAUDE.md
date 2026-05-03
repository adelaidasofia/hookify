# hookify v0.2.0 (patched fork)

Patched fork of Anthropic's hookify Claude Code plugin. Fixes two
latent bugs, adds a JSON rule cache, and integrates seven
cherry-picks from the hookify-plus community fork.

## What shipped in v0.2.0

- **Bug #2 fixed:** Global rules in `~/.claude/` now load regardless
  of CWD. Project rules override global by name; disabled project
  rules suppress matching global rules.
- **Bug #3 fixed:** `event: file` rules now fire on Write operations
  (was silently bypassed).
- **JSON rule cache:** mtime-invalidated, stored at
  `${CLAUDE_PLUGIN_ROOT}/.cache/`. Set `HOOKIFY_NO_CACHE=1` to
  disable.
- **7 cherry-picks from hookify-plus:** `not_regex_match` operator,
  `value` key alias, `read` event type, `permissionDecisionReason`,
  `Update` tool support, Windows path quoting, fixed example file.

## Development

```bash
python3 -m pytest          # run tests (67 tests)
python3 -m ruff check .    # lint
python3 -m ruff format .   # format
```

## Project structure

```
core/config_loader.py   — rule file parsing + global rule loading
core/rule_engine.py     — rule evaluation against tool input
core/cache.py           — JSON rule cache (mtime-invalidated)
hooks/*.py              — hook entry points (PreToolUse, PostToolUse, Stop, UserPromptSubmit)
tests/                  — pytest test suite
docs/plans/             — design doc, specs, implementation plan
```

## Key design decisions

- **Python 3.10+ floor** — bump to 3.11 when 3.10 EOLs (Oct 2026)
- **Flat layout preserved** from upstream for diff-friendly patch filing
- **Cache in `${CLAUDE_PLUGIN_ROOT}/.cache/`** — auto-cleaned on
  version bump; XDG fallback for non-plugin contexts
- **Project overrides global** by rule `name`; disabled project rule
  suppresses matching global rule
- **Apache 2.0 license** preserved from upstream

## Reference

- Research: `~/dev/docs/research/2026-05-02-hookify-claude-code-plugin.md`
- Design doc: `docs/plans/2026-05-03-hookify-design.md`
- Specs: `docs/plans/2026-05-03-spec-cwd-global-rules.md`,
  `docs/plans/2026-05-03-spec-json-cache.md`
- Upstream: https://github.com/anthropics/claude-plugins-official/tree/main/plugins/hookify
- Bug #2 canonical thread: https://github.com/anthropics/claude-plugins-official/issues/503
- hookify-plus: https://github.com/adrozdenko/hookify-plus
