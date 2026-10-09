#!/usr/bin/env python3
"""Task state persistence, validation, and resumption engine.

Conforms to schemas/task-state.schema.json and provides atomic file-locked
writes, scoped SHA-256 source fingerprinting, and stale evidence detection.
"""

from __future__ import annotations

from contextlib import contextmanager
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile
import time
import unicodedata
from typing import Any, Dict, Iterator, List, Optional, Sequence, Set, Tuple, Union


SCHEMA_VERSION = 1
MAX_STATE_BYTES = 512 * 1024
STATE_LOCK_TIMEOUT_SECONDS = 3.0
STATE_LOCK_POLL_SECONDS = 0.05

TASK_ID_REGEX = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
AC_ID_REGEX = re.compile(r"^AC-[0-9]+$")
MILESTONE_ID_REGEX = re.compile(r"^M[0-9]+$")
HEX_SHA256_REGEX = re.compile(r"^[a-f0-9]{64}$")

VALID_TASK_STATUSES = {"pending", "in_progress", "completed", "blocked", "cancelled"}
VALID_MILESTONE_STATUSES = {"pending", "in_progress", "verified", "skipped"}
VALID_AC_STATUSES = {"pending", "in_progress", "verified", "superseded"}
VALID_TEST_COUNT_STATUSES = {"runner-enforced", "unverified"}
VALID_WORK_STATUSES = {"pending", "running", "completed", "failed", "blocked", "cancelled"}
FINAL_CHECK_ROLES = {"reviewer", "verifier", "harness-reviewer", "harness-verifier"}
MAX_WORK_ITEMS = 128
DEFAULT_MAX_WORKERS = 3
MAX_WORKERS = 8
FINGERPRINT_VERSION = 2
MAX_FINGERPRINT_FILES = 10000

IGNORED_FINGERPRINT_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    "site-packages",
    "build",
    "dist",
    ".tox",
    ".nox",
    ".pytest_cache",
    ".mypy_cache",
    "node_modules",
    "vendor",
    ".idea",
    ".vscode",
    ".harness",
}


def is_safe_task_id(task_id: str) -> bool:
    """Validate task_id against strict regex pattern."""
    if not isinstance(task_id, str):
        return False
    return bool(TASK_ID_REGEX.fullmatch(task_id))


def get_task_dir(workspace: Path, task_id: str) -> Path:
    """Resolve and validate task directory inside workspace/.harness/tasks/<task_id>."""
    if not is_safe_task_id(task_id):
        raise ValueError(f"Invalid task_id: {task_id!r}. Must match {TASK_ID_REGEX.pattern}")

    ws_resolved = workspace.resolve(strict=False)
    task_directory = (ws_resolved / ".harness" / "tasks" / task_id).resolve(strict=False)

    try:
        task_directory.relative_to(ws_resolved)
    except ValueError as err:
        raise ValueError(f"Task directory escapes workspace: {task_directory}") from err

    return task_directory


def get_task_state_path(workspace: Path, task_id: str) -> Path:
    """Get the path to state.json for a task."""
    return get_task_dir(workspace, task_id) / "state.json"


def _is_normalized_scope(value: Any) -> bool:
    """Accept literal relative scopes, never path aliases or glob expressions."""
    return (
        isinstance(value, str)
        and bool(value)
        and not value.startswith(("/", "~"))
        and not any(char in value for char in "\\:*?[]")
        and not any(ord(char) < 32 for char in value)
        and all(part not in {"", ".", ".."} for part in value.split("/"))
    )


