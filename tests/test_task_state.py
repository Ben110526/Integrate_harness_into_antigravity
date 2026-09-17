import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCRIPTS = ROOT / "plugin" / "codex-claude-harness" / "scripts"
import sys
if str(PLUGIN_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(PLUGIN_SCRIPTS))

import task_state
import lifecycle_guard


class TaskStateValidationTests(unittest.TestCase):
    """Test schema conformance and data validation for task state records."""

    def setUp(self) -> None:
        self.valid_state = {
            "schema_version": 1,
            "task_id": "task-alpha-1",
            "workspace": "/repo/workspace",
            "status": "in_progress",
            "brief_revision": "rev-1",
            "active_milestone": "M1",
            "milestones": [
                {
                    "id": "M1",
                    "title": "Harden verification gate",
                    "status": "in_progress",
                    "dependencies": [],
                    "ac_ids": ["AC-1"],
                },
                {
                    "id": "M2",
                    "title": "Autonomous continuation",
                    "status": "pending",
                    "dependencies": ["M1"],
                    "ac_ids": ["AC-2"],
                },
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "outcome": "Verification gate handles python flags",
                    "requirement_source": "M1 spec",
                    "planned_check": "python3 -m unittest tests/test_verification_gate.py",
                    "status": "in_progress",
                },
                {
                    "id": "AC-2",
                    "outcome": "Autonomous continuation dispatches next milestone",
                    "requirement_source": "M2 spec",
                    "planned_check": "python3 -m unittest tests/test_harness_run.py",
                    "status": "pending",
                },
            ],
            "source_fingerprint": {
                "src/app.py": "a" * 64,
                "tests/test_app.py": "b" * 64,
            },
            "evidence": [
                {
                    "id": "ev-1",
                    "ac_id": "AC-1",
                    "command": "pytest -q",
                    "cwd": "/repo/workspace",
                    "exit_code": 0,
                    "test_count_status": "runner-enforced",
                    "timestamp": 1726000000.0,
                }
            ],
            "blockers": [],
            "next_action": "Execute AC-1 tests",
            "updated_at": 1726000000.0,
        }

    def test_valid_state_passes_validation(self) -> None:
        valid, errors = task_state.validate_task_state(self.valid_state)
        self.assertTrue(valid, f"Validation failed unexpectedly: {errors}")
        self.assertEqual(len(errors), 0)

    def test_missing_required_fields_rejected(self) -> None:
        required_fields = [
            "schema_version",
            "task_id",
            "status",
            "brief_revision",
            "active_milestone",
            "milestones",
            "acceptance_criteria",
            "source_fingerprint",
        ]
        for field in required_fields:
            with self.subTest(field=field):
                state = copy.deepcopy(self.valid_state)
                del state[field]
                valid, errors = task_state.validate_task_state(state)
                self.assertFalse(valid)
                self.assertTrue(any(f"Missing required property: {field}" in e for e in errors))

    def test_schema_version_must_equal_one(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["schema_version"] = 2
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("schema_version must be 1" in e for e in errors))

    def test_invalid_task_id_rejected(self) -> None:
        for bad_id in ("../escape", "task/slash", "task with spaces", "a" * 65, "", "@invalid"):
            with self.subTest(bad_id=bad_id):
                state = copy.deepcopy(self.valid_state)
                state["task_id"] = bad_id
                valid, errors = task_state.validate_task_state(state)
                self.assertFalse(valid)

    def test_invalid_status_rejected(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["status"] = "unknown_status"
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("Invalid status" in e for e in errors))

    def test_invalid_milestone_id_pattern(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["milestones"][0]["id"] = "Milestone-1"  # Must match ^M[0-9]+$
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)

    def test_invalid_ac_id_pattern(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["acceptance_criteria"][0]["id"] = "REQ-1"  # Must match ^AC-[0-9]+$
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)

    def test_superseded_ac_requires_reason(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["acceptance_criteria"][0]["status"] = "superseded"
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("superseded_reason" in e for e in errors))

        state["acceptance_criteria"][0]["superseded_reason"] = "Requirement dropped by user"
        valid, errors = task_state.validate_task_state(state)
        self.assertTrue(valid, errors)

    def test_source_fingerprint_hashes_must_be_64_char_hex(self) -> None:
        for bad_hash in ("short", "g" * 64, "A" * 64, 12345):
            with self.subTest(bad_hash=bad_hash):
                state = copy.deepcopy(self.valid_state)
                state["source_fingerprint"]["src/app.py"] = bad_hash
                valid, errors = task_state.validate_task_state(state)
                self.assertFalse(valid)

    def test_unexpected_keys_rejected(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["unsupported_custom_key"] = "forbidden"
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("Unexpected properties" in e for e in errors))

    def test_evidence_ac_id_must_match_acceptance_criteria(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["evidence"].append({
            "id": "ev-unmatched",
            "ac_id": "AC-999",
            "command": "pytest",
            "cwd": "/repo/workspace",
            "exit_code": 0,
        })
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("does not match any acceptance_criteria id" in e for e in errors))

    def test_evidence_id_must_be_non_empty_string(self) -> None:
        state = copy.deepcopy(self.valid_state)
        state["evidence"][0]["id"] = "   "
        valid, errors = task_state.validate_task_state(state)
        self.assertFalse(valid)
        self.assertTrue(any("id must be a non-empty string" in e for e in errors))


