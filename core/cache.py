#!/usr/bin/env python3
"""JSON rule cache for hookify plugin.

Serializes parsed Rule objects to a JSON cache file so that subsequent
hook events can skip YAML frontmatter parsing and file I/O.  Invalidation
is mtime-based: if any source .md file has been added, removed, or
modified since the cache was written, the cache is rebuilt.

See docs/plans/2026-05-03-spec-json-cache.md for full specification.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import sys
import tempfile
from typing import Any

from core.config_loader import Condition, Rule

# Bump CACHE_SCHEMA_VERSION when the on-disk format changes in a way
# that old readers cannot handle.  Old caches are silently rebuilt.
CACHE_SCHEMA_VERSION = 1
SCHEMA_REVISION = "2026-05-03"

_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_bypass_enabled() -> bool:
    """Return True if HOOKIFY_NO_CACHE env var is set to a truthy value.

    Truthy values: ``1``, ``true``, ``yes``, ``on`` (case-insensitive).
    """
    value = os.environ.get("HOOKIFY_NO_CACHE", "")
    return value.strip().lower() in _TRUTHY_VALUES


def cache_path_for(project_dir: str, global_dir: str) -> str:
    """Compute the cache file path for the given rule directories.

    Uses ``${CLAUDE_PLUGIN_ROOT}/.cache/<key>.json`` where *key* is the
    first 16 hex characters of
    ``sha256(realpath(project_dir) + "\\0" + realpath(global_dir))``.

    Falls back to ``${XDG_CACHE_HOME:-~/.cache}/hookify/<key>.json``
    when ``CLAUDE_PLUGIN_ROOT`` is unset.
    """
    real_project = os.path.realpath(project_dir)
    real_global = os.path.realpath(global_dir)
    key = hashlib.sha256(f"{real_project}\0{real_global}".encode()).hexdigest()[:16]

    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT")
    if plugin_root:
        cache_dir = os.path.join(plugin_root, ".cache")
    else:
        xdg_cache = os.environ.get("XDG_CACHE_HOME", os.path.join(os.path.expanduser("~"), ".cache"))
        cache_dir = os.path.join(xdg_cache, "hookify")

    return os.path.join(cache_dir, f"{key}.json")


def load_from_cache(cache_path: str) -> tuple[list[Rule], dict[str, float]] | None:
    """Load rules and source mtimes from a cache file.

    Returns ``None`` if the cache is absent, contains corrupt JSON,
    has a mismatched schema version, or has an unexpected top-level
    structure.  Warnings are logged to stderr on errors.

    On success returns ``(rules, sources)`` where *rules* is a list of
    reconstructed :class:`Rule` objects and *sources* maps source file
    paths to their ``st_mtime`` at cache-write time.
    """
    try:
        with open(cache_path) as f:
            data = json.load(f)
    except FileNotFoundError:
        return None
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        print(f"Warning: cache read failed ({cache_path}): {exc}", file=sys.stderr)
        return None

    # Structural validation
    if not isinstance(data, dict):
        print(f"Warning: cache has unexpected top-level type ({cache_path})", file=sys.stderr)
        return None

    if data.get("version") != CACHE_SCHEMA_VERSION:
        print(
            f"Warning: cache schema version mismatch ({cache_path}): "
            f"expected {CACHE_SCHEMA_VERSION}, got {data.get('version')}",
            file=sys.stderr,
        )
        return None

    sources = data.get("sources")
    raw_rules = data.get("rules")

    if not isinstance(sources, dict) or not isinstance(raw_rules, list):
        print(f"Warning: cache has unexpected structure ({cache_path})", file=sys.stderr)
        return None

    # Reconstruct Rule objects
    rules: list[Rule] = []
    for rd in raw_rules:
        if not isinstance(rd, dict):
            print(f"Warning: skipping non-dict rule entry in cache ({cache_path})", file=sys.stderr)
            continue
        conditions = [
            Condition.from_dict(c) for c in rd.get("conditions", []) if isinstance(c, dict)
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

    return rules, sources


def save_to_cache(cache_path: str, rules: list[Rule], sources: dict[str, float]) -> bool:
    """Atomically write rules and source mtimes to the cache file.

    Uses a write-to-temp-then-``os.replace`` pattern for atomicity.
    Creates the cache directory if it does not exist.

    Returns ``True`` on success, ``False`` on failure (logged to stderr).
    """
    payload: dict[str, Any] = {
        "version": CACHE_SCHEMA_VERSION,
        "schema_revision": SCHEMA_REVISION,
        "sources": sources,
        "rules": [_rule_to_dict(r) for r in rules],
    }

    cache_dir = os.path.dirname(cache_path)
    try:
        os.makedirs(cache_dir, exist_ok=True)
    except OSError as exc:
        print(f"Warning: cannot create cache directory ({cache_dir}): {exc}", file=sys.stderr)
        return False

    tmp_fd = None
    tmp_path = None
    try:
        tmp_fd, tmp_path = tempfile.mkstemp(dir=cache_dir, suffix=".tmp")
        with os.fdopen(tmp_fd, "w") as f:
            tmp_fd = None  # os.fdopen takes ownership
            json.dump(payload, f)
        os.replace(tmp_path, cache_path)
        tmp_path = None  # replaced successfully; nothing to clean up
        return True
    except OSError as exc:
        print(f"Warning: cache write failed ({cache_path}): {exc}", file=sys.stderr)
        return False
    finally:
        # Clean up temp file if replace didn't happen
        if tmp_fd is not None:
            os.close(tmp_fd)
        if tmp_path is not None:
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)


def is_cache_valid(sources_in_cache: dict[str, float], current_files: dict[str, float]) -> bool:
    """Return True iff the cached sources match current files exactly.

    Both the file set (keys) AND the mtimes (values) must match.
    """
    return sources_in_cache == current_files


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


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
