import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest

from evals.quota_benchmark import (
    BenchmarkError,
    normalized_usage,
    require_response_contract,
    safe_fixture_path,
    terminal_result,
    workspace_snapshot,
)
from evals.validate_changed_paths import changed_path_error


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
FIXTURES = ROOT / "evals" / "fixtures"
ROUTES = {
    "DIRECT",
    "LOCAL_LOOKUP",
    "RESEARCH",
    "IMPLEMENT",
    "COMPLEX_IMPLEMENT",
    "REVIEW_ONLY",
    "REVIEW_VERIFY",
}


class EvalManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))

    def test_manifest_has_unique_ids_and_required_language_coverage(self) -> None:
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue({"python", "javascript", "go", "rust"}.issubset(
            {case["language"] for case in self.cases}
        ))

    def test_each_case_has_a_runnable_and_consistent_contract(self) -> None:
        for case in self.cases:
            with self.subTest(case=case.get("id")):
                self.assertIn(case["route"], ROUTES)
                self.assertIsInstance(case["prompt"], str)
                self.assertTrue(case["prompt"].strip())
                self.assertIsInstance(case["expect_change"], bool)
                self.assertIsInstance(case["verify"], list)
                self.assertTrue(all(isinstance(arg, str) and arg for arg in case["verify"]))
                self.assertIsInstance(case.get("requires", []), list)
                self.assertTrue(all(
                    isinstance(command, str) and command
                    for command in case.get("requires", [])
                ))
                self.assertIsInstance(case.get("benchmark", False), bool)
                if case.get("benchmark"):
                    self.assertFalse(case["expect_change"])
                    self.assertEqual(case["allowed_changed_paths"], [])
                for response_key in (
                    "response_contains", "response_not_contains", "response_only_lines"
                ):
                    response_terms = case.get(response_key, [])
                    self.assertIsInstance(response_terms, list)
                    self.assertEqual(len(response_terms), len(set(response_terms)))
                    self.assertTrue(all(
                        isinstance(term, str) and term
                        for term in response_terms
                    ))
                self.assertTrue(
                    set(case.get("response_contains", [])).isdisjoint(
                        case.get("response_not_contains", [])
                    )
                )
                self.assertTrue(set(case.get("response_only_lines", [])).issubset(
                    case.get("response_contains", [])
                ))
                if case["verify"]:
                    self.assertIn(case["verify"][0], case["requires"])

                criteria = case.get("acceptance_criteria", [])
                self.assertIsInstance(criteria, list)
                criterion_ids = [criterion["id"] for criterion in criteria]
                self.assertEqual(len(criterion_ids), len(set(criterion_ids)))
                for criterion in criteria:
                    self.assertTrue(criterion["id"].strip())
                    self.assertTrue(criterion["description"].strip())
                    self.assertTrue(all(
                        isinstance(arg, str) and arg
                        for arg in criterion["verify"]
                    ))
                    self.assertIn(criterion["verify"][0], case["requires"])

                fixture = FIXTURES / case["fixture"]
                self.assertTrue(fixture.is_dir(), f"missing fixture: {fixture}")
                required_paths = case.get("required_changed_paths", [])
                allowed_paths = case["allowed_changed_paths"]
                self.assertEqual(case["expect_change"], bool(required_paths))
                self.assertTrue(set(required_paths).issubset(allowed_paths))
                for relative_path in allowed_paths:
                    relative = pathlib.PurePosixPath(relative_path)
                    self.assertFalse(relative.is_absolute())
                    self.assertNotIn("..", relative.parts)
                    self.assertTrue((fixture / relative_path).is_file())

    def test_complex_route_covers_multi_component_security_and_persistence(self) -> None:
        complex_cases = [case for case in self.cases if case["route"] == "COMPLEX_IMPLEMENT"]
        self.assertTrue(complex_cases)
        for case in complex_cases:
            with self.subTest(case=case["id"]):
                self.assertGreaterEqual(len(case["required_changed_paths"]), 2)
                self.assertEqual(
                    set(case["allowed_changed_paths"]),
                    set(case["required_changed_paths"]),
                )
                self.assertIn("COMPLEX_IMPLEMENT", case.get("response_contains", []))
                prompt = case["prompt"].lower()
                self.assertIn("subagent", prompt)
                self.assertIn("security", prompt)
                self.assertIn("persistence", prompt)
                criteria = case.get("acceptance_criteria", [])
                self.assertGreaterEqual(len(criteria), 3)
                self.assertLessEqual(len(criteria), 4)
                self.assertEqual(
                    [criterion["id"] for criterion in criteria],
                    [f"AC-{index}" for index in range(1, len(criteria) + 1)],
                )
                for criterion in criteria:
                    self.assertIn(criterion["id"], case.get("response_contains", []))
                fixture = FIXTURES / case["fixture"]
                test_sources = "\n".join(
                    path.read_text(encoding="utf-8")
                    for path in fixture.rglob("*")
                    if path.is_file() and "test" in path.name
                )
                for criterion in criteria:
                    command = criterion["verify"]
                    self.assertIn("--test-name-pattern", command)
                    pattern_index = command.index("--test-name-pattern") + 1
                    self.assertLess(pattern_index, len(command))
                    self.assertIn(command[pattern_index], test_sources)

    def test_nonexistent_symbol_case_rejects_hallucinated_evidence(self) -> None:
        case = next(
            case for case in self.cases
            if case["id"] == "nonexistent-symbol-read-only"
        )
        self.assertEqual(case["route"], "REVIEW_VERIFY")
        self.assertFalse(case["expect_change"])
        self.assertEqual(case["allowed_changed_paths"], [])
        self.assertEqual(case["verify"], [])
        self.assertIn(
            "SYMBOL_STATUS: calculate_tax NOT_FOUND",
            case["response_contains"],
        )
        self.assertIn("FILES_CHANGED: none", case["response_contains"])
        self.assertIn(
            "SYMBOL_STATUS: calculate_tax FOUND",
            case["response_not_contains"],
        )
        self.assertIn("SYMBOL_LOCATION:", case["response_not_contains"])
        self.assertEqual(
            case["response_only_lines"],
            [
                "SYMBOL_STATUS: calculate_tax NOT_FOUND",
                "FILES_CHANGED: none",
                "Harness: REVIEW_VERIFY; passed: repository symbol search; failed/skipped: none",
            ],
        )

        fixture = FIXTURES / case["fixture"]
        fixture_text = "\n".join(
            path.read_text(encoding="utf-8")
            for path in fixture.rglob("*")
            if path.is_file()
        )
        self.assertNotIn("calculate_tax", fixture_text)

    def test_quota_routes_have_deterministic_read_only_cases(self) -> None:
        by_id = {case["id"]: case for case in self.cases}
        local_lookup = by_id["local-lookup-existing-symbol"]
        self.assertEqual(local_lookup["route"], "LOCAL_LOOKUP")
        self.assertTrue(local_lookup["benchmark"])
        self.assertNotIn("calculator.py:1", local_lookup["prompt"])
        self.assertNotIn("divide FOUND", local_lookup["prompt"])
        self.assertEqual(
            local_lookup["response_only_lines"],
            [
                "SYMBOL_STATUS: divide FOUND",
                "SYMBOL_LOCATION: calculator.py:1",
                "FILES_CHANGED: none",
                "Harness: LOCAL_LOOKUP; passed: exact local symbol lookup; failed/skipped: none",
            ],
        )
        fixture = FIXTURES / local_lookup["fixture"]
        self.assertEqual(
            (fixture / "calculator.py").read_text(encoding="utf-8").splitlines()[0],
            "def divide(left: float, right: float) -> float:",
        )

        review_only = by_id["review-only-conceptual"]
        self.assertEqual(review_only["route"], "REVIEW_ONLY")
        self.assertTrue(review_only["benchmark"])
        self.assertNotIn("Harness: REVIEW_ONLY", review_only["prompt"])
        self.assertIn("ValueError", review_only["response_contains"])
        self.assertIn("ZeroDivisionError", review_only["response_contains"])
        self.assertEqual(
            by_id["nonexistent-symbol-read-only"]["route"],
            "REVIEW_VERIFY",
        )

    def test_quota_usage_parser_accepts_official_json_and_stream_json(self) -> None:
        usage = {
            "input_tokens": 100,
            "output_tokens": 20,
            "thinking_tokens": 8,
            "cache_read_tokens": 60,
            "total_tokens": 120,
        }
        envelope = {
            "status": "SUCCESS",
            "duration_seconds": 1.25,
            "usage": usage,
        }
        self.assertEqual(
            normalized_usage(terminal_result(json.dumps(envelope), "json")),
            usage,
        )
        stream = "\n".join((
            json.dumps({"event": "init", "init": {"tools": []}}),
            json.dumps({"event": "result", "result": envelope}),
        ))
        self.assertEqual(
            normalized_usage(terminal_result(stream, "stream-json")),
            usage,
        )
        response_case = {
            "route": "LOCAL_LOOKUP",
            "response_contains": ["SYMBOL_STATUS: divide FOUND"],
            "response_not_contains": ["NOT_FOUND"],
        }
        route_envelope = {
            "response": (
                "SYMBOL_STATUS: divide FOUND\n"
                "Harness: LOCAL_LOOKUP; passed: lookup; failed/skipped: none"
            )
        }
        require_response_contract(route_envelope, response_case)
        with self.assertRaises(BenchmarkError):
            require_response_contract(
                {"response": route_envelope["response"] + "\nNOT_FOUND"},
                response_case,
            )
        with self.assertRaises(BenchmarkError):
            terminal_result('{"event":"init"}\n', "stream-json")
        with self.assertRaises(BenchmarkError):
            normalized_usage({"usage": {"input_tokens": -1}})

    def test_quota_benchmark_is_opt_in_and_emits_usage_only(self) -> None:
        runner = ROOT / "evals" / "quota_benchmark.py"
        refused = subprocess.run(
            [
                "python3",
                str(runner),
                "--case",
                "local-lookup-existing-symbol",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(refused.returncode, 2)
        self.assertEqual(
            json.loads(refused.stdout)["event"],
            "benchmark_refused",
        )

        fixture_file = FIXTURES / "python-calculator" / "calculator.py"
        fixture_before = fixture_file.read_bytes()
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_agy = pathlib.Path(temp_dir) / "agy"
            fake_home = pathlib.Path(temp_dir) / "home"
            installed_plugin = (
                fake_home
                / ".gemini"
                / "config"
                / "plugins"
                / "codex-claude-harness"
            )
            shutil.copytree(
                ROOT / "plugin" / "codex-claude-harness",
                installed_plugin,
            )
            fake_agy.write_text(
                """#!/bin/sh
if [ -n "${FAKE_CALL_MARKER:-}" ]; then
  : > "$FAKE_CALL_MARKER"
fi
if [ "${FAKE_BAD:-0}" = "1" ]; then
  response='SYMBOL_STATUS: divide NOT_FOUND\\nHarness: LOCAL_LOOKUP; passed: exact local symbol lookup; failed/skipped: none'
else
  response='SYMBOL_STATUS: divide FOUND\\nSYMBOL_LOCATION: calculator.py:1\\nFILES_CHANGED: none\\nHarness: LOCAL_LOOKUP; passed: exact local symbol lookup; failed/skipped: none'
fi
if [ "${FAKE_MUTATE:-0}" = "1" ]; then
  printf '%s\\n' '# unexpected mutation' >> calculator.py
fi
if [ "${FAKE_EMPTY_DIR:-0}" = "1" ]; then
  mkdir unexpected-empty-dir
fi
printf '{"conversation_id":"must-not-leak","status":"SUCCESS","response":"%s","duration_seconds":1.5,"num_turns":1,"usage":{"input_tokens":100,"output_tokens":20,"thinking_tokens":8,"cache_read_tokens":60,"total_tokens":120}}\\n' "$response"
""",
                encoding="utf-8",
            )
            fake_agy.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temp_dir}{os.pathsep}{environment['PATH']}"
            environment["HOME"] = str(fake_home)
            environment["USERPROFILE"] = str(fake_home)
            completed = subprocess.run(
                [
                    "python3",
                    str(runner),
                    "--case",
                    "local-lookup-existing-symbol",
                    "--repeat",
                    "2",
                    "--confirm-quota-use",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            environment["FAKE_BAD"] = "1"
            rejected = subprocess.run(
                [
                    "python3",
                    str(runner),
                    "--case",
                    "local-lookup-existing-symbol",
                    "--repeat",
                    "2",
                    "--confirm-quota-use",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            environment.pop("FAKE_BAD")
            environment["FAKE_MUTATE"] = "1"
            mutated = subprocess.run(
                [
                    "python3",
                    str(runner),
                    "--case",
                    "local-lookup-existing-symbol",
                    "--repeat",
                    "2",
                    "--confirm-quota-use",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            environment.pop("FAKE_MUTATE")
            environment["FAKE_EMPTY_DIR"] = "1"
            mutated_directory = subprocess.run(
                [
                    "python3",
                    str(runner),
                    "--case",
                    "local-lookup-existing-symbol",
                    "--repeat",
                    "2",
                    "--confirm-quota-use",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )

            environment.pop("FAKE_EMPTY_DIR")
            call_marker = pathlib.Path(temp_dir) / "agy-called"
            environment["FAKE_CALL_MARKER"] = str(call_marker)
            installed_policy = (
                installed_plugin / "rules" / "engineering-harness.md"
            )
            installed_policy.write_text("stale policy\n", encoding="utf-8")
            stale_install = subprocess.run(
                [
                    "python3",
                    str(runner),
                    "--case",
                    "local-lookup-existing-symbol",
                    "--repeat",
                    "2",
                    "--confirm-quota-use",
                ],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            stale_install_called_agy = call_marker.exists()

        self.assertEqual(completed.returncode, 0, completed.stderr)
        events = [json.loads(line) for line in completed.stdout.splitlines()]
        samples = [event for event in events if event["event"] == "benchmark_sample"]
        self.assertEqual(len(samples), 2)
        self.assertTrue(all(sample["usage"]["total_tokens"] == 120 for sample in samples))
        summary = next(event for event in events if event["event"] == "benchmark_summary")
        self.assertEqual(summary["route"], "LOCAL_LOOKUP")
        self.assertEqual(summary["samples"], 2)
        self.assertEqual(summary["mean_usage"]["cache_read_tokens"], 60.0)
        self.assertNotIn("conversation_id", completed.stdout)
        self.assertNotIn("must-not-leak", completed.stdout)
        self.assertNotIn("SYMBOL_STATUS", completed.stdout)
        self.assertEqual(fixture_file.read_bytes(), fixture_before)
        self.assertEqual(rejected.returncode, 1)
        rejected_events = [json.loads(line) for line in rejected.stdout.splitlines()]
        rejected_samples = [
            event for event in rejected_events
            if event["event"] == "benchmark_sample"
        ]
        self.assertEqual(len(rejected_samples), 2)
        self.assertTrue(all(event["status"] == "ERROR" for event in rejected_samples))
        self.assertNotIn("SYMBOL_STATUS", rejected.stdout)
        self.assertEqual(mutated.returncode, 1)
        self.assertNotIn("unexpected mutation", mutated.stdout)
        self.assertEqual(mutated_directory.returncode, 1)
        self.assertNotIn("unexpected-empty-dir", mutated_directory.stdout)
        self.assertEqual(stale_install.returncode, 2)
        self.assertEqual(
            json.loads(stale_install.stdout)["event"],
            "benchmark_refused",
        )
        self.assertFalse(stale_install_called_agy)

    def test_quota_snapshot_rejects_symlinks_without_following_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = pathlib.Path(temp_dir) / "workspace"
            workspace.mkdir()
            (workspace / "regular.txt").write_text("safe", encoding="utf-8")
            external = pathlib.Path(temp_dir) / "external.txt"
            external.write_text("must not be read", encoding="utf-8")
            link = workspace / "external-link"
            try:
                link.symlink_to(external)
            except (NotImplementedError, OSError):
                self.skipTest("symlinks are unavailable on this platform")

            with self.assertRaises(BenchmarkError):
                workspace_snapshot(workspace)

    def test_quota_fixture_path_rejects_escape_and_absolute_paths(self) -> None:
        self.assertEqual(
            safe_fixture_path("python-calculator"),
            (FIXTURES / "python-calculator").resolve(),
        )
        for unsafe in ("../outside", "/tmp/outside", "nested\\outside", ""):
            with self.subTest(path=unsafe), self.assertRaises(BenchmarkError):
                safe_fixture_path(unsafe)

    def test_smoke_runner_enforces_response_not_contains(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_agy = pathlib.Path(temp_dir) / "agy"
            fake_agy.write_text(
                """#!/bin/sh
if [ "${FAKE_FORBIDDEN:-0}" = "1" ]; then
  printf '%s\\n' '{"status":"SUCCESS","conversation_id":"fake","response":"SYMBOL_STATUS: calculate_tax NOT_FOUND\\nFILES_CHANGED: none\\nsymbol_location: tax.py\\nHarness: REVIEW_VERIFY; passed: repository symbol search; failed/skipped: none"}'
elif [ "${FAKE_INVENTED:-0}" = "1" ]; then
  printf '%s\\n' '{"status":"SUCCESS","conversation_id":"fake","response":"SYMBOL_STATUS: calculate_tax NOT_FOUND\\nFILES_CHANGED: none\\ncalculate_tax is defined in calculator.py:10\\nHarness: REVIEW_VERIFY; passed: repository symbol search; failed/skipped: none"}'
else
  printf '%s\\n' '{"status":"SUCCESS","conversation_id":"fake","response":"SYMBOL_STATUS: calculate_tax NOT_FOUND\\nFILES_CHANGED: none\\nHarness: REVIEW_VERIFY; passed: repository symbol search; failed/skipped: none"}'
fi
""",
                encoding="utf-8",
            )
            fake_agy.chmod(0o755)
            environment = os.environ.copy()
            environment["PATH"] = f"{temp_dir}{os.pathsep}{environment['PATH']}"
            environment["HARNESS_EVAL_CASE"] = "nonexistent-symbol-read-only"

            accepted = subprocess.run(
                ["bash", str(ROOT / "evals" / "run-smoke.sh")],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(accepted.returncode, 0, accepted.stderr)

            environment["FAKE_FORBIDDEN"] = "1"
            rejected = subprocess.run(
                ["bash", str(ROOT / "evals" / "run-smoke.sh")],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(rejected.returncode, 0)
            self.assertIn("response contains forbidden terms", rejected.stderr)

            environment.pop("FAKE_FORBIDDEN")
            environment["FAKE_INVENTED"] = "1"
            invented = subprocess.run(
                ["bash", str(ROOT / "evals" / "run-smoke.sh")],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertNotEqual(invented.returncode, 0)
            self.assertIn("unexpected response lines", invented.stderr)

    def test_changed_path_contract_rejects_test_or_manifest_edits(self) -> None:
        required = {"src/policy.mjs", "src/store.mjs"}
        allowed = set(required)
        self.assertIsNone(changed_path_error(set(required), required, allowed))
        error = changed_path_error(
            required | {"test/store.test.mjs", "package.json"},
            required,
            allowed,
        )
        self.assertIsNotNone(error)
        self.assertIn("package.json", error or "")
        self.assertIn("test/store.test.mjs", error or "")


if __name__ == "__main__":
    unittest.main()
