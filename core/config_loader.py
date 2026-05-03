#!/usr/bin/env python3
"""Configuration loader for hookify plugin.

Loads and parses .claude/hookify.*.local.md files.
"""

from __future__ import annotations

import glob
import os
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Condition:
    """A single condition for matching."""

    field: str  # "command", "new_text", "old_text", "file_path", etc.
    operator: str  # "regex_match", "contains", "equals", etc.
    pattern: str  # Pattern to match

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Condition:
        """Create Condition from dict."""
        pattern = data.get("pattern")
        if pattern is None:
            pattern = data.get("value", "")
        return cls(
            field=data.get("field", ""),
            operator=data.get("operator", "regex_match"),
            pattern=pattern,
        )


@dataclass
class Rule:
    """A hookify rule."""

    name: str
    enabled: bool
    event: str  # "bash", "file", "stop", "all", etc.
    pattern: str | None = None  # Simple pattern (legacy)
    conditions: list[Condition] = field(default_factory=list)
    action: str = "warn"  # "warn" or "block" (future)
    tool_matcher: str | None = None  # Override tool matching
    message: str = ""  # Message body from markdown

    @classmethod
    def from_dict(cls, frontmatter: dict[str, Any], message: str) -> Rule:
        """Create Rule from frontmatter dict and message body."""
        # Handle both simple pattern and complex conditions
        conditions = []

        # New style: explicit conditions list
        if "conditions" in frontmatter:
            cond_list = frontmatter["conditions"]
            if isinstance(cond_list, list):
                conditions = [Condition.from_dict(c) for c in cond_list]

        # Legacy style: simple pattern field
        simple_pattern = frontmatter.get("pattern")
        if simple_pattern and not conditions:
            # Convert simple pattern to condition
            # Infer field from event
            event = frontmatter.get("event", "all")
            if event == "bash":
                field = "command"
            elif event == "file":
                field = "new_text"
            else:
                field = "content"

            conditions = [Condition(field=field, operator="regex_match", pattern=simple_pattern)]

        return cls(
            name=frontmatter.get("name", "unnamed"),
            enabled=frontmatter.get("enabled", True),
            event=frontmatter.get("event", "all"),
            pattern=simple_pattern,
            conditions=conditions,
            action=frontmatter.get("action", "warn"),
            tool_matcher=frontmatter.get("tool_matcher"),
            message=message.strip(),
        )


