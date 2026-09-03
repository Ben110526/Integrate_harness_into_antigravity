#!/usr/bin/env python3
"""Opt-in Antigravity route benchmark with machine-readable token usage."""

from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import shutil
import statistics
import subprocess
import sys
import tempfile
from collections.abc import Iterable
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
FIXTURES = ROOT / "evals" / "fixtures"
SOURCE_PLUGIN = ROOT / "plugin" / "codex-claude-harness"
BEHAVIOR_PATTERNS = ("rules/*.md", "agents/*.md", "skills/*/SKILL.md")
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "thinking_tokens",
    "cache_read_tokens",
    "total_tokens",
)
MAX_SNAPSHOT_ENTRIES = 256
MAX_SNAPSHOT_FILE_BYTES = 2 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024


class BenchmarkError(RuntimeError):
    """Raised when a benchmark result violates the documented CLI contract."""


def terminal_result(raw: str, output_format: str) -> dict[str, Any]:
    """Return the terminal result from an official json or stream-json envelope."""
    try:
        if output_format == "json":
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise BenchmarkError("agy JSON output is not an object")
            return payload

        results = []
        for line in raw.splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if isinstance(event, dict) and event.get("event") == "result":
                result = event.get("result")
                if isinstance(result, dict):
                    results.append(result)
        if len(results) != 1:
            raise BenchmarkError(
                f"expected exactly one terminal result event, got {len(results)}"
            )
        return results[0]
    except json.JSONDecodeError as error:
        raise BenchmarkError("agy output is not valid JSON") from error


def normalized_usage(result: dict[str, Any]) -> dict[str, int]:
    """Validate and copy only the documented, non-sensitive token counters."""
    usage = result.get("usage")
    if not isinstance(usage, dict):
        raise BenchmarkError("terminal result has no usage object")

    normalized: dict[str, int] = {}
    for field in USAGE_FIELDS:
        value = usage.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise BenchmarkError(f"usage.{field} must be a non-negative integer")
        normalized[field] = value
    return normalized


def require_response_contract(result: dict[str, Any], case: dict[str, Any]) -> None:
    """Validate route and deterministic response assertions before counting usage."""
    response = result.get("response")
    if not isinstance(response, str):
        raise BenchmarkError("terminal result has no text response")
    reported_routes = {
        line.strip().partition(":")[2].split(";", 1)[0].strip()
        for line in response.splitlines()
        if line.strip().startswith("Harness:")
    }
    if case["route"] not in reported_routes:
        raise BenchmarkError(f"response did not report route {case['route']}")

    missing = [term for term in case.get("response_contains", []) if term not in response]
    if missing:
        raise BenchmarkError("response omitted required evidence")
    folded_response = response.casefold()
    if any(
        term.casefold() in folded_response
        for term in case.get("response_not_contains", [])
    ):
        raise BenchmarkError("response contained forbidden evidence")
    only_lines = case.get("response_only_lines", [])
    if only_lines:
        nonblank = [line.strip() for line in response.splitlines() if line.strip()]
        if nonblank != only_lines:
            raise BenchmarkError("response did not match the exact-line contract")
    expected_line_count = case.get("response_line_count")
    if expected_line_count is not None:
        nonblank_count = len([line for line in response.splitlines() if line.strip()])
        if nonblank_count != expected_line_count:
            raise BenchmarkError("response did not match the line-count contract")


def emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, sort_keys=True, separators=(",", ":")), flush=True)


def safe_fixture_path(value: Any) -> pathlib.Path:
    """Resolve one manifest fixture without allowing traversal or symlink escape."""
    if not isinstance(value, str) or not value or "\\" in value:
        raise BenchmarkError("benchmark fixture must be a relative POSIX path")
    relative = pathlib.PurePosixPath(value)
    if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        raise BenchmarkError("benchmark fixture path is unsafe")

    candidate = FIXTURES
    for part in relative.parts:
        candidate = candidate / part
        if candidate.is_symlink():
            raise BenchmarkError("benchmark fixture path must not contain symlinks")
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as error:
        raise BenchmarkError("benchmark fixture does not exist") from error
    fixtures_root = FIXTURES.resolve(strict=True)
    if fixtures_root not in resolved.parents or not resolved.is_dir():
        raise BenchmarkError("benchmark fixture must resolve inside evals/fixtures")
    return resolved