class TaskStateStorageAndConfinementTests(unittest.TestCase):
    """Test workspace isolation, atomic persistence, and concurrency locking."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        (self.workspace / "src").mkdir(parents=True)
        (self.workspace / "src" / "app.py").write_text("print('hello')", encoding="utf-8")
        (self.workspace / "tests").mkdir(parents=True)
        (self.workspace / "tests" / "test_app.py").write_text("def test(): pass", encoding="utf-8")

        self.sample_state = {
            "schema_version": 1,
            "task_id": "task-test-42",
            "workspace": str(self.workspace),
            "status": "in_progress",
            "brief_revision": "rev-1",
            "active_milestone": "M1",
            "milestones": [
                {"id": "M1", "title": "Setup", "status": "in_progress"},
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "outcome": "App initialized",
                    "requirement_source": "Spec",
                    "planned_check": "pytest",
                    "status": "verified",
                },
            ],
            "source_fingerprint": task_state.compute_source_fingerprint(self.workspace),
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_task_dir_path_traversal_prevention(self) -> None:
        for bad_id in ("../escaped", "sub/dir", "../../root", "..", "foo/../bar"):
            with self.subTest(bad_id=bad_id):
                with self.assertRaises(ValueError):
                    task_state.get_task_dir(self.workspace, bad_id)

    def test_save_and_load_task_state(self) -> None:
        saved_path = task_state.save_task_state(self.workspace, self.sample_state)
        self.assertTrue(saved_path.is_file())
        self.assertEqual(
            saved_path,
            self.workspace / ".harness" / "tasks" / "task-test-42" / "state.json",
        )

        loaded = task_state.load_task_state(self.workspace, "task-test-42")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["task_id"], "task-test-42")
        self.assertEqual(loaded["status"], "in_progress")
        self.assertIn("updated_at", loaded)

    def test_load_nonexistent_or_corrupt_state_returns_none(self) -> None:
        self.assertIsNone(task_state.load_task_state(self.workspace, "nonexistent"))

        corrupt_dir = self.workspace / ".harness" / "tasks" / "corrupt-task"
        corrupt_dir.mkdir(parents=True)
        (corrupt_dir / "state.json").write_text("{not-valid-json", encoding="utf-8")
        self.assertIsNone(task_state.load_task_state(self.workspace, "corrupt-task"))

    def test_oversized_state_rejected(self) -> None:
        oversized_state = copy.deepcopy(self.sample_state)
        # Add massive blockers to exceed MAX_STATE_BYTES
        oversized_state["blockers"] = ["x" * 1024 for _ in range(600)]
        with self.assertRaises(ValueError) as ctx:
            task_state.save_task_state(self.workspace, oversized_state)
        self.assertIn("exceeds maximum allowed size", str(ctx.exception))

    def test_find_active_tasks_discovers_and_sorts(self) -> None:
        state1 = copy.deepcopy(self.sample_state)
        state1["task_id"] = "task-1"
        task_state.save_task_state(self.workspace, state1)
        time.sleep(0.01)

        state2 = copy.deepcopy(self.sample_state)
        state2["task_id"] = "task-2"
        task_state.save_task_state(self.workspace, state2)

        active = task_state.find_active_tasks(self.workspace)
        self.assertEqual(len(active), 2)
        # Most recently updated first
        self.assertEqual(active[0]["task_id"], "task-2")
        self.assertEqual(active[1]["task_id"], "task-1")

    def test_concurrent_saves_do_not_corrupt_state(self) -> None:
        task_state.save_task_state(self.workspace, self.sample_state)

        def worker_save(iteration: int) -> None:
            state = copy.deepcopy(self.sample_state)
            state["next_action"] = f"Action step {iteration}"
            task_state.save_task_state(self.workspace, state)

        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(worker_save, range(20)))

        loaded = task_state.load_task_state(self.workspace, "task-test-42")
        self.assertIsNotNone(loaded)
        valid, errors = task_state.validate_task_state(loaded)
        self.assertTrue(valid, errors)

    def test_save_task_state_does_not_mutate_caller_dict(self) -> None:
        caller_dict = copy.deepcopy(self.sample_state)
        # Remove optional workspace and updated_at
        caller_dict.pop("workspace", None)
        caller_dict.pop("updated_at", None)

        task_state.save_task_state(self.workspace, caller_dict)

        self.assertNotIn("workspace", caller_dict, "save_task_state must not inject workspace into caller's dict")
        self.assertNotIn("updated_at", caller_dict, "save_task_state must not inject updated_at into caller's dict")


class TaskResumptionAndFingerprintTests(unittest.TestCase):
    """Test deterministic content fingerprinting, drift detection, and stale evidence invalidation."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        (self.workspace / "src").mkdir(parents=True)
        (self.workspace / "src" / "app.py").write_text("def run(): return 42\n", encoding="utf-8")
        (self.workspace / "tests").mkdir(parents=True)
        (self.workspace / "tests" / "test_app.py").write_text("def test_run(): pass\n", encoding="utf-8")

        self.initial_fp = task_state.compute_source_fingerprint(self.workspace)
        self.state = {
            "schema_version": 1,
            "task_id": "resume-task",
            "workspace": str(self.workspace),
            "status": "in_progress",
            "brief_revision": "brief-v1",
            "active_milestone": "M1",
            "milestones": [
                {"id": "M1", "title": "Milestone 1", "status": "in_progress"},
            ],
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "outcome": "Returns 42",
                    "requirement_source": "spec",
                    "planned_check": "pytest",
                    "status": "verified",
                },
                {
                    "id": "AC-2",
                    "outcome": "Handles error",
                    "requirement_source": "spec",
                    "planned_check": "pytest",
                    "status": "pending",
                },
            ],
            "source_fingerprint": self.initial_fp,
        }
        task_state.save_task_state(self.workspace, self.state)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_fingerprint_deterministic_and_ignores_artifacts(self) -> None:
        # Create ignored dirs
        (self.workspace / ".git").mkdir()
        (self.workspace / ".git" / "HEAD").write_text("ref: master", encoding="utf-8")
        (self.workspace / "node_modules").mkdir()
        (self.workspace / "node_modules" / "foo.js").write_text("var x=1;", encoding="utf-8")

        fp = task_state.compute_source_fingerprint(self.workspace)
        self.assertIn("src/app.py", fp)
        self.assertIn("tests/test_app.py", fp)
        self.assertNotIn(".git/HEAD", fp)
        self.assertNotIn("node_modules/foo.js", fp)

    def test_resumption_clean_source_preserves_verified_evidence(self) -> None:
        assessment = task_state.assess_task_resumption(self.workspace, "resume-task")
        self.assertTrue(assessment["can_resume"])
        self.assertTrue(assessment["source_clean"])
        self.assertEqual(assessment["changed_files"], [])
        self.assertEqual(assessment["valid_ac_ids"], ["AC-1"])
        self.assertEqual(assessment["stale_ac_ids"], [])

    def test_resumption_modified_source_invalidates_verified_evidence(self) -> None:
        # Modify src/app.py
        (self.workspace / "src" / "app.py").write_text("def run(): return 99\n", encoding="utf-8")

        assessment = task_state.assess_task_resumption(self.workspace, "resume-task")
        self.assertTrue(assessment["can_resume"])
        self.assertFalse(assessment["source_clean"])
        self.assertIn("src/app.py", assessment["changed_files"])
        self.assertEqual(assessment["valid_ac_ids"], [])
        self.assertEqual(assessment["stale_ac_ids"], ["AC-1"])
        self.assertTrue(any("Source files changed" in r for r in assessment["reasons"]))

    def test_resumption_deleted_source_file_detected(self) -> None:
        # Delete tests/test_app.py
        (self.workspace / "tests" / "test_app.py").unlink()

        assessment = task_state.assess_task_resumption(self.workspace, "resume-task")
        self.assertFalse(assessment["source_clean"])
        self.assertIn("tests/test_app.py", assessment["missing_files"])
        self.assertIn("AC-1", assessment["stale_ac_ids"])

    def test_resumption_revised_brief_invalidates_evidence(self) -> None:
        # Pass a different brief revision
        assessment = task_state.assess_task_resumption(
            self.workspace, "resume-task", current_brief_revision="brief-v2"
        )
        self.assertTrue(assessment["can_resume"])
        self.assertIn("AC-1", assessment["stale_ac_ids"])
        self.assertTrue(any("Brief revision changed" in r for r in assessment["reasons"]))

    def test_lifecycle_guard_task_resume_context_hint(self) -> None:
        hint = lifecycle_guard._task_context_hints([self.workspace])
        self.assertIsNotNone(hint)
        assert hint is not None
        self.assertIn("resume-task", hint)
        self.assertIn("in_progress", hint)
        self.assertIn("M1", hint)
        self.assertIn("1/2 ACs verified", hint)
        self.assertIn("Source fingerprint matches checkpoint", hint)

        # Now mutate source and check that hint flags stale evidence
        (self.workspace / "src" / "app.py").write_text("changed", encoding="utf-8")
        hint_stale = lifecycle_guard._task_context_hints([self.workspace])
        self.assertIsNotNone(hint_stale)
        assert hint_stale is not None
        self.assertIn("marked stale", hint_stale)


