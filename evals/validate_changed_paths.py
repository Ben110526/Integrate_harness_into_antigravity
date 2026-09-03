#!/usr/bin/env python3
"""Validate that an eval changed every required path and no protected path."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Optional, Set, Tuple


def changed_path_error(
    changed: Set[str], required: Set[str], allowed: Set[str]
) -> Optional[str]:
    missing = sorted(required - changed)
    if missing:
        return f"required paths were not changed: {missing}"
    unexpected = sorted(changed - allowed)
    if unexpected:
        return f"paths outside the eval allowlist were changed: {unexpected}"
    return None


def repository_changed_paths(repository: pathlib.Path) -> Set[str]:
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=str(repository),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return {line[3:] for line in status if len(line) >= 4}


def unified_diff_shape(diff_text: str) -> Tuple[int, int]:
    """Return (hunks, added-plus-deleted-lines) for a text unified diff."""
    hunks = 0
    changed_lines = 0
    in_hunk = False
    for line in diff_text.splitlines():
        if line.startswith("diff --git "):
            in_hunk = False
        elif line.startswith("@@"):
            hunks += 1
            in_hunk = True
        elif not in_hunk and line.startswith(("+++", "---")):
            continue
        elif in_hunk and line.startswith(("+", "-")):
            changed_lines += 1
    return hunks, changed_lines


def diff_shape_error(
    diff_text: str, max_hunks: int, max_changed_lines: int
) -> Optional[str]:
    if "GIT binary patch" in diff_text or "Binary files " in diff_text:
        return "binary diffs are not eligible for the inline fast path"
    hunks, changed_lines = unified_diff_shape(diff_text)
    if hunks > max_hunks:
        return f"diff has {hunks} hunks; maximum is {max_hunks}"
    if changed_lines > max_changed_lines:
        return (
            f"diff has {changed_lines} added/deleted lines; "
            f"maximum is {max_changed_lines}"
        )
    return None


def repository_diff(repository: pathlib.Path) -> str:
    return subprocess.run(
        ["git", "diff", "--no-ext-diff", "--no-color", "--unified=0", "HEAD", "--"],
        cwd=str(repository),
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def main() -> int:
    if len(sys.argv) not in {4, 6}:
        print(
            "usage: validate_changed_paths.py REPOSITORY REQUIRED_JSON ALLOWED_JSON "
            "[MAX_HUNKS MAX_CHANGED_LINES]",
            file=sys.stderr,
        )
        return 2
    changed = repository_changed_paths(pathlib.Path(sys.argv[1]))
    required = set(json.loads(sys.argv[2]))
    allowed = set(json.loads(sys.argv[3]))
    error = changed_path_error(changed, required, allowed)
    if error:
        print(error, file=sys.stderr)
        return 1
    if len(sys.argv) == 6:
        shape_error = diff_shape_error(
            repository_diff(pathlib.Path(sys.argv[1])),
            int(sys.argv[4]),
            int(sys.argv[5]),
        )
        if shape_error:
            print(shape_error, file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
