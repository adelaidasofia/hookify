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
- pytest test suite (66 tests; none in upstream).
- ruff lint + format.
- GitHub Actions CI on Python 3.10, 3.11, 3.12.
- Apache 2.0 license preserved from upstream.
