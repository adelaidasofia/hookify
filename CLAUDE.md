# Hookify re-fork

Clean-room reimplementation of a faster, bug-fixed hookify Claude Code
plugin. NOT a copy of any prior work — reimplemented from scratch based
on the official plugin's public architecture and documented bugs.

## First thing: read the research

`~/dev/docs/research/2026-05-02-hookify-claude-code-plugin.md` — full
analysis of the official plugin, the known bugs (7+ open issues),
community forks (hookify-plus), performance numbers, and the specific
improvements to target. Read it before writing any code.

## Goals

1. **Fix the import-path bug** — official plugin breaks with
   `No module named 'hookify'` due to Claude Code's versioned cache
   path (`hookify/0.1.0/` vs expected `hookify/core/`). Must work from
   user scope / globally, not just project root. Issues: #13427,
   #13470, #13568, #13612, #14459, #15793, #28299 (claude-code repo),
   #20 (claude-plugins-official repo).

2. **JSON-based rule caching** — the official plugin reads and parses
   .md rule files (YAML frontmatter + markdown body) from disk on
   EVERY hook event (~5ms). Parse once → serialize parsed rules to a
   JSON cache file → read the single JSON blob on subsequent events.
   Invalidate when any .md rule file's mtime changes. Target: <1ms
   cold cache, <0.1ms warm.

3. **Find and fix the second bug** — surfaces while fixing #1. Document
   it when found.

4. **Cherry-pick from community forks** — evaluate hookify-plus
   (adrozdenko) for: `not_regex_match`, `value` key, `read` event
   support. Take what's good; skip what's not.

## Non-goals

- Don't change hookify's markdown-rule authoring UX — it's good as-is
- Don't add features beyond what's needed to fix bugs + add caching
  until the base is solid
- Don't make this paint-oh-specific — this is a general-purpose plugin

## Reference

- Official plugin: https://github.com/anthropics/claude-code/tree/main/plugins/hookify
- Official README: https://github.com/anthropics/claude-plugins-official/blob/main/plugins/hookify/README.md
- hookify-plus (community fork): https://github.com/adrozdenko/hookify-plus
- Claude Code hooks docs: https://code.claude.com/docs/en/hooks
- Claude Code plugins docs: https://github.com/anthropics/claude-code/blob/main/plugins/README.md

## Performance targets

| Metric | Official | Target |
|---|---|---|
| Per-event latency (cold) | ~5ms | <1ms |
| Per-event latency (warm) | ~5ms | <0.1ms |
| Cache invalidation | N/A (no cache) | mtime-based on .md rule files |

## Architecture notes

Official hookify uses these Claude Code hook types:
- **Command hooks** — run a shell command
- **Prompt hooks** — send a prompt to Claude for single-turn evaluation
- Rule files are markdown with YAML frontmatter (hook event, pattern,
  action)

The caching layer sits between "hook event fires" and "read + parse
rule files." It doesn't change which hook types are used or how rules
are authored — it just eliminates the repeated file I/O + YAML parse.