def _validate_work_items(data: Dict[str, Any]) -> List[str]:
    """Validate the optional dependency graph without changing legacy checkpoints."""
    errors: List[str] = []
    max_workers = data.get("max_workers", DEFAULT_MAX_WORKERS)
    if type(max_workers) is not int or not 1 <= max_workers <= MAX_WORKERS:
        errors.append(f"max_workers must be an integer between 1 and {MAX_WORKERS}")
    if "work_items" not in data:
        return errors
    items = data["work_items"]
    if not isinstance(items, list):
        return errors + ["work_items must be an array"]
    if len(items) > MAX_WORK_ITEMS:
        errors.append(f"work_items must contain at most {MAX_WORK_ITEMS} entries")
        return errors

    milestones = data.get("milestones", [])
    milestone_ids = [ms.get("id") for ms in milestones if isinstance(ms, dict)] if isinstance(milestones, list) else []
    known_milestones = {ms_id for ms_id in milestone_ids if isinstance(ms_id, str)}
    if len(known_milestones) != len(milestone_ids):
        errors.append("work_items require unique valid milestone IDs")
    active_milestone = data.get("active_milestone")
    if not isinstance(active_milestone, str) or active_milestone not in known_milestones:
        errors.append("active_milestone must reference an existing milestone for work_items")

    graph: Dict[str, List[str]] = {}
    allowed = {"id", "milestone_id", "role", "status", "dependencies", "read_paths", "write_paths", "priority"}
    required = allowed - {"priority"}
    for idx, item in enumerate(items):
        label = f"work_items[{idx}]"
        if not isinstance(item, dict):
            errors.append(f"{label} must be an object")
            continue
        missing = required - item.keys()
        extra = item.keys() - allowed
        if missing:
            errors.append(f"{label} missing required properties: {sorted(missing)}")
        if extra:
            errors.append(f"{label} has unexpected keys: {sorted(extra)}")
        work_id = item.get("id")
        safe_id = is_safe_task_id(work_id)
        if not safe_id:
            errors.append(f"{label}.id must match {TASK_ID_REGEX.pattern}")
        elif work_id in graph:
            errors.append(f"Duplicate work item ID: {work_id}")
        milestone_id = item.get("milestone_id")
        if not isinstance(milestone_id, str) or milestone_id not in known_milestones:
            errors.append(f"{label}.milestone_id must reference an existing milestone")
        role = item.get("role")
        if not isinstance(role, str) or not role.strip():
            errors.append(f"{label}.role must be a non-empty string")
        if not isinstance(item.get("status"), str) or item["status"] not in VALID_WORK_STATUSES:
            errors.append(f"{label}.status invalid")
        dependencies = item.get("dependencies")
        valid_deps = isinstance(dependencies, list) and all(is_safe_task_id(dep) for dep in dependencies)
        if not valid_deps:
            errors.append(f"{label}.dependencies must be a list of safe work item IDs")
        elif len(set(dependencies)) != len(dependencies):
            errors.append(f"{label}.dependencies must be unique")
        if safe_id and work_id not in graph:
            graph[work_id] = dependencies if valid_deps else []
        for field in ("read_paths", "write_paths"):
            scopes = item.get(field)
            if not isinstance(scopes, list) or not all(_is_normalized_scope(scope) for scope in scopes):
                errors.append(f"{label}.{field} must contain normalized literal workspace-relative paths")
            elif len(set(scopes)) != len(scopes):
                errors.append(f"{label}.{field} must be unique")
        if isinstance(role, str) and role.strip().casefold() in FINAL_CHECK_ROLES and item.get("write_paths"):
            errors.append(f"{label} final reviewer/verifier must be read-only")
        priority = item.get("priority", 0)
        if type(priority) is not int or not -100 <= priority <= 100:
            errors.append(f"{label}.priority must be an integer between -100 and 100")

    for work_id, dependencies in graph.items():
        for dependency in dependencies:
            if dependency not in graph:
                errors.append(f"Work item {work_id} has unknown dependency: {dependency}")
    visiting: Set[str] = set()
    visited: Set[str] = set()

    def visit(work_id: str) -> bool:
        if work_id in visiting:
            return False
        if work_id in visited:
            return True
        visiting.add(work_id)
        for dependency in graph[work_id]:
            if dependency in graph and not visit(dependency):
                return False
        visiting.remove(work_id)
        visited.add(work_id)
        return True

    if any(not visit(work_id) for work_id in graph):
        errors.append("work_items dependencies must be acyclic")
    return errors


