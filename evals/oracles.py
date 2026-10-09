#!/usr/bin/env python3
"""Run independent checks without turning successful empty commands into evidence."""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile


ADAPTER = pathlib.Path(__file__).resolve().parents[1] / "plugin" / "codex-claude-harness" / "scripts" / "verify_tests.py"
SUMMARY = re.compile(
    r"HARNESS_TEST_SUMMARY runner=unittest tests_run=(\d+) skipped=(\d+) "
    r"executed=(\d+) status=(passed|failed|no-tests)"
)
NODE_REPORTER = """import { resolve } from 'node:path';
export default async function* (events) {
  const counts = {tests: 0, passed: 0, failed: 0, cancelled: 0, skipped: 0, todo: 0};
  let planned = false;
  let unsupported = false;
  let failure = false;
  for await (const event of events) {
    const data = event.data;
    if (event.type === 'test:plan' && data.nesting === 0) planned = true;
    if (event.type !== 'test:pass' && event.type !== 'test:fail') continue;
    const skipped = data.skip !== undefined && data.skip !== false;
    const todo = data.todo !== undefined && data.todo !== false;
    if (event.type === 'test:fail' && !skipped && !todo) failure = true;
    if (data.details?.type === 'suite') continue;
    // Node reports a file with no declared tests as one passing file container.
    // Count declared tests, excluding that container rather than trusting totals.
    if (typeof data.file === 'string' && typeof data.name === 'string' &&
        data.line === 1 && data.column === 1 && resolve(data.name) === resolve(data.file)) continue;
    if (!Number.isInteger(data.line) || data.line < 1) { unsupported = true; continue; }
    counts.tests++;
    if (skipped) counts.skipped++;
    else if (todo) counts.todo++;
    else if (event.type === 'test:pass') counts.passed++;
    else counts.failed++;
  }
  yield JSON.stringify({success: !failure, counts, planned, unsupported}) + '\\n';
}
"""


def _result(runner: str, status: str, exit_code=None, reason=None, **counts) -> dict:
    return {
        "status": status, "exit_code": exit_code, "runner": runner,
        "tests_run": counts.get("tests_run"), "executed": counts.get("executed"),
        "skipped": counts.get("skipped"), "reason": reason,
    }


def _run(workspace: pathlib.Path, argv: list[str]):
    return subprocess.run(
        argv, cwd=workspace, capture_output=True, text=True, timeout=60,
        check=False, env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )


def counted_runner(argv: list[str]) -> str | None:
    """Recognize supported native command shapes without running anything."""
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        return None
    executable = pathlib.Path(argv[0]).name.lower()
    if re.fullmatch(r"python(?:\d+(?:\.\d+)*)?(?:\.exe)?", executable) and argv[1:3] == ["-m", "unittest"]:
        return "unittest"
    if executable in {"node", "node.exe"} and "--test" in argv[1:]:
        return "node-test"
    if executable in {"go", "go.exe"} and argv[1:2] == ["test"]:
        return "go-test"
    return None


def case_support_error(case: dict) -> str | None:
    commands = ([case["verify"]] if case.get("verify") else [])
    commands += [criterion["verify"] for criterion in case.get("acceptance_criteria", [])]
    if any(counted_runner(command) is None for command in commands):
        return "unsupported counted verification runner; no model call or coverage"
    return None


def _fresh_go_args(argv: list[str]) -> list[str] | None:
    args = []
    index = 0
    binary_args = False
    while index < len(argv):
        arg = argv[index]
        if arg in {"-args", "--args"}:
            binary_args = True
        count = re.fullmatch(r"--?(?:test\.)?count(?:=(.*))?", arg)
        if count:
            # A later test-binary flag would override go's injected -test.count=1.
            if binary_args:
                return None
            value = count.group(1)
            if value is None:
                index += 1
                if index >= len(argv):
                    return None
                value = argv[index]
            if not value.isdigit() or int(value) < 1:
                return None
        elif not binary_args and arg in {"-json", "-json=true"}:
            pass
        else:
            args.append(arg)
        index += 1
    return args