def extract_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Extract YAML frontmatter and message body from markdown.

    Returns (frontmatter_dict, message_body).

    Supports multi-line dictionary items in lists by preserving indentation.
    """
    if not content.startswith("---"):
        return {}, content

    # Split on --- markers
    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter_text = parts[1]
    message = parts[2].strip()

    # Simple YAML parser that handles indented list items
    frontmatter = {}
    lines = frontmatter_text.split("\n")

    current_key = None
    current_list = []
    current_dict = {}
    in_list = False
    in_dict_item = False

    for line in lines:
        # Skip empty lines and comments
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # Check indentation level
        indent = len(line) - len(line.lstrip())

        # Top-level key (no indentation or minimal)
        if indent == 0 and ":" in line and not line.strip().startswith("-"):
            # Save previous list/dict if any
            if in_list and current_key:
                if in_dict_item and current_dict:
                    current_list.append(current_dict)
                    current_dict = {}
                frontmatter[current_key] = current_list
                in_list = False
                in_dict_item = False
                current_list = []

            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()

            if not value:
                # Empty value - list or nested structure follows
                current_key = key
                in_list = True
                current_list = []
            else:
                # Simple key-value pair
                value = value.strip('"').strip("'")
                if value.lower() == "true":
                    value = True
                elif value.lower() == "false":
                    value = False
                frontmatter[key] = value

        # List item (starts with -)
        elif stripped.startswith("-") and in_list:
            # Save previous dict item if any
            if in_dict_item and current_dict:
                current_list.append(current_dict)
                current_dict = {}

            item_text = stripped[1:].strip()

            # Check if this is an inline dict (key: value on same line)
            if ":" in item_text and "," in item_text:
                # Inline comma-separated dict: "- field: command, operator: regex_match"
                item_dict = {}
                for part in item_text.split(","):
                    if ":" in part:
                        k, v = part.split(":", 1)
                        item_dict[k.strip()] = v.strip().strip('"').strip("'")
                current_list.append(item_dict)
                in_dict_item = False
            elif ":" in item_text:
                # Start of multi-line dict item: "- field: command"
                in_dict_item = True
                k, v = item_text.split(":", 1)
                current_dict = {k.strip(): v.strip().strip('"').strip("'")}
            else:
                # Simple list item
                current_list.append(item_text.strip('"').strip("'"))
                in_dict_item = False

        # Continuation of dict item (indented under list item)
        elif indent > 2 and in_dict_item and ":" in line:
            # This is a field of the current dict item
            k, v = stripped.split(":", 1)
            current_dict[k.strip()] = v.strip().strip('"').strip("'")

    # Save final list/dict if any
    if in_list and current_key:
        if in_dict_item and current_dict:
            current_list.append(current_dict)
        frontmatter[current_key] = current_list

    return frontmatter, message


def _resolve_rule_dirs() -> list[str]:
    """Return the list of .claude directories to search for rule files.

    Order: project-local first, then user-global. If they resolve to the same
    real path (e.g. CWD == $HOME), return only one entry to avoid double-loading.
    """
    project_dir = os.path.realpath(os.path.join(os.getcwd(), ".claude"))
    global_dir = os.path.realpath(os.path.join(os.path.expanduser("~"), ".claude"))

    if project_dir == global_dir:
        return [project_dir]
    return [project_dir, global_dir]


def _current_source_mtimes() -> dict[str, float]:
    """Glob both rule dirs and stat every matching file.

    Returns a dict mapping absolute file paths to their ``st_mtime``.
    """
    mtimes: dict[str, float] = {}
    for rule_dir in _resolve_rule_dirs():
        pattern = os.path.join(rule_dir, "hookify.*.local.md")
        for file_path in sorted(glob.glob(pattern)):
            try:
                mtimes[file_path] = os.path.getmtime(file_path)
            except OSError:
                # File vanished between glob and stat — skip it
                continue
    return mtimes


def _parse_and_merge_rules() -> list[Rule]:
    """Parse all rule files from both dirs and merge by name.

    Project rules take precedence over global rules with the same name.
    A project rule with ``enabled: false`` suppresses a global rule
    with the same name.

    Returns all enabled rules (no event filtering).
    """
    by_name: dict[str, Rule] = {}
    suppressed: set = set()

    for rule_dir in _resolve_rule_dirs():
        pattern = os.path.join(rule_dir, "hookify.*.local.md")
        files = sorted(glob.glob(pattern))

        for file_path in files:
            try:
                rule = load_rule_file(file_path)
                if not rule:
                    continue

                # Skip if name already seen (project wins) or suppressed
                if rule.name in by_name or rule.name in suppressed:
                    continue

                # Disabled rule: record suppression but don't include
                if not rule.enabled:
                    suppressed.add(rule.name)
                    continue

                by_name[rule.name] = rule

            except (OSError, PermissionError) as e:
                # File I/O errors - log and continue
                print(f"Warning: Failed to read {file_path}: {e}", file=sys.stderr)
                continue
            except (ValueError, KeyError, AttributeError, TypeError) as e:
                # Parsing errors - log and continue
                print(f"Warning: Failed to parse {file_path}: {e}", file=sys.stderr)
                continue
            except Exception as e:
                # Unexpected errors - log with type details
                print(
                    f"Warning: Unexpected error loading {file_path} ({type(e).__name__}): {e}",
                    file=sys.stderr,
                )
                continue

    return list(by_name.values())


def _filter_by_event(rules: list[Rule], event: str | None) -> list[Rule]:
    """Return rules matching *event*.

    A rule matches if ``event`` is None (no filter), ``rule.event == 'all'``,
    or ``rule.event == event``.
    """
    if event is None:
        return rules
    return [r for r in rules if r.event == "all" or r.event == event]


def load_rules(event: str | None = None) -> list[Rule]:
    """Load hookify rules from project-local and user-global .claude directories.

    Uses a JSON cache when available (see ``core.cache``).  The cache is
    bypassed when ``HOOKIFY_NO_CACHE`` is set to a truthy value.

    Searches <cwd>/.claude/ first, then ~/.claude/. Project rules take
    precedence over global rules with the same ``name``. A project rule with
    ``enabled: false`` suppresses a global rule with the same name.

    Args:
        event: Optional event filter ("bash", "file", "stop", etc.)

    Returns:
        List of enabled Rule objects matching the event.
    """
    # Import cache module here to avoid circular import
    # (cache.py imports Condition/Rule from config_loader)
    from core.cache import (
        cache_path_for,
        is_bypass_enabled,
        is_cache_valid,
        load_from_cache,
        save_to_cache,
    )

    CACHE_MIN_RULES = 5

    # Bypass mode: skip cache entirely
    if is_bypass_enabled():
        rules = _parse_and_merge_rules()
        return _filter_by_event(rules, event)

    current_mtimes = _current_source_mtimes()

    # Small rule sets are faster without the cache overhead
    if len(current_mtimes) < CACHE_MIN_RULES:
        rules = _parse_and_merge_rules()
        return _filter_by_event(rules, event)

    # Resolve directories for cache key
    dirs = _resolve_rule_dirs()
    project_dir = dirs[0]
    global_dir = dirs[-1]  # same as project_dir when CWD == $HOME

    cp = cache_path_for(project_dir, global_dir)

    # Try loading from cache
    cached = load_from_cache(cp)
    if cached is not None:
        cached_rules, cached_sources = cached
        if is_cache_valid(cached_sources, current_mtimes):
            return _filter_by_event(cached_rules, event)

    # Cache miss or invalid — parse from disk and save
    rules = _parse_and_merge_rules()
    save_to_cache(cp, rules, current_mtimes)
    return _filter_by_event(rules, event)


def load_rule_file(file_path: str) -> Rule | None:
    """Load a single rule file.

    Returns:
        Rule object or None if file is invalid.
    """
    try:
        with open(file_path) as f:
            content = f.read()

        frontmatter, message = extract_frontmatter(content)

        if not frontmatter:
            print(
                f"Warning: {file_path} missing YAML frontmatter (must start with ---)",
                file=sys.stderr,
            )
            return None

        rule = Rule.from_dict(frontmatter, message)
        return rule

    except (OSError, PermissionError) as e:
        print(f"Error: Cannot read {file_path}: {e}", file=sys.stderr)
        return None
    except (ValueError, KeyError, AttributeError, TypeError) as e:
        print(f"Error: Malformed rule file {file_path}: {e}", file=sys.stderr)
        return None
    except UnicodeDecodeError as e:
        print(f"Error: Invalid encoding in {file_path}: {e}", file=sys.stderr)
        return None
    except Exception as e:
        print(
            f"Error: Unexpected error parsing {file_path} ({type(e).__name__}): {e}",
            file=sys.stderr,
        )
        return None


# For testing
if __name__ == "__main__":
    import sys

    # Test frontmatter parsing
    test_content = """---
name: test-rule
enabled: true
event: bash
pattern: "rm -rf"
---

⚠️ Dangerous command detected!
"""

    fm, msg = extract_frontmatter(test_content)
    print("Frontmatter:", fm)
    print("Message:", msg)

    rule = Rule.from_dict(fm, msg)
    print("Rule:", rule)
