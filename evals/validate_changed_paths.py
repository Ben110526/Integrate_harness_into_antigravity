#!/usr/bin/env python3
"""Validate that an eval changed every required path and no protected path."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from typing import Optional, Set


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


def main() -> int:
    if len(sys.argv) != 4:
        print(
            "usage: validate_changed_paths.py REPOSITORY REQUIRED_JSON ALLOWED_JSON",
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