def verify_command(workspace: pathlib.Path, argv: list[str], minimum_tests: int = 1) -> dict:
    """Return metadata only. Uncounted successful runners remain unverified.

    Supported counted commands are ``python -m unittest ...`` and ``node --test
    ...``, and ``go test ...``. Python uses the existing result-object adapter. Node's private reporter
    counts documented native result events, discarding test stdout and file paths.
    """
    if isinstance(minimum_tests, bool) or not isinstance(minimum_tests, int) or minimum_tests < 1:
        return _result("unsupported", "error", reason="invalid minimum test count")
    if not isinstance(argv, list) or not argv or any(not isinstance(arg, str) or not arg for arg in argv):
        return _result("unsupported", "error", reason="invalid verification command")
    runner = counted_runner(argv) or "unsupported"
    is_unittest, is_node, is_go = runner == "unittest", runner == "node-test", runner == "go-test"
    try:
        if is_unittest:
            run = _run(workspace, [argv[0], str(ADAPTER), "unittest"] + argv[3:])
            summaries = [SUMMARY.fullmatch(line) for line in run.stderr.splitlines()]
            summaries = [match for match in summaries if match is not None]
            if len(summaries) != 1:
                return _result(runner, "failed" if run.returncode else "unverified", run.returncode,
                               "counted unittest result unavailable")
            match = summaries[0]
            tests_run, skipped, executed = map(int, match.groups()[:3])
            counts = {"tests_run": tests_run, "skipped": skipped, "executed": executed}
            if executed > tests_run:
                return _result(runner, "unverified", run.returncode, "inconsistent native test counts")
            if run.returncode or match.group(4) == "failed":
                status = "failed" if match.group(4) == "failed" else "unverified"
                return _result(runner, status, run.returncode, "tests failed" if status == "failed" else "no executed tests", **counts)
            if match.group(4) != "passed" or executed < minimum_tests:
                return _result(runner, "unverified", run.returncode, "insufficient executed tests", **counts)
            return _result(runner, "passed", run.returncode, **counts)
        if is_node:
            # Caller-selected reporters and non-test modes cannot replace the oracle.
            forbidden = ("--test-reporter", "--watch", "--help", "--eval", "--print")
            if any(arg in {"-h", "-e", "-p"} or arg.startswith(forbidden) for arg in argv[1:]):
                return _result(runner, "unverified", reason="unsupported node test mode or reporter")
            with tempfile.TemporaryDirectory(prefix="harness-node-oracle-") as temp:
                reporter = pathlib.Path(temp) / "counts.mjs"
                reporter.write_text(NODE_REPORTER, encoding="utf-8")
                command = [argv[0], "--test-reporter=" + reporter.as_uri()] + argv[1:]
                run = _run(workspace, command)
            try:
                lines = run.stdout.splitlines()
                if len(lines) != 1:
                    raise ValueError("missing final summary")
                summary = json.loads(lines[0])
                native = summary["counts"]
                values = [native[key] for key in ("tests", "passed", "failed", "cancelled", "skipped", "todo")]
                if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values):
                    raise ValueError("invalid native counts")
                tests_run, passed, failed, cancelled, skipped, todo = values
                if tests_run != passed + failed + cancelled + skipped + todo:
                    raise ValueError("inconsistent native counts")
                executed = tests_run - skipped - todo
                if not isinstance(summary["success"], bool) or summary.get("planned") is not True or summary.get("unsupported") is not False:
                    raise ValueError("invalid or unsupported native result")
            except (ValueError, KeyError, TypeError):
                return _result(runner, "failed" if run.returncode else "unverified", run.returncode,
                               "native node test counts unavailable")
            counts = {"tests_run": tests_run, "skipped": skipped + todo, "executed": executed}
            if run.returncode or failed or cancelled or not summary["success"]:
                return _result(runner, "failed", run.returncode, "tests failed", **counts)
            if executed < minimum_tests:
                return _result(runner, "unverified", run.returncode, "insufficient executed tests", **counts)
            return _result(runner, "passed", run.returncode, **counts)
        if is_go:
            if "-json=false" in argv[2:]:
                return _result(runner, "unverified", reason="native Go JSON events disabled")
            args = _fresh_go_args(argv[2:])
            if args is None:
                return _result(runner, "unverified", reason="unsupported Go count override")
            # Before package and -args arguments, so they cannot absorb the flag.
            run = _run(workspace, [argv[0], "test", "-json", "-count=1"] + args)
            started = {}
            tests_run = skipped = finished = packages = 0
            go_failure = False
            cached = False
            try:
                for line in run.stdout.splitlines():
                    event = json.loads(line)
                    if not isinstance(event, dict):
                        raise ValueError("invalid Go event")
                    action, test, package = event.get("Action"), event.get("Test"), event.get("Package")
                    output = event.get("Output")
                    if event.get("Cached") is True or (isinstance(output, str) and re.search(r"(?m)^ok\s+.+\s+\(cached\)\s*$", output)):
                        cached = True
                    if action == "fail":
                        go_failure = True
                    if test is None:
                        if action == "pass":
                            packages += 1
                        continue
                    if not isinstance(test, str) or not isinstance(package, str):
                        raise ValueError("invalid Go test identity")
                    key = (package, test)
                    if action == "run":
                        if key in started:
                            raise ValueError("overlapping Go test identities")
                        started[key] = True
                        tests_run += 1
                    elif action in {"pass", "skip", "fail"}:
                        if key not in started:
                            raise ValueError("Go test result without run")
                        del started[key]
                        finished += 1
                        skipped += action == "skip"
                if started or finished != tests_run or not packages:
                    raise ValueError("incomplete Go test events")
            except (ValueError, TypeError):
                return _result(runner, "failed" if run.returncode or go_failure else "unverified", run.returncode,
                               "native Go test counts unavailable")
            if cached:
                return _result(runner, "failed" if go_failure or run.returncode else "unverified", run.returncode,
                               "cached Go test replay is not fresh execution evidence")
            counts = {"tests_run": tests_run, "skipped": skipped, "executed": tests_run - skipped}
            if run.returncode or go_failure:
                return _result(runner, "failed", run.returncode, "tests failed", **counts)
            if counts["executed"] < minimum_tests:
                return _result(runner, "unverified", run.returncode, "insufficient executed tests", **counts)
            return _result(runner, "passed", run.returncode, **counts)
        run = _run(workspace, argv)
        return _result(runner, "failed" if run.returncode else "unverified", run.returncode,
                       "unsupported runner has no executed-test evidence")
    except subprocess.TimeoutExpired:
        return _result(runner, "error", reason="verification timed out")
    except OSError:
        return _result(runner, "error", reason="verification could not execute")


def main() -> int:
    if sys.argv[1] == "supports-case":
        case = json.loads(pathlib.Path(sys.argv[2]).read_text(encoding="utf-8"))[int(sys.argv[3])]
        error = case_support_error(case)
        if error:
            print(error)
        return 1 if error else 0
    result = verify_command(pathlib.Path(sys.argv[1]), json.loads(sys.argv[2]))
    print(json.dumps(result, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