def validate_task_state(data: Any) -> Tuple[bool, List[str]]:
    """Validate task state data against task-state.schema.json constraints.

    Returns (is_valid, list_of_error_messages).
    """
    errors: List[str] = []
    if not isinstance(data, dict):
        return False, ["Root must be a JSON object"]

    # Allowed keys from schema
    allowed_keys = {
        "$schema",
        "schema_version",
        "task_id",
        "workspace",
        "status",
        "brief_revision",
        "active_milestone",
        "milestones",
        "acceptance_criteria",
        "source_fingerprint",
        "source_fingerprint_metadata",
        "evidence",
        "blockers",
        "next_action",
        "updated_at",
        "work_items",
        "max_workers",
    }
    extra_keys = set(data.keys()) - allowed_keys
    if extra_keys:
        errors.append(f"Unexpected properties: {sorted(extra_keys)}")

    # Required properties
    required_keys = [
        "schema_version",
        "task_id",
        "status",
        "brief_revision",
        "active_milestone",
        "milestones",
        "acceptance_criteria",
        "source_fingerprint",
    ]
    for req in required_keys:
        if req not in data:
            errors.append(f"Missing required property: {req}")

    # schema_version
    version = data.get("schema_version")
    if version != SCHEMA_VERSION:
        errors.append(f"schema_version must be {SCHEMA_VERSION}, got {version!r}")

    # task_id
    task_id = data.get("task_id")
    if not isinstance(task_id, str) or not TASK_ID_REGEX.fullmatch(task_id):
        errors.append(f"task_id {task_id!r} does not match pattern {TASK_ID_REGEX.pattern}")

    # workspace (optional string)
    if "workspace" in data and not isinstance(data["workspace"], str):
        errors.append("workspace must be a string")

    # status
    status = data.get("status")
    if status not in VALID_TASK_STATUSES:
        errors.append(f"Invalid status: {status!r}. Must be one of {sorted(VALID_TASK_STATUSES)}")

    # brief_revision
    if "brief_revision" in data and not isinstance(data["brief_revision"], str):
        errors.append("brief_revision must be a string")

    # active_milestone
    if "active_milestone" in data and not isinstance(data["active_milestone"], str):
        errors.append("active_milestone must be a string")

    # milestones
    milestones = data.get("milestones")
    if not isinstance(milestones, list):
        errors.append("milestones must be an array")
    else:
        for idx, ms in enumerate(milestones):
            if not isinstance(ms, dict):
                errors.append(f"milestones[{idx}] must be an object")
                continue
            ms_keys = set(ms.keys()) - {"id", "title", "status", "dependencies", "ac_ids"}
            if ms_keys:
                errors.append(f"milestones[{idx}] has unexpected keys: {sorted(ms_keys)}")
            ms_id = ms.get("id")
            if not isinstance(ms_id, str) or not MILESTONE_ID_REGEX.fullmatch(ms_id):
                errors.append(f"milestones[{idx}].id {ms_id!r} does not match {MILESTONE_ID_REGEX.pattern}")
            if not isinstance(ms.get("title"), str):
                errors.append(f"milestones[{idx}].title must be a string")
            ms_status = ms.get("status")
            if ms_status not in VALID_MILESTONE_STATUSES:
                errors.append(f"milestones[{idx}].status {ms_status!r} invalid")
            if "dependencies" in ms and not (isinstance(ms["dependencies"], list) and all(isinstance(d, str) for d in ms["dependencies"])):
                errors.append(f"milestones[{idx}].dependencies must be a list of strings")
            if "ac_ids" in ms and not (isinstance(ms["ac_ids"], list) and all(isinstance(a, str) for a in ms["ac_ids"])):
                errors.append(f"milestones[{idx}].ac_ids must be a list of strings")

    # acceptance_criteria
    valid_ac_ids: Set[str] = set()
    acs = data.get("acceptance_criteria")
    if not isinstance(acs, list):
        errors.append("acceptance_criteria must be an array")
    else:
        for idx, ac in enumerate(acs):
            if not isinstance(ac, dict):
                errors.append(f"acceptance_criteria[{idx}] must be an object")
                continue
            ac_keys = set(ac.keys()) - {"id", "outcome", "requirement_source", "planned_check", "status", "superseded_reason", "evidence_ids"}
            if ac_keys:
                errors.append(f"acceptance_criteria[{idx}] has unexpected keys: {sorted(ac_keys)}")
            ac_id = ac.get("id")
            if not isinstance(ac_id, str) or not AC_ID_REGEX.fullmatch(ac_id):
                errors.append(f"acceptance_criteria[{idx}].id {ac_id!r} does not match {AC_ID_REGEX.pattern}")
            else:
                valid_ac_ids.add(ac_id)
            if not isinstance(ac.get("outcome"), str) or not ac["outcome"].strip():
                errors.append(f"acceptance_criteria[{idx}].outcome must be a non-empty string")
            ac_status = ac.get("status")
            if ac_status not in VALID_AC_STATUSES:
                errors.append(f"acceptance_criteria[{idx}].status {ac_status!r} invalid")
            if ac_status == "superseded" and not ac.get("superseded_reason"):
                errors.append(f"acceptance_criteria[{idx}] superseded status requires superseded_reason")
            if "evidence_ids" in ac and not (isinstance(ac["evidence_ids"], list) and all(isinstance(e, str) for e in ac["evidence_ids"])):
                errors.append(f"acceptance_criteria[{idx}].evidence_ids must be a list of strings")

    # source_fingerprint
    sf = data.get("source_fingerprint")
    if not isinstance(sf, dict):
        errors.append("source_fingerprint must be an object mapping paths to SHA-256 strings")
    else:
        for path_key, digest in sf.items():
            if not _is_normalized_scope(path_key):
                errors.append(f"source_fingerprint path {path_key!r} must be a normalized workspace-relative path")
            if not isinstance(digest, str) or not HEX_SHA256_REGEX.fullmatch(digest):
                errors.append(f"source_fingerprint[{path_key!r}] hash {digest!r} must be 64-char hex SHA-256")

    metadata = data.get("source_fingerprint_metadata")
    if "source_fingerprint_metadata" in data:
        if not isinstance(metadata, dict):
            errors.append("source_fingerprint_metadata must be an object")
        else:
            if set(metadata) != {"version", "scope", "max_files"}:
                errors.append("source_fingerprint_metadata requires only version, scope, max_files")
            if type(metadata.get("version")) is not int or metadata["version"] != FINGERPRINT_VERSION:
                errors.append(f"source_fingerprint_metadata.version must be {FINGERPRINT_VERSION}")
            if metadata.get("scope") not in ("explicit", "auto"):
                errors.append("source_fingerprint_metadata.scope must be explicit or auto")
            limit = metadata.get("max_files")
            if type(limit) is not int or not 1 <= limit <= MAX_FINGERPRINT_FILES:
                errors.append(f"source_fingerprint_metadata.max_files must be between 1 and {MAX_FINGERPRINT_FILES}")

    # evidence (optional)
    if "evidence" in data:
        ev_list = data["evidence"]
        if not isinstance(ev_list, list):
            errors.append("evidence must be an array")
        else:
            for idx, ev in enumerate(ev_list):
                if not isinstance(ev, dict):
                    errors.append(f"evidence[{idx}] must be an object")
                    continue
                ev_keys = set(ev.keys()) - {"id", "ac_id", "command", "cwd", "test_target", "exit_code", "test_count_status", "timestamp"}
                if ev_keys:
                    errors.append(f"evidence[{idx}] has unexpected keys: {sorted(ev_keys)}")
                for req in ("ac_id", "command", "cwd", "exit_code"):
                    if req not in ev:
                        errors.append(f"evidence[{idx}] missing required property {req}")
                if "ac_id" in ev and isinstance(ev["ac_id"], str):
                    if valid_ac_ids and ev["ac_id"] not in valid_ac_ids:
                        errors.append(f"evidence[{idx}].ac_id {ev['ac_id']!r} does not match any acceptance_criteria id")
                if "id" in ev and not (isinstance(ev["id"], str) and ev["id"].strip()):
                    errors.append(f"evidence[{idx}].id must be a non-empty string")
                if "exit_code" in ev and not isinstance(ev["exit_code"], int):
                    errors.append(f"evidence[{idx}].exit_code must be integer")
                if "test_count_status" in ev and ev["test_count_status"] not in VALID_TEST_COUNT_STATUSES:
                    errors.append(f"evidence[{idx}].test_count_status invalid")

    # blockers, next_action, updated_at
    if "blockers" in data and not (isinstance(data["blockers"], list) and all(isinstance(b, str) for b in data["blockers"])):
        errors.append("blockers must be a list of strings")
    if "next_action" in data and not isinstance(data["next_action"], str):
        errors.append("next_action must be a string")
    if "updated_at" in data and not isinstance(data["updated_at"], (int, float)):
        errors.append("updated_at must be a timestamp number")

    errors.extend(_validate_work_items(data))

    return len(errors) == 0, errors


