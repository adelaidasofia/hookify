# Specification — JSON Rule Cache

**Date:** 2026-05-03
**Status:** Draft (awaiting Chris's approval)
**Consumer:** `core/cache.py` (new module), called by
`core/config_loader.py:load_rules()`

## Purpose

Eliminate the per-hook-event YAML parse + file-I/O cost by
serializing parsed `Rule` objects to a JSON cache file, and on
subsequent hook events loading from the cache via `json.loads()`
instead of re-parsing markdown rule files.

Target performance for the cache step itself: <1 ms cold load
(cache absent or invalid), <0.1 ms warm load (cache valid).

The cache primarily reduces disk I/O thrashing — repeated YAML
parsing of the same files on every hook event is wasteful even when
fast — and removes a long-tail latency risk on slow or contended
filesystems (NFS, encrypted volumes). README perf claims will stay
modest (no "100x" headline); benchmarks on the target machine
will be added when implementation is complete.

## Inputs

| Input | Type | Source | Notes |
|---|---|---|---|
| `event` | `Optional[str]` | Caller argument | Same filter as `load_rules()` |
| Project rule directory | filesystem | Resolved by `config_loader` | `<cwd>/.claude/` |
| Global rule directory | filesystem | Resolved by `config_loader` | `~/.claude/` |
| Cache directory | filesystem | `${CLAUDE_PLUGIN_ROOT}/.cache/` | Created on first write; auto-cleaned on plugin version bump |
| `CLAUDE_PLUGIN_ROOT` env var | str | Set by Claude Code at hook execution | Required; if absent, fall back to `${XDG_CACHE_HOME:-~/.cache}/hookify/` |
| `HOOKIFY_NO_CACHE` env var | str / unset | Environment | If set to any truthy value, bypass cache entirely |

## Outputs

| Scenario | Output |
|---|---|
| Cache valid, found | `List[Rule]` reconstructed from JSON |
| Cache invalid (mtime mismatch, file set changed) | Re-parse from `.md` files; write new cache; return `List[Rule]` |
| Cache absent (first run, after manual deletion) | Re-parse from `.md` files; write cache; return `List[Rule]` |
| Cache read fails (corruption, JSON error, etc.) | Log to stderr; re-parse from `.md`; overwrite cache; return `List[Rule]` |
| Cache write fails (permission, disk full, etc.) | Log to stderr; return `List[Rule]` (load succeeds; cache just isn't persisted) |
| `HOOKIFY_NO_CACHE` set | Skip cache read AND write entirely; behave as if no caching exists |

## Behavior

### Standard load path (cache hit)

1. Compute cache key: `sha256(realpath(project_dir) + "\0" + realpath(global_dir))[:16]`
2. Cache file path: `<cache_dir>/<key>.json`
3. Read JSON. Validate top-level `version` field matches expected schema version.
4. For each entry in `sources`, compare cached `mtime` to current
   `os.stat(...).st_mtime` of that file
5. Glob `project_dir` and `global_dir` for `hookify.*.local.md`;
   compare set against cached `sources` keys
6. If all mtimes match AND file sets match exactly → **cache hit**
7. Reconstruct `Rule` objects from `rules` array
8. Apply event filter; return

### Cache miss / invalidation path

1. Re-run full upstream load: glob, parse YAML, build `Rule` objects,
   apply override semantics from spec #1
2. Build cache payload (see schema below)
3. Atomic write to `<key>.tmp`, then `os.replace(tmp, final)`
4. Apply event filter; return

### Cache-bypass path (`HOOKIFY_NO_CACHE` set)

- Skip step 1-7 entirely; go straight to full parse path
- Do NOT write cache afterward (so the env var is symmetric — it
  doesn't accidentally update a stale cache)

## Cache file schema

JSON file. Schema version `1`.

```json
{
  "version": 1,
  "schema_revision": "2026-05-03",
  "sources": {
    "/Users/chris/proj/.claude/hookify.dangerous-rm.local.md": 1735000000.0,
    "/Users/chris/.claude/hookify.research-save.local.md": 1735000123.0
  },
  "rules": [
    {
      "name": "dangerous-rm",
      "enabled": true,
      "event": "bash",
      "pattern": "rm\\s+-rf",
      "conditions": [
        {"field": "command", "operator": "regex_match", "pattern": "rm\\s+-rf"}
      ],
      "action": "warn",
      "tool_matcher": null,
      "message": "⚠️ Dangerous command detected!",
      "_source_path": "/Users/chris/proj/.claude/hookify.dangerous-rm.local.md",
      "_source_scope": "project"
    }
  ]
}
```

**Field notes:**

- `version` — schema version. If bumped in a future release, old caches are auto-invalidated and rebuilt.
- `schema_revision` — date string for human debugging (which release wrote this cache). Not used for invalidation.
- `sources` — every source `.md` file path mapped to its `st_mtime` at cache write time. Used for invalidation.
- `rules` — list of fully-resolved rules in load order (project rules first, then global rules per spec #1).
- `_source_path` and `_source_scope` — debugging aids; not load-bearing for behavior. Kept lightweight for grep/jq inspection of cache contents.

## Cache file location

**Decision: `${CLAUDE_PLUGIN_ROOT}/.cache/<key>.json`**

Where `<key> = sha256(realpath(project_dir) + "\0" + realpath(global_dir))[:16]`.

`CLAUDE_PLUGIN_ROOT` is set by Claude Code when hook scripts run, and
resolves to `~/.claude/plugins/cache/<marketplace>/<plugin>/<version>/`.

**Why this:**

- **Plugin-native convention** — `CLAUDE_PLUGIN_ROOT` is the canonical
  per-plugin location per `plugin-dev`'s plugin-structure guidance;
  using a `.cache/` subdirectory under it keeps state plugin-isolated.
- **Auto-cleaned on plugin version bump** — when v0.3.0 ships, its
  cache lives in `<plugin-root>/0.3.0/.cache/`, naturally orphaning
  the v0.2.0 cache without manual housekeeping.
- **Plugin-uninstall cleans up** — removing the plugin removes the
  cache; no orphan files in the user's home directory.
- **No source-tree pollution** — projects don't get a
  `.hookify-cache.json` to gitignore.
- **Per-(project, global) keying** — different working directories
  get different cache files within the plugin's `.cache/`; no
  cross-project contamination.
- **Truncated hash (16 hex chars / 64 bits)** — short enough to type
  for debugging, long enough to avoid collisions in any realistic
  deployment.

**Fallback:** If `CLAUDE_PLUGIN_ROOT` is unset (e.g., running tests
or from a non-plugin context), use
`${XDG_CACHE_HOME:-~/.cache}/hookify/<key>.json` instead. The env var
is normally always set by Claude Code at hook execution time, but
the fallback keeps test runs and direct script invocations working.

**Why not the alternatives:**

| Alt | Rejected because |
|---|---|
| `${XDG_CACHE_HOME:-~/.cache}/hookify/` | Survives plugin uninstall (orphan files); doesn't auto-clean on version bump; less plugin-native |
| Per-source-dir cache (`<dir>/.hookify-cache.json`) | Pollutes user repos; requires gitignore guidance |
| Single global cache file (one `cache.json` for everything) | Cross-project contamination; write contention across concurrent invocations |
| Per-PID cache | Multiplies cache files; useless if process is short-lived (which hook scripts are) |

**Note on prior art:** Chris's earlier work at Ally landed on
plugin-cache location for this same reason. The "unknown version"
issue mentioned in his prior recall is fixed in this fork by adding
the `version: "0.2.0"` field to `plugin.json`.

## Multi-process safety

**Decision: atomic write-rename, no locking.**

```python
def _write_cache_atomic(path: str, data: dict) -> None:
    tmp_path = f"{path}.tmp.{os.getpid()}"
    with open(tmp_path, "w") as f:
        json.dump(data, f)
    os.replace(tmp_path, path)  # atomic on POSIX and Windows
```

**Why no locking:**

- Hook scripts are short-lived (~50 ms total). Lock contention would
  block hooks from running.
- Stale reads are harmless — a hook that loads a cache one update
  behind just behaves identically to a hook from one moment earlier.
- Concurrent writers race; the loser's write is lost but the cache
  remains internally consistent (atomic rename either wins or loses
  in full).
- File locks (`fcntl`) introduce complexity, can deadlock, and are
  Unix-specific; not justified for this use case.

## Cache invalidation triggers

The cache is considered invalid (will trigger full re-parse) if:

| Condition | Detected by |
|---|---|
| Cache file does not exist | `os.path.exists(cache_path) == False` |
| Cache file unreadable / corrupt JSON | `json.JSONDecodeError`, `OSError`, `UnicodeDecodeError` |
| Schema version mismatch | `cache["version"] != EXPECTED_VERSION` |
| Source file added | `set(current_glob) - set(cache["sources"]) != ∅` |
| Source file removed | `set(cache["sources"]) - set(current_glob) != ∅` |
| Source file modified | `os.stat(path).st_mtime != cache["sources"][path]` |
| Source file deleted between mtime check and parse | Caught by exception handler in load path; treated as miss |

## Acceptance criteria

- [ ] Cold-cache load (cache absent) on a typical rule set (5-10 rules) completes in <1 ms after Python startup
- [ ] Warm-cache load (cache valid) completes in <0.1 ms after Python startup
- [ ] Cache invalidates when any source `.md` file is modified
- [ ] Cache invalidates when a source `.md` file is added or removed
- [ ] `HOOKIFY_NO_CACHE=1` skips cache entirely (read AND write)
- [ ] Cache file at unexpected schema version is silently rebuilt
- [ ] Corrupt JSON in cache file is handled (rebuild, no crash)
- [ ] Concurrent invocations from two terminal sessions don't corrupt the cache
- [ ] No source-tree pollution (no cache files written into project's `.claude/` or `~/.claude/`)
- [ ] Cache bypass (`HOOKIFY_NO_CACHE`) results identical to current upstream behavior — used as the regression baseline in tests
- [ ] All `Rule`/`Condition` objects round-trip through cache (no field loss, no type drift)

## Explicitly excluded (YAGNI)

- **In-process memoization** — Python's `lru_cache` for the regex
  compile is already in upstream; we don't add an additional in-memory
  layer. Each hook invocation is a fresh process anyway.
- **Cache compression** — caches are small (kilobytes); gzip adds
  CPU cost without space benefit.
- **Cache warming on plugin install** — the first hook event
  populates it; that 5ms cold cost is fine for first-fire.
- **TTL-based expiration** — mtime is the source of truth; no time-based
  staleness needed.
- **Cache statistics / hit-rate logging** — adds I/O on every hook
  event; benchmark separately if needed.
- **Distributed cache (Redis, etc.)** — solo-developer tool, not a
  service.
- **Encrypted cache** — rule content is not sensitive; YAML rule files
  themselves are plaintext on disk.
- **Caching compiled regex objects** — `re.Pattern` doesn't serialize
  to JSON cleanly, and `lru_cache` already covers re-use within a
  process.

## Alternatives considered

### Alternative storage: SQLite — REJECTED

Chris's prior work at Ally explored SQLite for caching rule
frontmatter with SQL-style lookup. Tested implementation worked
correctly but did not improve overall performance — the bottleneck
is YAML parse cost, not lookup speed. SQLite added open-database +
prepared-statement overhead that outweighed any indexing benefit at
this rule-count scale (typically 5-50 rules).

The JSON approach wins specifically because it stores
**already-parsed** structures: `json.loads()` returns ready-to-use
dicts in microseconds, bypassing YAML entirely. SQLite would only
help if we were doing complex queries; we just need "load the whole
ruleset for this scope."

### Alternative storage: Python's native binary serialization — REJECTED

The `pickle` module is faster than JSON for round-tripping, but
unsuitable here:

1. Platform/version-dependent — a cache written by Python 3.11 may
   not load cleanly on 3.10.
2. Known security caveats (arbitrary code execution on malicious
   input). Even though our cache files are user-local, this is a
   class of vulnerability we don't need to expose.
3. JSON cache files are debuggable with `cat`, `jq`, `less`. Native
   binary files require a Python REPL.

JSON's portability and inspectability outweigh the small speed
advantage of native serialization.

### Alternative invalidation: content hash — REJECTED

Hashing every source file on every invocation would add O(file-size)
work per check. mtime check is O(1) per file via a single `stat()`
syscall. mtime is sufficient for correctness given that:

- Rule files are user-edited via normal file operations (which update
  mtime)
- We catch file-set changes (add/remove) separately via glob
  comparison
- The risk case (user manually setting mtime backwards via `touch -d`)
  is rare and self-corrects on next legitimate edit

### Alternative invalidation: directory mtime — REJECTED

Directory mtime doesn't update when a file IN the directory is
modified — only when entries are added/removed. We need both axes
(set changes AND content changes), so per-file mtime is the minimum
sufficient mechanism.

### Alternative language: Rust or Go for the cache — REJECTED

Question revisited: would a compiled language for the cache
mechanism (or the full hook entrypoint) yield meaningful gains?

**Per-event latency breakdown:**

| Component | Python (current) | Hypothetical Rust |
|---|---|---|
| Interpreter / binary startup | ~30-50 ms | ~1-5 ms |
| Cache read + JSON parse (warm) | <0.1 ms | <0.05 ms |
| Cache miss + YAML parse (cold) | ~5 ms | ~1-2 ms |
| Rule evaluation (regex) | <1 ms | <1 ms |
| **Total per event (warm)** | **~30-51 ms** | **~2-6 ms** |

For just the cache module, Rust offers no meaningful win — the
cache work is already <1 ms in Python; a compiled rewrite saves
maybe 0.5 ms while the surrounding Python interpreter adds 30+ ms.

For the full hook entrypoint, Rust would yield a real ~10x
wall-clock improvement (~30-50 ms → ~3-6 ms). But this requires:

1. Rewriting ~600 lines of Python (config loader, rule engine, hook
   handlers, YAML parser substitute)
2. Per-architecture binary distribution (arm64-darwin, x86_64-darwin,
   x86_64-linux, x86_64-windows)
3. Loss of the upstream-merge path entirely — Anthropic distributes
   Python plugins; a Rust rewrite cannot be merged into the Python
   codebase
4. Loss of hot-fix friendliness — `.py` edits ship instantly; binary
   releases need rebuild + repackage per arch
5. Rust toolchain dependency for contributors

The cost-benefit doesn't match the project's goals (fork-and-fix-
bugs, hope upstream merges, drop-in Python compatibility). Sticking
with Python is correct.

**Smaller speed-ups also rejected:**

- `orjson` / `ujson` (faster JSON parsers) — saves <0.1 ms on
  kilobyte caches; adds a non-stdlib dependency for negligible gain
- `mypyc` / Cython compilation — Python's *startup* dominates, not
  execution speed; compiled Python doesn't help the dominant cost

## Open questions for Chris

None — every multi-defensible-answer item has an explicit
recommendation above. Confirm or push back on any specific one.
