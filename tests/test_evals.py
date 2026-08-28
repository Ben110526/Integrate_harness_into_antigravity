import json
import pathlib
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
                if case["verify"]:
                    self.assertIn(case["verify"][0], case["requires"])

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
