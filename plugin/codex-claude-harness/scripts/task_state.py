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
import sys
import tempfile
import time
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
        "evidence",
        "blockers",
        "next_action",
        "updated_at",
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
            if not isinstance(path_key, str) or not path_key:
                errors.append(f"source_fingerprint path {path_key!r} must be a non-empty string")
            if not isinstance(digest, str) or not HEX_SHA256_REGEX.fullmatch(digest):
                errors.append(f"source_fingerprint[{path_key!r}] hash {digest!r} must be 64-char hex SHA-256")

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

    return len(errors) == 0, errors


def compute_file_sha256(path: Path) -> Optional[str]:
    """Compute deterministic SHA-256 of a regular file.

    Returns None if missing, unreadable, directory, or symlink escaping root.
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
    """Generate a deterministic dictionary of relative path -> SHA-256 for scoped source files.

    If paths is provided, only inspects those paths.
    Otherwise, inspects relevant source/test/config files in workspace up to max_files.
    """
    ws_resolved = workspace.resolve(strict=False)
    fingerprint: Dict[str, str] = {}

    if paths is not None:
        for rel in sorted(paths):
            p = (ws_resolved / rel).resolve(strict=False)
            try:
                p.relative_to(ws_resolved)
            except ValueError:
                continue
            digest = compute_file_sha256(p)
            if digest is not None:
                # Store normalized posix relative path
                fingerprint[Path(rel).as_posix()] = digest
        return fingerprint

    # Auto-scan workspace for relevant code/config files
    candidate_paths: List[Path] = []
    for root_dir, dirnames, filenames in os.walk(ws_resolved):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_FINGERPRINT_DIRS and not d.startswith(".")]
        for fname in filenames:
            if fname.startswith("."):
                continue
            ext = os.path.splitext(fname)[1].casefold()
            if ext in {".py", ".ts", ".js", ".mjs", ".go", ".rs", ".json", ".md", ".sh", ".toml", ".yml", ".yaml"}:
                candidate_paths.append(Path(root_dir) / fname)
                if len(candidate_paths) >= max_files:
                    break
        if len(candidate_paths) >= max_files:
            break

    for p in sorted(candidate_paths):
        try:
            rel = p.relative_to(ws_resolved).as_posix()
        except ValueError:
            continue
        digest = compute_file_sha256(p)
        if digest is not None:
            fingerprint[rel] = digest

    return fingerprint


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
        return {
            "can_resume": False,
            "task_id": task_id,
            "status": status,
            "active_milestone": active_milestone,
            "reasons": reasons,
            "changed_files": [],
            "stale_ac_ids": [],
            "valid_ac_ids": [ac["id"] for ac in state.get("acceptance_criteria", []) if ac.get("status") == "verified"],
        }

    # Check workspace provenance
    stored_ws = state.get("workspace")
    if stored_ws:
        stored_ws_resolved = Path(stored_ws).resolve(strict=False)
        if stored_ws_resolved != ws_resolved:
            reasons.append(f"Workspace provenance mismatch: expected {stored_ws}, current {ws_resolved}")

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

    for rel_path, expected_hash in stored_fingerprint.items():
        curr_file = ws_resolved / rel_path
        if not curr_file.exists():
            missing_files.append(rel_path)
            changed_files.append(rel_path)
        else:
            actual_hash = compute_file_sha256(curr_file)
            if actual_hash != expected_hash:
                changed_files.append(rel_path)

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
            if brief_changed or changed_files:
                stale_ac_ids.append(ac_id)
            else:
                valid_ac_ids.append(ac_id)
        elif ac_status in {"pending", "in_progress"}:
            pass
        elif ac_status == "superseded":
            pass

    can_resume = status in {"pending", "in_progress", "blocked"}

    return {
        "can_resume": can_resume,
        "task_id": task_id,
        "status": status,
        "active_milestone": active_milestone,
        "source_clean": len(changed_files) == 0,
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
            "source_fingerprint": compute_source_fingerprint(ws),
        }
        try:
            saved = save_task_state(ws, new_state)
            print(f"Initialized task {args.task_id} state at {saved}")
        except Exception as err:
            print(f"Failed to initialize task state: {err}", file=sys.stderr)
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
