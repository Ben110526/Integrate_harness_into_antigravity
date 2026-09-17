#!/usr/bin/env python3
"""Workspace wrapper for task_state module."""

import os
from pathlib import Path
import sys

# Ensure plugin scripts directory is importable
PLUGIN_SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "plugin"
    / "codex-claude-harness"
    / "scripts"
)
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

from task_state import *  # noqa: F401, F403
import task_state

if __name__ == "__main__":
    task_state.main()
