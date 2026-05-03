# hookify (patched fork)

Patched fork of [Anthropic's hookify](https://github.com/anthropics/claude-plugins-official/tree/main/plugins/hookify) Claude Code plugin with bug fixes, a JSON rule cache, and community improvements. Maintained at [Chris-Irving/hookify](https://github.com/Chris-Irving/hookify) -- pending upstream merge.

## What's fixed (v0.2.0)

### Bug fixes

- **Global rules never load (bug #2)** -- The official plugin uses a relative glob (`os.path.join('.claude', ...)`) that only finds rules when CWD happens to be the project root. Rules in `~/.claude/` (user scope) are silently ignored. Fixed by resolving paths from `CLAUDE_PROJECT_DIR` and `~/.claude/` explicitly. See [issue #503](https://github.com/anthropics/claude-plugins-official/issues/503).

- **Write tool bypasses file rules (bug #3)** -- Rules with `event: file` only check `new_string` (the Edit tool's input key). The Write tool sends `content` instead, so its payload is never matched and `action: block` rules silently fail. Fixed by falling back through `content`, `new_string`, and `new_text` for all file-event tools. Upstream issue pending.

### JSON rule cache

The official plugin reads and parses every `.md` rule file (YAML frontmatter + markdown body) from disk on every hook event (~5ms). This fork parses once, serializes the result to a single JSON cache file, and reads that on subsequent events. The cache is invalidated automatically when any rule file's mtime changes.

| Metric | Official | This fork |
|---|---|---|
| Per-event latency (cold) | ~5ms | <1ms |
| Per-event latency (warm) | ~5ms | <0.1ms |

Set `HOOKIFY_NO_CACHE=1` to disable caching and always parse from disk.

### Cherry-picks from hookify-plus

The following improvements are cherry-picked from [adrozdenko/hookify-plus](https://github.com/adrozdenko/hookify-plus):

- `not_regex_match` operator -- negate a regex condition without writing a negative lookahead
- `value` key alias -- use `value:` as a synonym for `pattern:` in YAML conditions
- `read` event type -- Read, Glob, Grep, and LS tools get their own event bucket instead of falling through to `event: all`
- `permissionDecisionReason` in block output -- Claude sees *why* a rule blocked, not just that it was blocked
- `Update` tool support -- the Update tool is recognized as a file-event tool alongside Edit and Write
- Windows path quoting in generated `hooks.json`
- Fixed example rule file (corrected YAML frontmatter)

## Install

```
/plugin marketplace add Chris-Irving/hookify
/plugin install hookify@hookify
/reload-plugins
```

If you have the official hookify installed (`hookify@claude-plugins-official`), disable or remove it first to avoid duplicate hook registrations.

## Requirements

Python 3.10+

## Writing rules

Rules are markdown files with YAML frontmatter placed in `.claude/` (project scope) or `~/.claude/` (user scope). A minimal rule:

```markdown
---
name: block-dangerous-rm
enabled: true
event: bash
pattern: rm\s+-rf
action: block
---

Dangerous rm command detected. Verify the path before proceeding.
```

For the full rule syntax -- events, operators, fields, conditions, and advanced examples -- see the [upstream README](https://github.com/anthropics/claude-plugins-official/blob/main/plugins/hookify/README.md).

## Development

```bash
python3 -m pytest
python3 -m ruff check .
python3 -m ruff format .
```

## License

Apache 2.0 -- preserved from upstream.

## Credits

Original plugin by Anthropic. Bug fixes and cache by Chris Irving. Cherry-picks from [adrozdenko/hookify-plus](https://github.com/adrozdenko/hookify-plus).
