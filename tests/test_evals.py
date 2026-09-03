import json
import os
import pathlib
import subprocess
import tempfile
import unittest

from evals.validate_changed_paths import changed_path_error


ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "evals" / "cases.json"
FIXTURES = ROOT / "evals" / "fixtures"
ROUTES = {"DIRECT", "RESEARCH", "IMPLEMENT", "COMPLEX_IMPLEMENT", "REVIEW_VERIFY"}


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