def plan_ready_work(state: Dict[str, Any], available_slots: Optional[int] = None) -> Dict[str, Any]:
    """Return a read-only launch plan; never invoke agents or update checkpoints.

    The coordinator must revalidate runtime worker IDs, capacity, source stability,
    authority, and file ownership before native dispatch. Completed work items are
    dependency bookkeeping, not authenticated test evidence or AC acceptance.
    Final roles use reviewer/verifier (optionally harness-prefixed); preparation
    must use separate read-only work items. Scopes are literal paths, overlap is
    conservatively case-insensitive, and symlinks are resolved against the actual
    workspace. Any existing directory scope serializes write-related comparisons
    with every counterpart because nested aliases cannot be ruled out without a
    scan; read/read sharing remains allowed. Prefer exact file scopes for parallel
    writers. Undeclared side effects and milestone-level dependency readiness remain
    coordinator responsibilities. A filesystem change after planning can invalidate
    this advisory result; this helper supplies neither filesystem locks nor a scheduler.
    """
    valid, errors = validate_task_state(state)
    if not valid:
        raise ValueError(f"Cannot plan invalid task state: {'; '.join(errors)}")
    if available_slots is not None and (type(available_slots) is not int or available_slots < 0):
        raise ValueError("available_slots must be a non-negative integer")
    items = state.get("work_items", [])
    max_workers = state.get("max_workers", DEFAULT_MAX_WORKERS)
    running = [item for item in items if item["status"] == "running"]
    capacity = max(0, max_workers - len(running))
    if available_slots is not None:
        capacity = min(capacity, available_slots)
    result: Dict[str, Any] = {
        "runnable": [], "waiting": {}, "running": [item["id"] for item in running],
        "max_workers": max_workers, "available_slots": capacity,
    }
    if not items:
        return result
    workspace = state.get("workspace")
    if not isinstance(workspace, str) or not Path(workspace).is_absolute():
        raise ValueError("Planning work_items requires an absolute workspace")
    try:
        root = Path(workspace).resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Planning workspace must be a directory")
        scopes: Dict[str, Dict[str, List[Path]]] = {}
        directory_scopes: Dict[Path, bool] = {}
        for item in items:
            scopes[item["id"]] = {}
            for field in ("read_paths", "write_paths"):
                resolved: List[Path] = []
                for scope in item[field]:
                    path = (root / scope).resolve(strict=False)
                    try:
                        path.relative_to(root)
                    except ValueError as err:
                        raise ValueError(f"Work item {item['id']} path escapes workspace: {scope}") from err
                    try:
                        directory_scopes[path] = stat.S_ISDIR(path.stat().st_mode)
                    except FileNotFoundError:
                        directory_scopes[path] = False
                    except OSError as err:
                        raise ValueError(f"Cannot inspect planning scope {scope}: {err}") from err
                    resolved.append(path)
                scopes[item["id"]][field] = resolved
    except (OSError, RuntimeError) as err:
        raise ValueError(f"Cannot resolve planning workspace/scopes: {err}") from err

    def overlaps(first: Path, second: Path) -> bool:
        if directory_scopes[first] or directory_scopes[second]:
            return True
        left = tuple(unicodedata.normalize("NFC", part).casefold() for part in first.parts)
        right = tuple(unicodedata.normalize("NFC", part).casefold() for part in second.parts)
        if left[:len(right)] == right or right[:len(left)] == left:
            return True
        try:
            return first.samefile(second)
        except (OSError, ValueError):
            return False

    def conflicts(first: Dict[str, Any], second: Dict[str, Any]) -> bool:
        left, right = scopes[first["id"]], scopes[second["id"]]
        return any(overlaps(a, b) for a in left["write_paths"] for b in right["read_paths"] + right["write_paths"]) or any(
            overlaps(a, b) for a in left["read_paths"] for b in right["write_paths"]
        )

    for index, item in enumerate(running):
        for other in running[index + 1:]:
            if conflicts(item, other):
                raise ValueError(f"Already-running work items have conflicting read/write scopes: {item['id']}, {other['id']}")

    by_id = {item["id"]: item for item in items}
    children: Dict[str, List[str]] = {work_id: [] for work_id in by_id}
    for item in items:
        for dependency in item["dependencies"]:
            children[dependency].append(item["id"])
    depths: Dict[str, int] = {}

    def downstream_depth(work_id: str) -> int:
        if work_id not in depths:
            depths[work_id] = max((1 + downstream_depth(child) for child in children[work_id]), default=0)
        return depths[work_id]

    active = state["active_milestone"]
    writers = [item for item in items if item["milestone_id"] == active and item["write_paths"]]
    if any(writer["status"] != "completed" for writer in writers) and any(
        item["milestone_id"] == active and item["role"].strip().casefold() in FINAL_CHECK_ROLES for item in running
    ):
        raise ValueError("Running final reviewer/verifier requires all active milestone writers completed")
    candidates = sorted(enumerate(items), key=lambda pair: (-downstream_depth(pair[1]["id"]), -pair[1].get("priority", 0), pair[0]))
    selected: List[Dict[str, Any]] = []
    for _, item in candidates:
        if item["status"] != "pending":
            continue
        work_id = item["id"]
        reason: Optional[str] = None
        if state["status"] in {"completed", "cancelled"}:
            reason = f"Task is {state['status']}"
        elif item["milestone_id"] != active:
            reason = "Milestone is not active"
        else:
            unfinished = [dep for dep in item["dependencies"] if by_id[dep]["status"] != "completed"]
            if unfinished:
                reason = "Dependencies not completed: " + ", ".join(f"{dep} ({by_id[dep]['status']})" for dep in unfinished)
            elif item["role"].strip().casefold() in FINAL_CHECK_ROLES and any(writer["status"] != "completed" for writer in writers):
                reason = "Final review/verification awaits all active milestone writers"
            else:
                owner = next((other["id"] for other in running + selected if conflicts(item, other)), None)
                if owner:
                    reason = f"Read/write scope conflicts with {owner}"
                elif len(selected) >= capacity:
                    reason = "No available worker slot"
        if reason:
            result["waiting"][work_id] = reason
        else:
            selected.append(item)
            result["runnable"].append(work_id)
    return result


