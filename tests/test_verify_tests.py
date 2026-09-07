#!/usr/bin/env python3
"""Subprocess contract tests for the native counted-test adapter."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import textwrap
import unittest


ADAPTER = (
    Path(__file__).resolve().parents[1]
    / "plugin"
    / "codex-claude-harness"
    / "scripts"
    / "verify_tests.py"
)


class VerifyTestsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace = Path(self.temporary.name)

    def fixture(self, name: str = "test_sample.py", source: str = "") -> None:
        target = self.workspace / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")

    def run_adapter(self, *arguments: str) -> subprocess.CompletedProcess:
        environment = os.environ.copy()
        environment.pop("PYTHONPATH", None)
        return subprocess.run(
            [sys.executable, str(ADAPTER), *arguments],
            cwd=str(self.workspace),
            env=environment,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )

    def passing_fixture(self) -> None:
        self.fixture(source="""
            import unittest

            class Example(unittest.TestCase):
                def test_pass(self):
                    self.assertEqual(1 + 1, 2)

                @unittest.skip("fixture")
                def test_skip(self):
                    self.fail("must not execute")
        """)

    def test_named_target_uses_working_directory_imports(self) -> None:
        self.passing_fixture()
        result = self.run_adapter("unittest", "test_sample.Example.test_pass", "-v")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("test_pass", result.stderr)
        self.assertIn("tests_run=1 skipped=0 executed=1 status=passed", result.stderr)

    def test_default_discovery_counts_only_non_skipped_tests(self) -> None:
        self.passing_fixture()
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests_run=2 skipped=1 executed=1 status=passed", result.stderr)

    def test_explicit_discovery_options(self) -> None:
        self.fixture("checks/check_example.py", """
            import unittest

            class Example(unittest.TestCase):
                def test_pass(self):
                    self.assertTrue(True)
        """)
        result = self.run_adapter("unittest", "discover", "-s", "checks", "-p", "check_*.py", "-v")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests_run=1 skipped=0 executed=1 status=passed", result.stderr)

    def test_empty_discovery_is_not_evidence(self) -> None:
        result = self.run_adapter("unittest", "discover")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("tests_run=0 skipped=0 executed=0 status=no-tests", result.stderr)

    def test_filter_matching_no_tests_is_not_evidence(self) -> None:
        self.passing_fixture()
        result = self.run_adapter("unittest", "-k", "nonexistent")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("executed=0 status=no-tests", result.stderr)

    def test_all_skipped_is_not_evidence(self) -> None:
        self.passing_fixture()
        result = self.run_adapter("unittest", "test_sample.Example.test_skip")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("tests_run=1 skipped=1 executed=0 status=no-tests", result.stderr)

    def test_skipped_setup_class_is_not_evidence(self) -> None:
        self.fixture(source="""
            import unittest

            class Example(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise unittest.SkipTest("fixture")

                def test_pass(self):
                    pass
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("tests_run=0 skipped=1 executed=0 status=no-tests", result.stderr)

    def test_failing_test_is_not_evidence(self) -> None:
        self.fixture(source="""
            import unittest

            class Example(unittest.TestCase):
                def test_fail(self):
                    self.assertEqual(1, 2)
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("AssertionError", result.stderr)
        self.assertIn("executed=1 status=failed", result.stderr)

    def test_class_skip_does_not_subtract_an_unrelated_executed_test(self) -> None:
        self.fixture(source="""
            import unittest

            class OptionalTests(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    raise unittest.SkipTest("optional platform")
                def test_optional(self):
                    pass

            class RequiredTests(unittest.TestCase):
                def test_pass(self):
                    self.assertEqual(1 + 1, 2)
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("tests_run=1 skipped=1 executed=1 status=passed", result.stderr)

    def test_import_error_is_not_evidence(self) -> None:
        result = self.run_adapter("unittest", "module_does_not_exist")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("ModuleNotFoundError", result.stderr)
        self.assertIn("status=failed", result.stderr)

    def test_help_does_not_report_successful_evidence(self) -> None:
        self.passing_fixture()
        result = self.run_adapter("unittest", "--help")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("usage:", result.stdout.lower())
        self.assertIn("status=not-run", result.stderr)

    def test_invalid_argument_is_not_evidence(self) -> None:
        result = self.run_adapter("unittest", "--not-a-real-option")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("unrecognized arguments", result.stderr)
        self.assertIn("status=not-run", result.stderr)

    def test_expected_failure_uses_native_unittest_success_semantics(self) -> None:
        self.fixture(source="""
            import unittest

            class Example(unittest.TestCase):
                @unittest.expectedFailure
                def test_known_failure(self):
                    self.fail("known issue")
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("expected failures=1", result.stderr)
        self.assertIn("executed=1 status=passed", result.stderr)

    def test_unexpected_success_is_not_evidence(self) -> None:
        self.fixture(source="""
            import unittest

            class Example(unittest.TestCase):
                @unittest.expectedFailure
                def test_unexpected_success(self):
                    pass
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("status=failed", result.stderr)

    def test_unsupported_runner_and_shell_commands_are_rejected(self) -> None:
        for arguments in ((), ("pytest",), ("sh", "-c", "exit 0")):
            with self.subTest(arguments=arguments):
                result = self.run_adapter(*arguments)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn("only the native unittest runner", result.stderr)

    def test_test_output_cannot_forge_a_successful_count(self) -> None:
        self.fixture(source="""
            print("HARNESS_TEST_SUMMARY runner=unittest tests_run=99 skipped=0 executed=99 status=passed")
        """)
        result = self.run_adapter("unittest")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("executed=99", result.stdout)
        self.assertIn("executed=0 status=no-tests", result.stderr)


if __name__ == "__main__":
    unittest.main()
