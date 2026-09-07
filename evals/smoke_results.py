#!/usr/bin/env python3
"""Record independent AC outcomes; runner-assisted completion is not autonomous."""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import time

try:
    from .quota_benchmark import SOURCE_PLUGIN, behavior_digest, matching_installed_digest
except ImportError:
    from quota_benchmark import SOURCE_PLUGIN, behavior_digest, matching_installed_digest


def protected_path(workspace: pathlib.Path, relative: str) -> pathlib.Path:
    parts = pathlib.PurePosixPath(relative)
    if not relative or "\\" in relative or parts.is_absolute() or ".." in parts.parts:
        raise ValueError("unsafe preexisting-change path")
    path = workspace
    for part in parts.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("preexisting-change path contains a symlink")
    if not path.is_file():
        raise ValueError("preexisting-change target is not an existing regular file")
    return path


def prepare_user_changes(workspace: pathlib.Path, case: dict) -> None:
    # Called only after the isolated fixture baseline commit, never on source.
    for relative, content in case.get("preexisting_changes", {}).items():
        protected_path(workspace, relative).write_text(content, encoding="utf-8")


def user_changes_preserved(workspace: pathlib.Path, case: dict) -> bool:
    try:
        return all(
            protected_path(workspace, path).read_bytes() == content.encode("utf-8")
            for path, content in case.get("preexisting_changes", {}).items()
        )
    except (OSError, ValueError):
        return False


def acceptance_results(workspace: pathlib.Path, case: dict) -> list[dict]:
    results = []
    for criterion in case.get("acceptance_criteria", []):
        try:
            run = subprocess.run(
                criterion["verify"], cwd=workspace, capture_output=True,
                text=True, timeout=60, check=False,
                env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
            )
            status = "passed" if run.returncode == 0 else "failed"
            result = {"id": criterion["id"], "status": status, "exit_code": run.returncode}
        except (OSError, subprocess.TimeoutExpired):
            result = {"id": criterion["id"], "status": "error", "exit_code": None}
        # Do not short-circuit: a failed AC must not hide later AC outcomes.
        results.append(result)
    return results


def sample_result(case: dict, model: str, continuations: int, errors: int,
                  criteria: list[dict], preserved: bool, duration: float) -> dict:
    expected = [item["id"] for item in case.get("acceptance_criteria", [])]
    observed = [item["id"] for item in criteria]
    complete_ac = observed == expected and all(item["status"] == "passed" for item in criteria)
    passed = errors == 0 and complete_ac and preserved
    return {
        "event": "smoke_sample", "case": case["id"], "model": model,
        "outcome_pass": passed, "runner_continuations": continuations,
        "unassisted_completion": passed and continuations == 0,
        "required_ac_count": len(expected), "acceptance": criteria,
        "ac_pass_count": sum(item["status"] == "passed" for item in criteria),
        "all_required_ac_verified": complete_ac,
        "preexisting_changes_preserved": preserved,
        "infrastructure_or_contract_failures": errors,
        "duration_seconds": round(duration, 3),
        # Not available from a stable CLI trace. Never treat missing telemetry as zero.
        "user_nudges": None, "permission_prompts": None,
        "decision_questions": None, "native_resume_correct": None,
        "no_progress_repair_rounds": None, "usage": None,
    }


def main() -> int:
    mode, cases_path, index, workspace = sys.argv[1:5]
    case = json.loads(pathlib.Path(cases_path).read_text(encoding="utf-8"))[int(index)]
    root = pathlib.Path(workspace)
    if mode == "prepare":
        if case.get("workflow_pilot"):
            matching_installed_digest()
        prepare_user_changes(root, case)
        return 0
    model, continuations, errors, started, metrics_path = sys.argv[5:10]
    criteria = acceptance_results(root, case)
    result = sample_result(
        case, model, int(continuations), int(errors), criteria,
        user_changes_preserved(root, case), time.time() - float(started),
    )
    result["source_behavior_digest"] = behavior_digest(SOURCE_PLUGIN)
    encoded = json.dumps(result, sort_keys=True)
    print(f"[metrics] {encoded}")
    if metrics_path:
        with pathlib.Path(metrics_path).open("a", encoding="utf-8") as handle:
            handle.write(encoded + "\n")
    return 0 if result["outcome_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