def compute_file_sha256(path: Path) -> Optional[str]:
    """Compute a legacy content-only digest, following the supplied path.

    Returns None if missing, unreadable or non-regular. This helper does not
    establish workspace provenance; snapshots use the checked manifest instead.
    """
    try:
        if not path.is_file():
            return None
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            while chunk := f.read(64 * 1024):
                hasher.update(chunk)
        return hasher.hexdigest()
    except (OSError, ValueError):
        return None


def compute_source_fingerprint(
    workspace: Path,
    paths: Optional[Sequence[str]] = None,
    max_files: int = 150,
) -> Dict[str, str]:
    """Return path -> v2 manifest SHA-256, retaining the dictionary interface.

    Explicit paths include missing and non-file entries. Digests cover kind,
    permission mode, resolved path, link text and regular-file content. Directory
    entries describe that exact path, not recursive directory contents. Automatic
    scope uses the existing source-extension/ignored-directory policy and raises
    rather than silently returning a truncated, unreadable or unsafe snapshot.
    Persist through capture_source_snapshot to identify v2 coverage; untagged
    legacy dictionaries remain loadable but cannot preserve verified evidence.
    """
    if type(max_files) is not int or not 1 <= max_files <= MAX_FINGERPRINT_FILES:
        raise ValueError(f"max_files must be an integer between 1 and {MAX_FINGERPRINT_FILES}")
    try:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Fingerprint workspace must be a directory")
        if paths is not None:
            if isinstance(paths, (str, bytes)):
                raise ValueError("Fingerprint paths must be a sequence of path strings")
            requested = list(paths)
            if not all(_is_normalized_scope(path) for path in requested):
                raise ValueError("Fingerprint paths must be normalized workspace-relative literals")
            selected = sorted(set(requested))
            if len(selected) > max_files:
                raise ValueError("Explicit fingerprint scope exceeds max_files")
        else:
            selected: List[str] = []

            def scan_error(error: OSError) -> None:
                raise ValueError(f"Cannot enumerate fingerprint scope: {error}") from error

            extensions = {".py", ".ts", ".js", ".mjs", ".go", ".rs", ".json", ".md", ".sh", ".toml", ".yml", ".yaml"}
            for root_dir, dirnames, filenames in os.walk(root, onerror=scan_error, followlinks=False):
                dirnames[:] = sorted(name for name in dirnames if name not in IGNORED_FINGERPRINT_DIRS and not name.startswith("."))
                for name in dirnames:
                    if stat.S_ISLNK((Path(root_dir) / name).lstat().st_mode):
                        raise ValueError("Auto fingerprint cannot cover a directory symlink; use explicit file scope")
                for name in sorted(filenames):
                    if not name.startswith(".") and Path(name).suffix.casefold() in extensions:
                        selected.append((Path(root_dir) / name).relative_to(root).as_posix())
                        if len(selected) > max_files:
                            raise ValueError("Auto fingerprint scope exceeds max_files; use a complete explicit scope or larger bound")
        return {relative: _source_entry_digest(root, relative) for relative in selected}
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Cannot establish source fingerprint: {error}") from error


