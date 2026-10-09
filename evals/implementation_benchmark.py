#!/usr/bin/env python3
"""Explicitly authorized repeated implementation pilots with independent oracles."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import platform
import re
import shutil
import statistics
import stat
import subprocess
import sys
import tempfile
import time

try:
    from . import quota_benchmark as quota
except ImportError:
    import quota_benchmark as quota

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
MAX_REPEAT = 10
MAX_CASES = 5
LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
POLICY_START = b"<!-- auto-harness:start -->"
POLICY_END = b"<!-- auto-harness:end -->"


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot(workspace):
    """Bounded content/mode snapshot; generated caches and root git state are separate."""
    result = {".": ("directory", b"", stat.S_IMODE(workspace.stat().st_mode))}
    size = 0
    for directory, directories, files in os.walk(str(workspace), followlinks=False):
        parent = pathlib.Path(directory)
        for name in list(directories):
            path = parent / name
            if (parent == workspace and name == ".git") or name == "__pycache__":
                directories.remove(name)
                continue
            if path.is_symlink():
                raise quota.BenchmarkError("fixture contains a symlink")
            result[path.relative_to(workspace).as_posix()] = ("directory", b"", stat.S_IMODE(path.stat().st_mode))
        for name in files:
            if name.endswith((".pyc", ".pyo")):
                continue
            path = parent / name
            if path.is_symlink() or not path.is_file():
                raise quota.BenchmarkError("fixture contains an unsupported entry")
            length = path.stat().st_size
            size += length
            if length > quota.MAX_SNAPSHOT_FILE_BYTES or size > quota.MAX_SNAPSHOT_BYTES:
                raise quota.BenchmarkError("fixture exceeds snapshot size limit")
            result[path.relative_to(workspace).as_posix()] = ("file", path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
        if len(result) > quota.MAX_SNAPSHOT_ENTRIES:
            raise quota.BenchmarkError("fixture exceeds snapshot entry limit")
    return result


def snapshot_digest(value):
    digest = hashlib.sha256()
    for name, (kind, content, mode) in sorted(value.items()):
        digest.update(name.encode() + b"\0" + kind.encode() + b"\0" + str(mode).encode() + b"\0" + content + b"\0")
    return digest.hexdigest()


def safe_relative(value):
    if not isinstance(value, str) or not value or any(char in value for char in "\\:\0\r\n\t"):
        return False
    path = pathlib.PurePosixPath(value)
    return not path.is_absolute() and path.as_posix() == value and not any(
        part in {"", ".", ".."} for part in path.parts
    )


def protected_file(value):
    name = pathlib.PurePosixPath(value).name.casefold()
    return (
        name in {"agents.md", "gemini.md", "package.json", "package-lock.json", "go.mod", "go.sum", "cargo.toml", "cargo.lock", "pyproject.toml"}
        or name.startswith("test_") or name.endswith(("_test.go", "_test.py", ".test.mjs", ".test.js", ".spec.js", ".spec.mjs"))
    )


def selected_cases(case_ids, manifest_path=None):
    if not case_ids or len(case_ids) > MAX_CASES or len(set(case_ids)) != len(case_ids):
        raise quota.BenchmarkError("select 1 to 5 distinct implementation case IDs")
    path = CASES_PATH if manifest_path is None else manifest_path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(manifest, list) or any(not isinstance(case, dict) for case in manifest):
        raise quota.BenchmarkError("eval manifest must be a case list")
    ids = [case.get("id") for case in manifest]
    if any(not isinstance(value, str) for value in ids) or len(ids) != len(set(ids)):
        raise quota.BenchmarkError("eval manifest case IDs must be unique strings")
    by_id = {case["id"]: case for case in manifest}
    selected = []
    for case_id in case_ids:
        case = by_id.get(case_id)
        if case is None:
            raise quota.BenchmarkError("unknown implementation case ID")
        required = case.get("required_changed_paths", [])
        allowed = case.get("allowed_changed_paths", [])
        criteria = case.get("acceptance_criteria", [])
        if (case.get("route") not in {"IMPLEMENT", "COMPLEX_IMPLEMENT"}
                or case.get("expect_change") is not True
                or not required or not allowed or not criteria):
            raise quota.BenchmarkError("implementation cases need source allowlists and independent ACs")
        if not case.get("require_result"):
            raise quota.BenchmarkError("implementation case must require a structured completion report")
        if not isinstance(case.get("prompt"), str) or not case["prompt"].strip():
            raise quota.BenchmarkError("implementation case has no prompt")
        fixture = quota.safe_fixture_path(case.get("fixture"))
        expected = snapshot(fixture)
        if (not isinstance(allowed, list) or len(allowed) != len(set(allowed))
                or not all(safe_relative(item) and not protected_file(item) and
                           expected.get(item, (None,))[0] == "file" for item in allowed)
                or not set(required).issubset(allowed)):
            raise quota.BenchmarkError("implementation source allowlist is unsafe or includes protected files")
        checks = []
        criterion_ids = []
        for criterion in criteria:
            if not isinstance(criterion, dict) or not isinstance(criterion.get("id"), str):
                raise quota.BenchmarkError("implementation AC IDs must be strings")
            criterion_ids.append(criterion["id"])
            command = criterion.get("verify")
            if not valid_command(command):
                raise quota.BenchmarkError("each implementation AC needs an independent verification command")
            if not valid_minimum(criterion.get("minimum_tests", 1)):
                raise quota.BenchmarkError("AC minimum_tests must be a positive integer")
            checks.append(tuple(command))
        if len(set(criterion_ids)) != len(criteria) or len(set(checks)) != len(criteria):
            raise quota.BenchmarkError("implementation AC IDs and verification commands must be distinct")
        if not valid_minimum(case.get("minimum_tests", 1)):
            raise quota.BenchmarkError("case minimum_tests must be a positive integer")
        if not valid_command(case.get("verify")):
            raise quota.BenchmarkError("implementation case needs a full verification command")
        selected.append(case)
    return selected


def valid_minimum(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def valid_command(command):
    return isinstance(command, list) and bool(command) and all(isinstance(arg, str) and arg for arg in command)


def git_command(workspace, arguments):
    return subprocess.run(
        ["git", *arguments], cwd=str(workspace), stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL, text=True, timeout=15, check=True,
        env={**os.environ, "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull},
    ).stdout.strip()


def initialize_repository(workspace, empty_hooks):
    git_command(workspace, ["init", "-q", "--template="])
    git_command(workspace, ["add", "--all"])
    git_command(workspace, ["-c", "core.hooksPath=" + str(empty_hooks), "-c", "commit.gpgsign=false",
                            "-c", "user.name=Harness Eval", "-c", "user.email=harness-eval@example.invalid",
                            "commit", "-qm", "baseline"])
    return git_command(workspace, ["rev-parse", "HEAD"])


def run_sample(case, model, output_format, timeout, expected_cli_version=None):
    try:
        from .oracles import verify_command
        from .smoke_results import grade_report, prepare_user_changes, user_changes_preserved
    except ImportError:
        from oracles import verify_command
        from smoke_results import grade_report, prepare_user_changes, user_changes_preserved

    started = time.monotonic()
    sample = {
        "status": "ERROR", "failure_kind": None, "initial_prompt_complete": False,
        "runner_continuations": 0, "usage": None, "cli_duration_seconds": None,
        "changed_paths": [], "source_scope_valid": False,
        "preexisting_changes_preserved": False, "repository_history_preserved": False,
        "suite": None, "comparison_valid": False, "profile_error": "model_call_not_started",
        "version_before": None, "version_after": None, "model_call_started": False,
        "acceptance": [{"id": item["id"], "status": "unverified", "reason": "CLI did not finish"}
                       for item in case["acceptance_criteria"]],
    }
    response = ""
    terminal_success = False
    response_valid = False
    try:
        fixture = quota.safe_fixture_path(case["fixture"])
        fixture_before = snapshot(fixture)
        sample["fixture_digest"] = snapshot_digest(fixture_before)
        with tempfile.TemporaryDirectory(prefix="harness-implementation-benchmark-") as directory:
            parent = pathlib.Path(directory)
            workspace = parent / "workspace"
            shutil.copytree(fixture, workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
            if snapshot(workspace) != fixture_before:
                raise quota.BenchmarkError("fixture copy differs from source")
            empty_hooks = parent / "empty-hooks"
            empty_hooks.mkdir()
            head = initialize_repository(workspace, empty_hooks)
            prepare_user_changes(workspace, case)
            before = snapshot(workspace)
            command = ["agy", "--print", case["prompt"], "--model", model, "--new-project",
                       "--add-dir", str(workspace), "--sandbox", "--mode=accept-edits",
                       "--output-format", output_format, "--print-timeout", str(timeout) + "s"]
            completed = None
            sample["version_before"] = observed_cli_version()
            expected_version = expected_cli_version or sample["version_before"]
            if sample["version_before"] is None:
                sample["profile_error"] = "cli_version_before_unavailable"
                sample["failure_kind"] = "profile_preflight"
            elif sample["version_before"] != expected_version:
                sample["profile_error"] = "cli_version_before_changed"
                sample["failure_kind"] = "profile_preflight"
            else:
                sample["model_call_started"] = True
                try:
                    completed = subprocess.run(
                        command, cwd=str(workspace), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, timeout=timeout, check=False,
                        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
                    )
                except subprocess.TimeoutExpired:
                    sample["failure_kind"] = "timeout"
                except OSError:
                    sample["failure_kind"] = "cli_launch"
                    sample["model_call_started"] = False
                finally:
                    sample["version_after"] = observed_cli_version()
                    if sample["version_after"] is None:
                        sample["profile_error"] = "cli_version_after_unavailable"
                    elif sample["version_after"] != expected_version:
                        sample["profile_error"] = "cli_version_after_changed"
                    elif not sample["model_call_started"]:
                        sample["profile_error"] = "model_call_not_started"
                    else:
                        sample["profile_error"] = None
                        sample["comparison_valid"] = True
            if completed is not None:
                if completed.returncode != 0:
                    sample["failure_kind"] = "cli_exit"
                try:
                    result = quota.terminal_result(completed.stdout, output_format)
                    response = result.get("response", "")
                    if not isinstance(response, str):
                        response = ""
                    terminal_success = completed.returncode == 0 and result.get("status") == "SUCCESS"
                    if not terminal_success and sample["failure_kind"] is None:
                        sample["failure_kind"] = "terminal_status"
                    try:
                        sample["usage"] = quota.normalized_usage(result)
                    except quota.BenchmarkError:
                        pass
                    duration = result.get("duration_seconds")
                    if (isinstance(duration, (int, float)) and not isinstance(duration, bool)
                            and math.isfinite(duration) and duration >= 0):
                        sample["cli_duration_seconds"] = float(duration)
                    try:
                        quota.require_response_contract(result, case)
                        response_valid = True
                    except quota.BenchmarkError:
                        if sample["failure_kind"] is None:
                            sample["failure_kind"] = "response_contract"
                except quota.BenchmarkError:
                    sample["failure_kind"] = "terminal_envelope"
            after = snapshot(workspace)
            changed = sorted(name for name in set(before) | set(after) if before.get(name) != after.get(name))
            sample["changed_paths"] = changed
            sample["source_scope_valid"] = (bool(changed) and set(case["required_changed_paths"]).issubset(changed)
                                              and set(changed).issubset(case["allowed_changed_paths"]))
            sample["preexisting_changes_preserved"] = (
                user_changes_preserved(workspace, case) and all(
                    before.get(path) == after.get(path) for path in case.get("preexisting_changes", {})
                )
            )
            sample["repository_history_preserved"] = (
                (workspace / ".git").is_dir() and not (workspace / ".git").is_symlink()
                and git_command(workspace, ["rev-parse", "HEAD"]) == head
            )
            integrity_valid = (set(changed).issubset(case["allowed_changed_paths"])
                               and sample["preexisting_changes_preserved"] and sample["repository_history_preserved"])
            if integrity_valid:
                # Rebuild trusted tests/config to avoid cache poisoning or mutable git metadata.
                oracle_workspace = parent / "oracle"
                shutil.copytree(fixture, oracle_workspace, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"))
                prepare_user_changes(oracle_workspace, case)
                for relative in case["allowed_changed_paths"]:
                    if after.get(relative, (None,))[0] == "file":
                        (oracle_workspace / relative).write_bytes(after[relative][1])
                        (oracle_workspace / relative).chmod(after[relative][2])
                    elif relative in before and relative not in after:
                        (oracle_workspace / relative).unlink()
                sample["suite"] = verify_command(oracle_workspace, case["verify"], case.get("minimum_tests", 1))
                sample["acceptance"] = [
                    {"id": criterion["id"], **verify_command(oracle_workspace, criterion["verify"], criterion.get("minimum_tests", 1))}
                    for criterion in case["acceptance_criteria"]
                ]
            else:
                sample["failure_kind"] = sample["failure_kind"] or "protected_scope"
                sample["acceptance"] = [{"id": item["id"], "status": "unverified", "reason": "fixture integrity check failed"}
                                        for item in case["acceptance_criteria"]]
    except subprocess.TimeoutExpired:
        sample["failure_kind"] = "timeout"
    except (OSError, subprocess.CalledProcessError, quota.BenchmarkError, ValueError):
        sample["failure_kind"] = "infrastructure_or_fixture"
    sample.update(grade_report(case, response, sample["acceptance"]))
    sample["all_required_ac_verified"] = all(item["status"] == "passed" for item in sample["acceptance"])
    sample["ac_pass_count"] = sum(item["status"] == "passed" for item in sample["acceptance"])
    sample["task_fulfillment"] = bool(
        sample["source_scope_valid"] and sample["preexisting_changes_preserved"]
        and sample["repository_history_preserved"] and sample["suite"]
        and sample["suite"]["status"] == "passed" and sample["all_required_ac_verified"]
    )
    if sample["report_status"] == "complete" and not sample["task_fulfillment"]:
        sample["false_complete"] = True
        sample["report_truthfulness"] = False
    sample["initial_prompt_complete"] = bool(
        terminal_success and response_valid and sample["task_fulfillment"] and sample["report_valid"] is True
        and sample["requirement_coverage"] is True and sample["report_truthfulness"] is True
        and sample["report_status"] == "complete" and not sample["false_complete"]
    )
    if sample["initial_prompt_complete"]:
        sample["status"] = "SUCCESS"
        sample["failure_kind"] = None
    elif sample["failure_kind"] is None:
        sample["failure_kind"] = "incomplete_oracle_or_report"
    sample["duration_seconds"] = round(time.monotonic() - started, 6)
    return sample


def duration_summary(samples):
    values = [sample["duration_seconds"] for sample in samples]
    return {"count": len(values), "median_seconds": statistics.median(values) if values else None,
            "minimum_seconds": min(values) if values else None, "maximum_seconds": max(values) if values else None}


def summarize(samples):
    successes = [sample for sample in samples if sample["initial_prompt_complete"]]
    usage = [sample["usage"] for sample in samples if sample["usage"] is not None]
    return {
        "requested_samples": len(samples), "complete_samples": len(successes),
        "quota_calls_started": sum(sample["model_call_started"] for sample in samples),
        "profile_valid_samples": sum(sample["comparison_valid"] for sample in samples),
        "profile_invalid_samples": sum(not sample["comparison_valid"] for sample in samples),
        "profile_valid_complete_samples": sum(sample["comparison_valid"] and sample["initial_prompt_complete"] for sample in samples),
        "comparison_valid": all(sample["comparison_valid"] for sample in samples),
        "failed_samples": len(samples) - len(successes),
        "initial_prompt_completion_rate": len(successes) / len(samples) if samples else None,
        "false_complete_samples": sum(sample["false_complete"] is True for sample in samples),
        "honest_partial_samples": sum(sample["honest_partial"] is True for sample in samples),
        "truthfulness_observed_samples": sum(sample["report_truthfulness"] is not None for sample in samples),
        "ac_pass_counts": {criterion["id"]: sum(next(item["status"] for item in sample["acceptance"] if item["id"] == criterion["id"]) == "passed" for sample in samples)
                           for criterion in samples[0]["acceptance"]} if samples else {},
        "duration_all": duration_summary(samples), "duration_success": duration_summary(successes),
        "usage_observed_samples": len(usage),
        "usage_totals_observed": {field: sum(item[field] for item in usage) for field in quota.USAGE_FIELDS} if usage else None,
    }


def runner_digest():
    files = ("implementation_benchmark.py", "quota_benchmark.py", "oracles.py", "smoke_results.py")
    return snapshot_digest({name: ("file", (ROOT / "evals" / name).read_bytes(), stat.S_IMODE((ROOT / "evals" / name).stat().st_mode)) for name in files})




def _policy_bytes(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > quota.MAX_SNAPSHOT_FILE_BYTES:
        raise quota.BenchmarkError("global harness policy is unavailable or unsafe")
    return path.read_bytes().replace(b"\r\n", b"\n")


def matching_global_policy_digest(source):
    """Hash only the installer-owned block, never unrelated user policy bytes."""
    source_path = source / "global" / "GEMINI.md"
    if source_path.parent.is_symlink():
        raise quota.BenchmarkError("global harness policy source is unsafe")
    expected_content = _policy_bytes(source_path).rstrip(b"\n")
    expected = POLICY_START + b"\n" + expected_content + b"\n" + POLICY_END
    installed = _policy_bytes(pathlib.Path.home() / ".gemini" / "GEMINI.md")
    if installed.count(POLICY_START) != 1 or installed.count(POLICY_END) != 1:
        raise quota.BenchmarkError("global harness policy managed block is missing or ambiguous")
    lines = installed.split(b"\n")
    try:
        begin = lines.index(POLICY_START)
        end = lines.index(POLICY_END)
    except ValueError as error:
        raise quota.BenchmarkError("global harness policy markers must be standalone lines") from error
    if end <= begin:
        raise quota.BenchmarkError("global harness policy managed block is malformed")
    observed = b"\n".join(lines[begin:end + 1])
    if observed != expected:
        raise quota.BenchmarkError("installed global harness policy differs from the selected source")
    return hashlib.sha256(expected).hexdigest()


def matching_harness_digest(source):
    """Match installed behavior to the chosen harness without changing evaluator files."""
    if not source.is_absolute() or source.is_symlink() or not source.is_dir():
        raise quota.BenchmarkError("harness source must be an existing absolute repository directory")
    source = source.resolve(strict=True)
    matching_global_policy_digest(source)
    if source == ROOT.resolve(strict=True):
        return quota.matching_installed_digest()
    expected = quota.behavior_digest(source / "plugin" / "codex-claude-harness")
    home = pathlib.Path.home()
    candidates = (
        home / ".gemini" / "config" / "plugins" / "codex-claude-harness",
        home / ".gemini" / "antigravity-cli" / "plugins" / "codex-claude-harness",
    )
    installed = [path for path in candidates if path.exists() or path.is_symlink()]
    if not installed or any(quota.behavior_digest(path) != expected for path in installed):
        raise quota.BenchmarkError("installed behavior differs from the selected harness source")
    return expected


def cli_version():
    completed = subprocess.run(["agy", "--version"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               text=True, timeout=15, check=False)
    if completed.returncode != 0:
        raise quota.BenchmarkError("agy version is unavailable")
    match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?\b", completed.stdout)
    if not match:
        raise quota.BenchmarkError("agy version is not recognized")
    return match.group(0)


def observed_cli_version():
    """Version probes are metadata only; private diagnostics remain discarded."""
    try:
        return cli_version()
    except (quota.BenchmarkError, OSError, subprocess.SubprocessError):
        return None


def parser():
    result = argparse.ArgumentParser(description="Opt-in repeated implementation pilot with independent AC grading")
    result.add_argument("--case", action="append", dest="cases", required=True)
    result.add_argument("--repeat", type=int, default=3)
    result.add_argument("--model", default="gemini-3.8-flash-high")
    result.add_argument("--output-format", choices=("json", "stream-json"), default="json")
    result.add_argument("--timeout-seconds", type=int, default=960)
    result.add_argument("--label", default="candidate")
    result.add_argument("--harness-source", type=pathlib.Path, default=ROOT, help="absolute repository whose harness must match the installed plugin")
    result.add_argument("--permission-profile", required=True, help="user-declared stable comparison label")
    result.add_argument("--mcp-profile", required=True, help="user-declared stable comparison label")
    result.add_argument("--confirm-quota-use", action="store_true")
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if not args.confirm_quota_use:
        quota.emit({"event": "implementation_benchmark_refused", "reason": "pass --confirm-quota-use to authorize model quota consumption"})
        return 2
    try:
        if not 3 <= args.repeat <= MAX_REPEAT:
            raise quota.BenchmarkError("--repeat must be between 3 and 10")
        if not 1 <= args.timeout_seconds <= 1800:
            raise quota.BenchmarkError("--timeout-seconds must be between 1 and 1800")
        if not all(LABEL.fullmatch(value) for value in (args.label, args.permission_profile, args.mcp_profile)):
            raise quota.BenchmarkError("comparison labels must be 1 to 64 simple identifier characters")
        if not LABEL.fullmatch(args.model):
            raise quota.BenchmarkError("model must be an explicit simple identifier")
        cases = selected_cases(args.cases)
        if shutil.which("agy") is None or shutil.which("git") is None:
            raise quota.BenchmarkError("agy and git must already be installed")
        if any(shutil.which(command) is None for case in cases for command in case.get("requires", [])):
            raise quota.BenchmarkError("a selected case runtime is unavailable; no samples started")
        behavior = matching_harness_digest(args.harness_source)
        global_policy = matching_global_policy_digest(args.harness_source)
        metadata = {
            "benchmark_protocol": 3, "label": args.label,
            "manifest_digest": hashlib.sha256(CASES_PATH.read_bytes()).hexdigest(),
            "runner_digest": runner_digest(), "source_behavior_digest": behavior,
            "installed_behavior_digest": behavior,
            "source_global_policy_digest": global_policy, "installed_global_policy_digest": global_policy,
            "source_revision": git_command(args.harness_source, ["rev-parse", "HEAD"]),
            "source_worktree_dirty": bool(git_command(args.harness_source, ["status", "--porcelain=v1"])),
            "evaluator_revision": git_command(ROOT, ["rev-parse", "HEAD"]),
            "model": args.model, "cli_version": cli_version(),
            "platform": {"system": platform.system(), "release": platform.release(), "machine": platform.machine()},
            "timeout_seconds": args.timeout_seconds, "repeat": args.repeat, "output_format": args.output_format,
            "declared_permission_profile": args.permission_profile, "declared_mcp_profile": args.mcp_profile,
            "observed_permission_grants": None, "observed_mcp_connections": None,
            "runner_continuation_cap": 0,
        }
    except (quota.BenchmarkError, OSError, ValueError, subprocess.SubprocessError):
        quota.emit({"event": "implementation_benchmark_refused", "reason": "invalid benchmark configuration, unavailable runtime, or stale installed harness"})
        return 2
    quota.emit({"event": "implementation_benchmark_start", **metadata, "requested_samples": len(cases) * args.repeat})
    failed = 0
    profile_invalid = 0
    quota_calls_started = 0
    for case in cases:
        samples = []
        comparison = {key: value for key, value in metadata.items() if key not in {"label", "source_revision", "source_worktree_dirty", "source_behavior_digest", "installed_behavior_digest", "source_global_policy_digest", "installed_global_policy_digest"}}
        comparison.update({"case_id": case["id"], "case_digest": digest_json(case),
                           "fixture_digest": snapshot_digest(snapshot(quota.safe_fixture_path(case["fixture"])))})
        comparison_key = digest_json(comparison)
        for repeat in range(1, args.repeat + 1):
            sample = run_sample(case, args.model, args.output_format, args.timeout_seconds,
                                expected_cli_version=metadata["cli_version"])
            samples.append(sample)
            failed += not sample["initial_prompt_complete"]
            profile_invalid += not sample["comparison_valid"]
            quota_calls_started += sample["model_call_started"]
            quota.emit({"event": "implementation_benchmark_sample", **metadata,
                        "case_id": case["id"], "case_digest": digest_json(case),
                        "comparison_key": comparison_key if sample["comparison_valid"] else None,
                        "repeat_index": repeat, **sample})
        quota.emit({"event": "implementation_benchmark_summary", **metadata, "case_id": case["id"],
                    "comparison_key": comparison_key if all(sample["comparison_valid"] for sample in samples) else None,
                    **summarize(samples)})
    quota.emit({"event": "implementation_benchmark_complete", "requested_samples": len(cases) * args.repeat,
                "quota_calls_started": quota_calls_started, "failed_samples": failed,
                "profile_invalid_samples": profile_invalid, "comparison_valid": profile_invalid == 0})
    return 1 if failed or profile_invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