class TaskStateCLITests(unittest.TestCase):
    """Test CLI commands: init, list, validate, resume, fingerprint."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.workspace = Path(self.temp_dir.name).resolve()
        (self.workspace / "src").mkdir(parents=True)
        (self.workspace / "src" / "main.py").write_text("print('hello')", encoding="utf-8")

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_cli_init_list_validate_resume(self) -> None:
        import io
        import sys
        from unittest.mock import patch

        # 1. Test init
        with patch.object(sys, "argv", [
            "task_state.py", "init",
            "--task-id", "task-cli-100",
            "--milestones", "M1,M2",
            "--acs", "AC-1,AC-2",
            "--workspace", str(self.workspace),
        ]):
            task_state.main()

        state_file = self.workspace / ".harness" / "tasks" / "task-cli-100" / "state.json"
        self.assertTrue(state_file.is_file())

        # 2. Test validate
        with patch.object(sys, "argv", [
            "task_state.py", "validate",
            str(state_file),
        ]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                task_state.main()
                self.assertIn("Valid:", out.getvalue())

        # 3. Test list
        with patch.object(sys, "argv", [
            "task_state.py", "list",
            str(self.workspace),
        ]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                task_state.main()
                self.assertIn("task-cli-100", out.getvalue())

        # 4. Test resume
        with patch.object(sys, "argv", [
            "task_state.py", "resume",
            "task-cli-100",
            str(self.workspace),
        ]):
            with patch("sys.stdout", new_callable=io.StringIO) as out:
                task_state.main()
                output = out.getvalue()
                self.assertIn('"can_resume": true', output)
                self.assertIn('"task_id": "task-cli-100"', output)


if __name__ == "__main__":
    unittest.main()