def behavior_digest(plugin_root: pathlib.Path) -> str:
    """Hash bounded policy, agent, and skill inputs without reading other config."""
    if plugin_root.is_symlink() or not plugin_root.is_dir():
        raise BenchmarkError("harness behavior directory is unavailable or unsafe")
    root = plugin_root.resolve(strict=True)
    paths = sorted({path for pattern in BEHAVIOR_PATTERNS for path in root.glob(pattern)})
    if not paths:
        raise BenchmarkError("harness behavior files are unavailable")
    if len(paths) > MAX_SNAPSHOT_ENTRIES:
        raise BenchmarkError("harness behavior file count exceeds the limit")

    digest = hashlib.sha256()
    total_bytes = 0
    for path in paths:
        relative = path.relative_to(root)
        cursor = root
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                raise BenchmarkError("harness behavior files must not use symlinks")
        resolved = path.resolve(strict=True)
        if root not in resolved.parents or not resolved.is_file():
            raise BenchmarkError("harness behavior file escaped its directory")
        size = resolved.stat().st_size
        if size > MAX_SNAPSHOT_FILE_BYTES:
            raise BenchmarkError("harness behavior contains an oversized file")
        total_bytes += size
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise BenchmarkError("harness behavior exceeds the total-size limit")
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(resolved.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def matching_installed_digest(home: pathlib.Path | None = None) -> str:
    """Refuse measurements when any installed harness copy is stale."""
    expected = behavior_digest(SOURCE_PLUGIN)
    base = pathlib.Path.home() if home is None else home
    candidates = (
        base / ".gemini" / "config" / "plugins" / "codex-claude-harness",
        base / ".gemini" / "antigravity-cli" / "plugins" / "codex-claude-harness",
    )
    installed = [path for path in candidates if path.exists() or path.is_symlink()]
    if not installed:
        raise BenchmarkError("the harness is not installed; run the installer first")
    if any(behavior_digest(path) != expected for path in installed):
        raise BenchmarkError(
            "installed harness behavior differs from this source; rerun the installer"
        )
    return expected


def selected_cases(case_ids: list[str]) -> list[dict[str, Any]]:
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkError("duplicate --case values would consume redundant quota")
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    by_id = {case["id"]: case for case in cases}
    selected = []
    for case_id in case_ids:
        case = by_id.get(case_id)
        if case is None:
            raise BenchmarkError(f"unknown eval case: {case_id}")
        if not case.get("benchmark"):
            raise BenchmarkError(f"case is not benchmark-enabled: {case_id}")
        if case.get("expect_change") or case.get("allowed_changed_paths"):
            raise BenchmarkError(f"benchmark case must be read-only: {case_id}")
        safe_fixture_path(case.get("fixture"))
        selected.append(case)
    return selected


def workspace_snapshot(workspace: pathlib.Path) -> dict[str, tuple[str, bytes]]:
    """Capture the controlled fixture so a nominally read-only sample is enforced."""
    snapshot: dict[str, tuple[str, bytes]] = {}
    total_bytes = 0
    for path in workspace.rglob("*"):
        if path.is_symlink():
            raise BenchmarkError("benchmark fixtures must not contain symlinks")
        if len(snapshot) >= MAX_SNAPSHOT_ENTRIES:
            raise BenchmarkError("benchmark fixture exceeds the entry-count limit")
        relative = path.relative_to(workspace).as_posix()
        if path.is_dir():
            snapshot[relative] = ("directory", b"")
            continue
        if not path.is_file():
            raise BenchmarkError("benchmark fixture contains an unsupported entry")
        size = path.stat().st_size
        if size > MAX_SNAPSHOT_FILE_BYTES:
            raise BenchmarkError("benchmark fixture contains an oversized file")
        total_bytes += size
        if total_bytes > MAX_SNAPSHOT_BYTES:
            raise BenchmarkError("benchmark fixture exceeds the total-size limit")
        snapshot[relative] = ("file", path.read_bytes())
    return snapshot


def run_sample(
    case: dict[str, Any],
    model: str,
    output_format: str,
    timeout: int,
) -> dict[str, Any]:
    fixture = safe_fixture_path(case.get("fixture"))
    expected = workspace_snapshot(fixture)
    with tempfile.TemporaryDirectory(prefix="harness-quota-benchmark-") as temp_dir:
        workspace = pathlib.Path(temp_dir) / "workspace"
        shutil.copytree(fixture, workspace)
        before = workspace_snapshot(workspace)
        if before != expected:
            raise BenchmarkError("temporary fixture copy does not match its source")
        command = [
            "agy",
            "--print",
            case["prompt"],
            "--model",
            model,
            "--new-project",
            "--add-dir",
            str(workspace),
            "--sandbox",
            "--mode=plan",
            "--output-format",
            output_format,
            "--print-timeout",
            "15m",
        ]
        completed = subprocess.run(
            command,
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
        after = workspace_snapshot(workspace)

    if completed.returncode != 0:
        raise BenchmarkError(f"agy exited non-zero ({completed.returncode})")
    if after != before:
        raise BenchmarkError("read-only benchmark sample modified its fixture copy")
    result = terminal_result(completed.stdout, output_format)
    if result.get("status") != "SUCCESS":
        raise BenchmarkError(f"agy returned status {result.get('status', 'UNKNOWN')}")
    require_response_contract(result, case)

    duration = result.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, (int, float)):
        raise BenchmarkError("terminal result has no numeric duration_seconds")
    return {
        "duration_seconds": float(duration),
        "usage": normalized_usage(result),
    }


def summarize(samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
    samples = list(samples)
    summary: dict[str, Any] = {
        "samples": len(samples),
        "mean_duration_seconds": round(statistics.fmean(
            sample["duration_seconds"] for sample in samples
        ), 3),
    }
    summary["mean_usage"] = {
        field: round(statistics.fmean(sample["usage"][field] for sample in samples), 3)
        for field in USAGE_FIELDS
    }
    summary["median_usage"] = {
        field: statistics.median(sample["usage"][field] for sample in samples)
        for field in USAGE_FIELDS
    }
    return summary


def parser() -> argparse.ArgumentParser:
    argument_parser = argparse.ArgumentParser(
        description=(
            "Run repeated, read-only Antigravity eval prompts and report token usage. "
            "This consumes quota only with --confirm-quota-use."
        )
    )
    argument_parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        required=True,
        help="benchmark-enabled eval case ID; repeat to compare routes",
    )
    argument_parser.add_argument("--repeat", type=int, default=3)
    argument_parser.add_argument(
        "--model",
        default="gemini-3.8-flash-high",
    )
    argument_parser.add_argument(
        "--output-format",
        choices=("json", "stream-json"),
        default="json",
    )
    argument_parser.add_argument("--timeout-seconds", type=int, default=960)
    argument_parser.add_argument(
        "--confirm-quota-use",
        action="store_true",
        help="explicitly authorize the selected repeated model calls",
    )
    return argument_parser


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if not args.confirm_quota_use:
        emit({
            "event": "benchmark_refused",
            "reason": "pass --confirm-quota-use to authorize model quota consumption",
        })
        return 2
    if args.repeat < 2:
        emit({"event": "benchmark_refused", "reason": "--repeat must be at least 2"})
        return 2
    if args.timeout_seconds < 1:
        emit({
            "event": "benchmark_refused",
            "reason": "--timeout-seconds must be positive",
        })
        return 2
    try:
        cases = selected_cases(args.cases)
        harness_digest = matching_installed_digest()
    except BenchmarkError as error:
        emit({"event": "benchmark_refused", "reason": str(error)})
        return 2
    if shutil.which("agy") is None:
        emit({"event": "benchmark_refused", "reason": "agy is not installed"})
        return 2

    failures = 0
    for case in cases:
        samples = []
        for repeat_index in range(1, args.repeat + 1):
            try:
                sample = run_sample(
                    case,
                    args.model,
                    args.output_format,
                    args.timeout_seconds,
                )
            except (BenchmarkError, subprocess.TimeoutExpired) as error:
                failures += 1
                emit({
                    "case_id": case["id"],
                    "event": "benchmark_sample",
                    "repeat": repeat_index,
                    "route": case["route"],
                    "status": "ERROR",
                    "error_type": type(error).__name__,
                })
                continue

            samples.append(sample)
            emit({
                "case_id": case["id"],
                "event": "benchmark_sample",
                "harness_digest": harness_digest,
                "model": args.model,
                "repeat": repeat_index,
                "route": case["route"],
                "status": "SUCCESS",
                **sample,
            })

        if samples:
            emit({
                "case_id": case["id"],
                "event": "benchmark_summary",
                "harness_digest": harness_digest,
                "model": args.model,
                "route": case["route"],
                **summarize(samples),
            })

    emit({
        "event": "benchmark_complete",
        "failed_samples": failures,
        "requested_samples": len(cases) * args.repeat,
    })
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