def _stat_identity(info: os.stat_result) -> Tuple[int, ...]:
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _source_entry_digest(root: Path, relative: str) -> str:
    """Hash one safe entry; reject observed changes during inspection."""
    lexical = root / relative
    resolved = lexical.resolve(strict=False)
    try:
        resolved_relative = resolved.relative_to(root).as_posix()
    except ValueError as error:
        raise ValueError(f"Fingerprint path escapes workspace: {relative}") from error
    entry: Dict[str, Any] = {"resolved_path": resolved_relative}
    try:
        before = lexical.lstat()
    except FileNotFoundError:
        entry["kind"] = "missing"
    else:
        entry["mode"] = stat.S_IMODE(before.st_mode)
        is_link = stat.S_ISLNK(before.st_mode)
        if is_link:
            entry["kind"] = "symlink"
            entry["link_target"] = os.readlink(lexical)
        try:
            target_info = resolved.lstat()
        except FileNotFoundError:
            if not is_link:
                raise ValueError(f"Source changed during fingerprint: {relative}")
            target: Dict[str, Any] = {"kind": "missing"}
        else:
            target = {"mode": stat.S_IMODE(target_info.st_mode)}
            if stat.S_ISREG(target_info.st_mode):
                target["kind"] = "file"
                digest = hashlib.sha256()
                descriptor = os.open(resolved, os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0))
                with os.fdopen(descriptor, "rb") as handle:
                    if _stat_identity(os.fstat(handle.fileno())) != _stat_identity(target_info):
                        raise ValueError(f"Source changed before fingerprint read: {relative}")
                    while chunk := handle.read(64 * 1024):
                        digest.update(chunk)
                    if _stat_identity(os.fstat(handle.fileno())) != _stat_identity(target_info):
                        raise ValueError(f"Source changed during fingerprint read: {relative}")
                target["content_sha256"] = digest.hexdigest()
            elif stat.S_ISDIR(target_info.st_mode):
                target["kind"] = "directory"
            elif stat.S_ISLNK(target_info.st_mode):
                raise ValueError(f"Source changed during symlink resolution: {relative}")
            else:
                target.update(kind="other", file_type=stat.S_IFMT(target_info.st_mode))
            if _stat_identity(resolved.lstat()) != _stat_identity(target_info):
                raise ValueError(f"Source changed during fingerprint: {relative}")
        if is_link:
            entry["target"] = target
        else:
            entry.update(target)
        if _stat_identity(lexical.lstat()) != _stat_identity(before) or lexical.resolve(strict=False) != resolved:
            raise ValueError(f"Source changed during fingerprint: {relative}")
    return hashlib.sha256(json.dumps(entry, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def capture_source_snapshot(workspace: Path, paths: Optional[Sequence[str]] = None, max_files: int = 150) -> Dict[str, Any]:
    """Capture both v2 fingerprint fields for a new, scoped checkpoint baseline.

    A new baseline does not authenticate prior checks or upgrade legacy evidence.
    Callers must establish that their declared scope covers the relevant inputs.
    """
    return {
        "source_fingerprint": compute_source_fingerprint(workspace, paths, max_files),
        "source_fingerprint_metadata": {"version": FINGERPRINT_VERSION, "scope": "auto" if paths is None else "explicit", "max_files": max_files},
    }


@contextmanager
def task_state_lock(lock_file: Path, timeout: float = STATE_LOCK_TIMEOUT_SECONDS) -> Iterator[bool]:
    """Hold a cross-process lock on a task state lockfile with bounded timeout."""
    try:
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = open(lock_file, "a+b")
    except OSError:
        yield False
        return

    acquired = False
    deadline = time.monotonic() + timeout
    try:
        if os.name == "nt":
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()

        while not acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except (BlockingIOError, OSError):
                if time.monotonic() >= deadline:
                    break
                time.sleep(STATE_LOCK_POLL_SECONDS)

        yield acquired
    finally:
        if acquired:
            try:
                if os.name == "nt":
                    import msvcrt
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        try:
            handle.close()
        except OSError:
            pass


def save_task_state(workspace: Path, state: Dict[str, Any], timeout: float = STATE_LOCK_TIMEOUT_SECONDS) -> Path:
    """Validate and atomically save task state to .harness/tasks/<task_id>/state.json."""
    is_valid, errors = validate_task_state(state)
    if not is_valid:
        raise ValueError(f"Cannot save invalid task state: {'; '.join(errors)}")

    task_id = state["task_id"]
    state_path = get_task_state_path(workspace, task_id)
    state_dir = state_path.parent
    state_dir.mkdir(parents=True, exist_ok=True)

    # Work on an isolated deep copy so caller dictionary is not mutated
    state_to_save = copy.deepcopy(state)
    if "workspace" not in state_to_save:
        state_to_save["workspace"] = str(workspace.resolve(strict=False))

    state_to_save["updated_at"] = time.time()
    serialized = json.dumps(state_to_save, indent=2, ensure_ascii=False).encode("utf-8")
    if len(serialized) > MAX_STATE_BYTES:
        raise ValueError(f"Task state exceeds maximum allowed size ({len(serialized)} > {MAX_STATE_BYTES} bytes)")

    lock_file = state_dir / "state.json.lock"
    with task_state_lock(lock_file, timeout=timeout) as locked:
        if not locked:
            raise TimeoutError(f"Could not acquire lock for task state {state_path} within {timeout}s")

        temp_fd, temp_name = tempfile.mkstemp(
            prefix=".state.tmp.",
            dir=str(state_dir),
        )
        try:
            with os.fdopen(temp_fd, "wb") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, state_path)
        except Exception:
            if os.path.exists(temp_name):
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
            raise

    return state_path


def load_task_state(workspace: Path, task_id: str) -> Optional[Dict[str, Any]]:
    """Safely load and validate task state from .harness/tasks/<task_id>/state.json.

    Returns None if missing, corrupted, or schema invalid.
    """
    if not is_safe_task_id(task_id):
        return None

    state_path = get_task_state_path(workspace, task_id)
    if not state_path.is_file():
        return None

    try:
        size = state_path.stat().st_size
        if size > MAX_STATE_BYTES or size == 0:
            return None
        content = state_path.read_text(encoding="utf-8")
        data = json.loads(content)
        is_valid, _ = validate_task_state(data)
        if not is_valid:
            return None
        return data
    except (OSError, json.JSONDecodeError, ValueError):
        return None


def find_active_tasks(workspace: Path) -> List[Dict[str, Any]]:
    """Find all valid task states under workspace/.harness/tasks/, sorted by updated_at descending."""
    ws_resolved = workspace.resolve(strict=False)
    tasks_root = ws_resolved / ".harness" / "tasks"
    if not tasks_root.is_dir():
        return []

    results: List[Dict[str, Any]] = []
    try:
        for entry in tasks_root.iterdir():
            if entry.is_dir() and is_safe_task_id(entry.name):
                state = load_task_state(workspace, entry.name)
                if state:
                    results.append(state)
    except OSError:
        pass

    results.sort(key=lambda s: s.get("updated_at", 0), reverse=True)
    return results


def assess_task_resumption(
    workspace: Path,
    task_id_or_state: Union[str, Dict[str, Any]],
    current_brief_revision: Optional[str] = None,
) -> Dict[str, Any]:
    """Assess whether a task can be safely resumed and detect any stale evidence.

    Checks:
    1. Provenance: Task existence and workspace match.
    2. Brief: Checks if brief revision changed.
    3. Source drift: Re-computes SHA-256 for all fingerprinted files.
    4. Stale evidence: If source files changed, identifies affected ACs.
    """
    ws_resolved = workspace.resolve(strict=False)
    if isinstance(task_id_or_state, str):
        state = load_task_state(workspace, task_id_or_state)
        if not state:
            return {
                "can_resume": False,
                "task_id": task_id_or_state,
                "status": "missing_or_corrupt",
                "reasons": ["Task state does not exist or is corrupted"],
                "changed_files": [],
                "stale_ac_ids": [],
                "valid_ac_ids": [],
            }
    else:
        state = task_id_or_state

    task_id = state.get("task_id", "unknown")
    status = state.get("status", "unknown")
    active_milestone = state.get("active_milestone", "")
    reasons: List[str] = []

    if status in {"completed", "cancelled"}:
        reasons.append(f"Task is already {status}")

    # Check workspace provenance
    metadata = state.get("source_fingerprint_metadata")
    provenance_matches = False
    legacy_reconstruction = False
    stored_ws = state.get("workspace")
    if not isinstance(stored_ws, str) or not stored_ws or not Path(stored_ws).is_absolute():
        legacy_reconstruction = metadata is None
        reasons.append("Workspace provenance is missing or not absolute; verified evidence cannot be reused")
    else:
        try:
            stored_ws_resolved = Path(stored_ws).resolve(strict=True)
            provenance_matches = stored_ws_resolved == ws_resolved and stored_ws_resolved.is_dir()
            if not provenance_matches:
                reasons.append(f"Workspace provenance mismatch: expected {stored_ws}, current {ws_resolved}")
        except (OSError, ValueError, RuntimeError) as error:
            reasons.append(f"Workspace provenance could not be established: {error}")

    # Check brief revision
    brief_changed = False
    if current_brief_revision and current_brief_revision != state.get("brief_revision"):
        brief_changed = True
        reasons.append(
            f"Brief revision changed from {state.get('brief_revision')!r} to {current_brief_revision!r}"
        )

    # Check source fingerprint drift
    stored_fingerprint: Dict[str, str] = state.get("source_fingerprint", {})
    changed_files: List[str] = []
    missing_files: List[str] = []

    coverage_verified = False
    if metadata is None:
        reasons.append("Legacy source fingerprint has no v2 coverage metadata; re-establish scope and checks")
    elif not provenance_matches:
        reasons.append("Source fingerprint cannot be reused for a different or unverified workspace")
    else:
        try:
            valid, errors = validate_task_state(state)
            if not valid:
                raise ValueError("Invalid checkpoint fingerprint: " + "; ".join(errors))
            current = compute_source_fingerprint(
                ws_resolved,
                paths=list(stored_fingerprint) if metadata["scope"] == "explicit" else None,
                max_files=metadata["max_files"],
            )
            coverage_verified = True
            changed_files = [relative for relative in sorted(set(stored_fingerprint) | set(current))
                             if stored_fingerprint.get(relative) != current.get(relative)]
            for relative in stored_fingerprint:
                try:
                    (ws_resolved / relative).lstat()
                except FileNotFoundError:
                    missing_files.append(relative)
        except (ValueError, OSError, RuntimeError) as error:
            coverage_verified = False
            reasons.append(f"Source fingerprint coverage could not be established: {error}")

    if changed_files:
        reasons.append(f"Source files changed since checkpoint ({len(changed_files)} files modified/missing)")

    # Identify valid vs stale ACs
    all_acs = state.get("acceptance_criteria", [])
    valid_ac_ids: List[str] = []
    stale_ac_ids: List[str] = []

    for ac in all_acs:
        ac_id = ac.get("id", "")
        ac_status = ac.get("status")
        if ac_status == "verified":
            if brief_changed or changed_files or not coverage_verified:
                stale_ac_ids.append(ac_id)
            else:
                valid_ac_ids.append(ac_id)
        elif ac_status in {"pending", "in_progress"}:
            pass
        elif ac_status == "superseded":
            pass

    can_resume = status in {"pending", "in_progress", "blocked"} and (provenance_matches or legacy_reconstruction)

    return {
        "can_resume": can_resume,
        "task_id": task_id,
        "status": status,
        "active_milestone": active_milestone,
        "source_clean": coverage_verified and len(changed_files) == 0,
        "fingerprint_coverage_verified": coverage_verified,
        "changed_files": sorted(changed_files),
        "missing_files": sorted(missing_files),
        "stale_ac_ids": sorted(stale_ac_ids),
        "valid_ac_ids": sorted(valid_ac_ids),
        "reasons": reasons,
    }


def main() -> None:
    """CLI utility for inspecting, managing, and validating task state."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="task_state.py",
        description="Task state persistence, validation, and resumption utility",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # init
    init_parser = subparsers.add_parser("init", help="Initialize a new task checkpoint")
    init_parser.add_argument("--task-id", required=True, help="Unique task identifier (^[a-zA-Z0-9_-]{1,64}$)")
    init_parser.add_argument("--milestones", default="M1", help="Comma-separated milestone IDs (e.g. M1,M2)")
    init_parser.add_argument("--acs", default="AC-1", help="Comma-separated AC IDs (e.g. AC-1,AC-2)")
    init_parser.add_argument("--brief-revision", default="rev-1", help="Brief revision string")
    init_parser.add_argument("--workspace", default=".", help="Target workspace path")
    init_parser.add_argument("--scope-path", action="append", default=None,
                             help="Exact workspace-relative source input; repeat for a complete explicit scope (missing paths are retained)")
    init_parser.add_argument("--max-files", type=int, default=150,
                             help=f"Fingerprint file-count bound, 1..{MAX_FINGERPRINT_FILES} (default: 150)")

    # list
    list_parser = subparsers.add_parser("list", help="List active tasks in workspace")
    list_parser.add_argument("workspace", nargs="?", default=".", help="Workspace path")

    # resume
    resume_parser = subparsers.add_parser("resume", help="Assess resumption status and drift for a task")
    resume_parser.add_argument("task_id", help="Task ID to assess")
    resume_parser.add_argument("workspace", nargs="?", default=".", help="Workspace path")
    resume_parser.add_argument("--brief-revision", default=None, help="Current brief revision if checking change")

    # inspect (alias)
    inspect_parser = subparsers.add_parser("inspect", help="Inspect a task checkpoint")
    inspect_parser.add_argument("task_id", help="Task ID to inspect")
    inspect_parser.add_argument("workspace", nargs="?", default=".", help="Workspace path")
    inspect_parser.add_argument("--brief-revision", default=None, help="Current brief revision")

    # validate
    validate_parser = subparsers.add_parser("validate", help="Validate a state.json file against schema")
    validate_parser.add_argument("target", help="Path to state.json or task_id in workspace")
    validate_parser.add_argument("workspace", nargs="?", default=".", help="Workspace path if target is a task_id")

    # fingerprint
    fp_parser = subparsers.add_parser("fingerprint", help="Compute source fingerprint for workspace")
    fp_parser.add_argument("workspace", nargs="?", default=".", help="Workspace path")

    dispatch_parser = subparsers.add_parser("dispatch-plan", help="Print ready work without launching agents or modifying state")
    dispatch_parser.add_argument("--task-id", required=True, help="Task ID to plan")
    dispatch_parser.add_argument("--workspace", default=".", help="Workspace path")
    dispatch_parser.add_argument("--available-slots", type=int, default=None, help="Current runtime capacity for new workers")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "init":
        ws = Path(args.workspace).resolve()
        ms_ids = [m.strip() for m in args.milestones.split(",") if m.strip()]
        ac_ids = [a.strip() for a in args.acs.split(",") if a.strip()]
        milestones = [
            {"id": m, "title": f"Milestone {m}", "status": "in_progress" if idx == 0 else "pending"}
            for idx, m in enumerate(ms_ids)
        ]
        acs = [
            {"id": a, "outcome": f"Criterion {a}", "requirement_source": "CLI init", "planned_check": "runner check", "status": "pending"}
            for a in ac_ids
        ]
        new_state = {
            "schema_version": SCHEMA_VERSION,
            "task_id": args.task_id,
            "workspace": str(ws),
            "status": "in_progress",
            "brief_revision": args.brief_revision,
            "active_milestone": ms_ids[0] if ms_ids else "M1",
            "milestones": milestones,
            "acceptance_criteria": acs,
        }
        try:
            new_state.update(capture_source_snapshot(ws, paths=args.scope_path, max_files=args.max_files))
            saved = save_task_state(ws, new_state)
            print(f"Initialized task {args.task_id} state at {saved}")
        except Exception as err:
            print(f"Failed to initialize task state: {err}", file=sys.stderr)
            if "fingerprint" in str(err).casefold() or "max_files" in str(err):
                print(f"Use repeated --scope-path for all relevant exact inputs, or --max-files N (1..{MAX_FINGERPRINT_FILES}) for a complete bounded scan.", file=sys.stderr)
            sys.exit(1)

    elif args.command == "list":
        ws = Path(args.workspace).resolve()
        tasks = find_active_tasks(ws)
        print(f"Found {len(tasks)} tasks in {ws}:")
        for t in tasks:
            print(f" - {t['task_id']} [{t['status']}] active: {t['active_milestone']} (updated: {t.get('updated_at')})")

    elif args.command in ("resume", "inspect"):
        ws = Path(args.workspace).resolve()
        state = load_task_state(ws, args.task_id)
        if not state:
            print(f"Task {args.task_id} not found or corrupted in {ws}", file=sys.stderr)
            sys.exit(1)
        assessment = assess_task_resumption(ws, state, current_brief_revision=args.brief_revision)
        print(json.dumps(assessment, indent=2))

    elif args.command == "dispatch-plan":
        ws = Path(args.workspace).resolve()
        try:
            state = load_task_state(ws, args.task_id)
            if state is None:
                raise ValueError(f"Task {args.task_id} not found or corrupted in {ws}")
            if state.get("workspace") and Path(state["workspace"]).resolve() != ws:
                raise ValueError("Task workspace provenance mismatch")
            state["workspace"] = str(ws)
            print(json.dumps(plan_ready_work(state, args.available_slots), indent=2))
        except (ValueError, OSError, RuntimeError) as err:
            print(f"Cannot produce dispatch plan: {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "validate":
        target_path = Path(args.target)
        if not target_path.is_file():
            ws = Path(args.workspace).resolve()
            candidate = get_task_state_path(ws, args.target)
            if candidate.is_file():
                target_path = candidate
            else:
                print(f"Error: file not found: {args.target}", file=sys.stderr)
                sys.exit(1)
        try:
            content = json.loads(target_path.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"JSON decode error in {target_path}: {e}", file=sys.stderr)
            sys.exit(1)
        is_valid, errors = validate_task_state(content)
        if is_valid:
            print(f"Valid: {target_path} conforms to schema.")
        else:
            print(f"Invalid: {target_path} has errors:", file=sys.stderr)
            for err in errors:
                print(f" - {err}", file=sys.stderr)
            sys.exit(1)

    elif args.command == "fingerprint":
        ws = Path(args.workspace).resolve()
        fp = compute_source_fingerprint(ws)
        print(json.dumps(fp, indent=2))


if __name__ == "__main__":
    main()
