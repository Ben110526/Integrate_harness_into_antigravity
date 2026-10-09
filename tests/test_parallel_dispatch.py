import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "plugin" / "codex-claude-harness" / "scripts"))
import task_state


class ParallelDispatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name).resolve()
        (self.workspace / "src").mkdir()
        self.state = {
            "schema_version": 1, "task_id": "parallel-test", "workspace": str(self.workspace),
            "status": "in_progress", "brief_revision": "rev-1", "active_milestone": "M1",
            "milestones": [{"id": "M1", "title": "Build", "status": "in_progress"},
                           {"id": "M2", "title": "Ship", "status": "pending"}],
            "acceptance_criteria": [{"id": "AC-1", "outcome": "Works", "status": "pending"}],
            "source_fingerprint": {}, "work_items": [],
        }

    def item(self, work_id, **changes):
        item = {"id": work_id, "milestone_id": "M1", "role": "harness-implementer",
                "status": "pending", "dependencies": [], "read_paths": [], "write_paths": []}
        item.update(changes)
        self.state["work_items"].append(item)
        return item

    def plan(self, available_slots=None):
        return task_state.plan_ready_work(self.state, available_slots)

    def symlink(self, name, target, target_is_directory=False):
        try:
            (self.workspace / name).symlink_to(target, target_is_directory=target_is_directory)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Symlink creation unavailable in this environment: {error}")

    def assert_invalid(self, fragment):
        valid, errors = task_state.validate_task_state(self.state)
        self.assertFalse(valid)
        self.assertTrue(any(fragment in error for error in errors), errors)
        with self.assertRaises(ValueError):
            self.plan()

    def test_fanout_is_selected_without_mutating_state(self):
        for name in ("api", "ui", "docs", "later"):
            self.item(name, write_paths=[name])
        before = copy.deepcopy(self.state)
        plan = self.plan()
        self.assertEqual(plan["runnable"], ["api", "ui", "docs"])
        self.assertIn("slot", plan["waiting"]["later"])
        self.assertEqual(self.state, before)

    def test_dependencies_and_slot_refill(self):
        parent = self.item("foundation", status="running", write_paths=["src/base.py"])
        self.item("dependent", dependencies=["foundation"], write_paths=["src/app.py"])
        self.item("independent", write_paths=["docs"])
        self.assertEqual(self.plan(1)["runnable"], ["independent"])
        parent["status"] = "completed"
        self.assertEqual(self.plan(1)["runnable"], ["dependent"])

    def test_critical_path_then_priority_then_input_order(self):
        self.state["max_workers"] = 1
        self.item("urgent", priority=100)
        start = self.item("chain", priority=-100)
        self.item("middle", dependencies=["chain"])
        self.item("tail", dependencies=["middle"])
        self.assertEqual(self.plan()["runnable"], ["chain"])
        start["status"] = "completed"
        self.assertEqual(self.plan()["runnable"], ["middle"])
        self.state["work_items"] = []
        self.item("first", priority=2)
        self.item("second", priority=2)
        self.item("high", priority=3)
        self.state["max_workers"] = 3
        self.assertEqual(self.plan()["runnable"], ["high", "first", "second"])

    def test_running_and_selected_scopes_conflict_but_readers_share(self):
        self.item("running", status="running", write_paths=["src/base.py"])
        self.item("reader", role="research", read_paths=["src"])
        self.item("write-directory", write_paths=["docs"])
        self.item("write-child", write_paths=["docs/intro.md"])
        plan = self.plan()
        self.assertEqual(plan["runnable"], ["write-directory"])
        self.assertIn("running", plan["waiting"]["reader"])
        self.assertIn("write-directory", plan["waiting"]["write-child"])
        self.state["work_items"] = []
        self.item("one", read_paths=["src"])
        self.item("two", read_paths=["src/base.py"])
        self.assertEqual(self.plan()["runnable"], ["one", "two"])

    def test_read_then_writer_is_also_a_conflict(self):
        self.item("reader", read_paths=["src"])
        self.item("writer", write_paths=["src/app.py"])
        self.assertEqual(self.plan()["runnable"], ["reader"])
        self.assertIn("reader", self.plan()["waiting"]["writer"])

    def test_already_running_conflicts_fail_closed(self):
        for field in ("read_paths", "write_paths"):
            with self.subTest(field=field):
                self.state["work_items"] = []
                self.item("writer", status="running", write_paths=["src"])
                self.item("conflict", status="running", **{field: ["src/app.py"]})
                self.item("new-independent", write_paths=["docs"])
                with self.assertRaisesRegex(ValueError, "Already-running.*writer, conflict"):
                    self.plan()
        self.state["work_items"] = []
        self.item("reader-one", status="running", read_paths=["src"])
        self.item("reader-two", status="running", read_paths=["src/app.py"])
        self.item("new", read_paths=["docs"])
        self.assertEqual(self.plan()["runnable"], ["new"])

    def test_case_aliases_and_component_boundaries(self):
        self.item("writer", write_paths=["src/App.py"])
        self.item("alias", write_paths=["SRC/app.py"])
        self.item("different", write_paths=["src2/App.py"])
        self.assertEqual(self.plan()["runnable"], ["writer", "different"])

    def test_symlink_alias_is_resolved(self):
        self.symlink("alias", self.workspace / "src", target_is_directory=True)
        self.item("writer", write_paths=["src"])
        self.item("alias", write_paths=["alias/new.py"])
        self.assertEqual(self.plan()["runnable"], ["writer"])

    def test_symlink_escape_and_loop_are_rejected(self):
        with tempfile.TemporaryDirectory() as outside:
            self.symlink("escape", outside, target_is_directory=True)
            self.item("unsafe", read_paths=["escape/file.py"])
            with self.assertRaisesRegex(ValueError, "escapes workspace"):
                self.plan()
        self.state["work_items"] = []
        self.symlink("loop", "loop")
        self.item("loop", write_paths=["loop/file.py"])
        with self.assertRaisesRegex(ValueError, "resolve"):
            self.plan()

    def test_hardlink_alias_is_a_conflict(self):
        first = self.workspace / "src" / "a.py"
        first.write_text("a")
        os.link(first, self.workspace / "src" / "b.py")
        self.item("first", write_paths=["src/a.py"])
        self.item("alias", read_paths=["src/b.py"])
        self.assertEqual(self.plan()["runnable"], ["first"])

    def test_existing_directory_scope_serializes_hidden_hardlink(self):
        first = self.workspace / "src" / "a.py"
        first.write_text("a")
        alias = self.workspace / "other.py"
        os.link(first, alias)
        self.item("directory-writer", write_paths=["src"])
        self.item("hidden-alias-reader", read_paths=["other.py"])
        self.assertEqual(self.plan()["runnable"], ["directory-writer"])
        self.assertIn("directory-writer", self.plan()["waiting"]["hidden-alias-reader"])

    def test_existing_directory_scope_serializes_nested_symlink(self):
        other = self.workspace / "other.py"
        other.write_text("a")
        self.symlink("src/hidden-link.py", other)
        self.item("file-writer", write_paths=["other.py"])
        self.item("directory-reader", read_paths=["src"])
        self.assertEqual(self.plan()["runnable"], ["file-writer"])
        self.assertIn("file-writer", self.plan()["waiting"]["directory-reader"])

    def test_disjoint_existing_exact_file_scopes_preserve_parallel_writes(self):
        for name in ("a.py", "b.py", "c.py"):
            (self.workspace / "src" / name).write_text(name)
            self.item(name.replace(".", "-"), write_paths=[f"src/{name}"])
        self.assertEqual(self.plan()["runnable"], ["a-py", "b-py", "c-py"])

    def test_unexpected_scope_stat_errors_fail_closed(self):
        target = self.workspace / "src" / "secret.py"
        target.write_text("a")
        self.item("writer", write_paths=["src/secret.py"])
        actual_stat = Path.stat

        def denied_stat(path, *args, **kwargs):
            if path == target:
                raise PermissionError("Fixture denies scope inspection")
            return actual_stat(path, *args, **kwargs)

        with mock.patch.object(Path, "stat", new=denied_stat):
            with self.assertRaisesRegex(ValueError, "Cannot inspect planning scope"):
                self.plan()

    def test_failed_blocked_cancelled_dependencies_never_unlock(self):
        for status in ("failed", "blocked", "cancelled", "running", "pending"):
            with self.subTest(status=status):
                self.state["work_items"] = []
                self.item("parent", status=status)
                self.item("child", dependencies=["parent"])
                self.assertNotIn("child", self.plan()["runnable"])
                self.assertIn(status, self.plan()["waiting"]["child"])

    def test_inactive_milestone_and_terminal_task_do_not_dispatch(self):
        self.item("future", milestone_id="M2")
        self.assertEqual(self.plan()["runnable"], [])
        self.item("ready")
        for status in ("completed", "cancelled"):
            self.state["status"] = status
            self.assertEqual(self.plan()["runnable"], [])

    def test_final_review_verification_barrier_and_preparation(self):
        writer = self.item("writer", write_paths=["src/app.py"])
        self.item("review", role="harness-reviewer", read_paths=["src"])
        self.item("verify", role="verifier", read_paths=["src"])
        self.item("prep", role="verification-preparation", read_paths=["tests"])
        plan = self.plan()
        self.assertEqual(plan["runnable"], ["writer", "prep"])
        self.assertIn("awaits", plan["waiting"]["review"])
        writer["status"] = "completed"
        self.assertEqual(self.plan()["runnable"], ["review", "verify", "prep"])
        writer["status"] = "failed"
        self.assertNotIn("verify", self.plan()["runnable"])

    def test_config_cap_and_runtime_slots_are_both_respected(self):
        self.state["max_workers"] = 8
        for idx in range(10):
            self.item(f"w{idx}", status="running" if idx < 2 else "pending")
        self.assertEqual(len(self.plan()["runnable"]), 6)
        self.assertEqual(len(self.plan(2)["runnable"]), 2)
        self.assertEqual(self.plan(0)["runnable"], [])
        self.assertEqual(len(self.plan(99)["runnable"]), 6)
        for invalid in (-1, True, 1.5):
            with self.assertRaises(ValueError):
                self.plan(invalid)
        self.state["max_workers"] = 1
        self.assertEqual(self.plan()["runnable"], [])

    def test_duplicate_unknown_and_cyclic_graphs_are_rejected(self):
        self.item("same")
        self.item("same")
        self.assert_invalid("Duplicate")
        self.state["work_items"] = []
        self.item("one", dependencies=["missing"])
        self.assert_invalid("unknown dependency")
        self.state["work_items"] = []
        self.item("one", dependencies=["two"])
        self.item("two", dependencies=["one"])
        self.assert_invalid("acyclic")

    def test_invalid_paths_ids_milestones_and_limits_are_rejected(self):
        item = self.item("valid")
        for path in ("/absolute", "../escape", "src/../x", "./src", "src//x", "src/", "C:/x", "a\\b", "~/.x", "src/*", ".", "bad\0x"):
            with self.subTest(path=repr(path)):
                item["write_paths"] = [path]
                self.assert_invalid("normalized")
        item["write_paths"] = []
        for work_id in ("../x", "x" * 65, ""):
            item["id"] = work_id
            self.assert_invalid(".id")
        item["id"] = "valid"
        item["milestone_id"] = "M99"
        self.assert_invalid("milestone_id")
        item["milestone_id"] = "M1"
        for cap in (0, 9, True, 2.5):
            self.state["max_workers"] = cap
            self.assert_invalid("max_workers")
        self.state["max_workers"] = 3
        item["priority"] = 101
        self.assert_invalid("priority")
        item.pop("priority")
        self.state["work_items"] = [dict(item, id=f"w{i}") for i in range(129)]
        self.assert_invalid("at most 128")

    def test_final_roles_cannot_own_writes(self):
        self.item("review", role=" Reviewer ", write_paths=["src"])
        self.assert_invalid("read-only")

    def test_running_final_check_cannot_overlap_reopened_writer(self):
        self.item("writer", write_paths=["src"])
        self.item("review", role="reviewer", status="running")
        with self.assertRaisesRegex(ValueError, "Running final reviewer"):
            self.plan()

    def test_legacy_checkpoint_needs_no_migration_or_workspace(self):
        self.state.pop("work_items")
        self.state.pop("workspace")
        valid, errors = task_state.validate_task_state(self.state)
        self.assertTrue(valid, errors)
        self.assertEqual(self.plan()["runnable"], [])
        self.assertEqual(self.plan()["max_workers"], 3)

    def test_nonempty_plan_requires_an_actual_absolute_workspace(self):
        self.item("work")
        self.state["workspace"] = "."
        with self.assertRaisesRegex(ValueError, "absolute workspace"):
            self.plan()
        self.state["workspace"] = str(self.workspace / "absent")
        with self.assertRaisesRegex(ValueError, "resolve"):
            self.plan()

    def test_dispatch_cli_is_read_only_and_reports_waiting_reasons(self):
        self.item("one")
        self.item("two", dependencies=["one"])
        path = task_state.save_task_state(self.workspace, self.state)
        before = path.read_bytes()
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "task_state.py"), "dispatch-plan", "--task-id", "parallel-test",
             "--workspace", str(self.workspace), "--available-slots", "1"], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        plan = json.loads(result.stdout)
        self.assertEqual(plan["runnable"], ["one"])
        self.assertIn("Dependencies", plan["waiting"]["two"])
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(sorted(p.name for p in path.parent.iterdir()), ["state.json", "state.json.lock"])


if __name__ == "__main__":
    unittest.main()
