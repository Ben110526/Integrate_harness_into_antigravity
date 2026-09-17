import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
SKILLS_DIR = ROOT / "plugin" / "codex-claude-harness" / "skills"
HARNESS_RUN = SKILLS_DIR / "harness-run" / "SKILL.md"
HARNESS_PLAN = SKILLS_DIR / "harness-plan" / "SKILL.md"
HARNESS_IMPLEMENT = SKILLS_DIR / "harness-implement" / "SKILL.md"
HARNESS_SHIP = SKILLS_DIR / "harness-ship" / "SKILL.md"


class HarnessRunContractTests(unittest.TestCase):
    """Verify that the M2 milestone coordinator contract (harness-run) is sound,

    well-integrated with existing skills, and adheres to strict safety boundaries.
    """

    def setUp(self) -> None:
        self.assertTrue(HARNESS_RUN.exists(), "harness-run/SKILL.md must exist")
        self.run_text = HARNESS_RUN.read_text(encoding="utf-8")
        self.plan_text = HARNESS_PLAN.read_text(encoding="utf-8")
        self.implement_text = HARNESS_IMPLEMENT.read_text(encoding="utf-8")
        self.ship_text = HARNESS_SHIP.read_text(encoding="utf-8")

    def test_frontmatter_metadata(self) -> None:
        """harness-run skill frontmatter must declare valid name and description."""
        self.assertTrue(self.run_text.startswith("---\n"))
        parts = self.run_text.split("---", 2)
        self.assertGreaterEqual(len(parts), 3)
        frontmatter = parts[1]
        self.assertIn("name: harness-run", frontmatter)
        self.assertIn("description:", frontmatter)

    def test_brief_six_fields_contract(self) -> None:
        """Brief must mandate all six fundamental fields to prevent underspecification."""
        required_fields = (
            "real problem",
            "current behavior",
            "desired behavior",
            "scope/non-goals",
            "constraints",
            "completion evidence",
        )
        for field in required_fields:
            self.assertIn(field, self.run_text, f"harness-run must require brief field '{field}'")

    def test_acceptance_ledger_rules(self) -> None:
        """AC ledger must mandate stable AC-* IDs and forbid activity-only claims."""
        self.assertIn("AC-*", self.run_text)
        self.assertIn("observable outcome", self.run_text)
        self.assertIn("requirement source", self.run_text)
        self.assertIn("planned check", self.run_text)
        # Forbid activity-only criteria
        self.assertIn('Do not substitute\n   activities such as "edited code" for outcomes', self.run_text)
        # Preserve superseded ACs
        self.assertIn("Preserve superseded ACs with the\n   user's change and reason", self.run_text)

    def test_behavior_map_structure(self) -> None:
        """Task-scoped behavior map must trace entry point to side effects and tests."""
        map_chain = "entry point → call sites → core behavior → outputs\n   or side effects → tests"
        self.assertIn(map_chain, self.run_text)
        self.assertIn("cheapest discriminating check", self.run_text)

    def test_single_coordinator_and_native_first(self) -> None:
        """Single coordinator rule prevents nested/conflicting orchestrator loops."""
        self.assertIn("Keep exactly one coordinator", self.run_text)
        self.assertIn("The main agent coordinates by default", self.run_text)
        self.assertIn("overlapping native/custom", self.run_text)
        self.assertIn("agent tree", self.run_text)

    def test_worker_assignment_is_self_contained(self) -> None:
        """Subagent assignments must be complete and standalone without relying on prior chat history."""
        assignment_elements = (
            "goal",
            "AC IDs",
            "workspace",
            "owned files",
            "dependencies/invariants",
            "safe checks",
            "expected output",
        )
        for elem in assignment_elements:
            self.assertIn(elem, self.run_text, f"Worker assignment must include '{elem}'")
        # Must have fallback if send_message / reuse is unsupported
        self.assertIn("Otherwise invoke\na new worker from the same self-contained handoff", self.run_text)

    def test_autonomous_milestone_continuation_without_early_stop(self) -> None:
        """Coordinator must dispatch next work within active turn rather than stopping at milestone boundaries."""
        self.assertIn("dispatch the next ready work with a tool call within the active\n   turn", self.run_text)
        self.assertIn("Do not issue a final response at a passed milestone while ready,\n   authorized work remains", self.run_text)
        self.assertIn("A progress sentence or stored `next_action` cannot\n   wake a runtime after it stops", self.run_text)

    def test_cancellation_and_material_decision_safeguards(self) -> None:
        """Coordinator must respect cancellation, missing authority, and material user decisions."""
        self.assertIn("Honor user cancellation and resource/runtime\n   limits", self.run_text)
        self.assertIn("Never force continuation unconditionally", self.run_text)
        self.assertIn("harness-clarify", self.run_text)

    def test_inter_skill_linkage(self) -> None:
        """harness-plan, harness-implement, and harness-ship must cross-reference harness-run."""
        self.assertIn("[harness-run](../harness-run/SKILL.md)", self.plan_text)
        self.assertIn("[harness-run](../harness-run/SKILL.md)", self.implement_text)
        self.assertIn("[harness-run](../harness-run/SKILL.md)", self.ship_text)

    def test_task_state_engine_contract(self) -> None:
        """harness-run must reference task_state.py and schema, not contain contradictory prohibition."""
        self.assertNotIn("Do not create `.harness/tasks/**`", self.run_text)
        self.assertIn("scripts/task_state.py", self.run_text)
        self.assertIn(".harness/tasks/<task-id>/state.json", self.run_text)
        self.assertIn("task-state.schema.json", self.run_text)


class MilestoneLedgerValidationHelperTests(unittest.TestCase):
    """Test algorithmic validation of AC ledgers and worker handoffs to ensure

    multi-milestone coordination logic can programmatically catch malformed state.
    """

    def validate_ac_ledger(self, ledger: list[dict]) -> tuple[bool, list[str]]:
        errors = []
        seen_ids = set()
        for idx, entry in enumerate(ledger):
            ac_id = entry.get("id", "")
            if not re.fullmatch(r"AC-\d+", ac_id):
                errors.append(f"Entry {idx}: Invalid AC ID '{ac_id}'")
            if ac_id in seen_ids:
                errors.append(f"Entry {idx}: Duplicate AC ID '{ac_id}'")
            seen_ids.add(ac_id)
            if not entry.get("outcome"):
                errors.append(f"Entry {idx} ({ac_id}): Missing observable outcome")
            if not entry.get("requirement_source"):
                errors.append(f"Entry {idx} ({ac_id}): Missing requirement source")
            if not entry.get("planned_check"):
                errors.append(f"Entry {idx} ({ac_id}): Missing planned check")
            status = entry.get("status")
            if status not in {"pending", "in_progress", "verified", "superseded"}:
                errors.append(f"Entry {idx} ({ac_id}): Invalid status '{status}'")
            if status == "superseded" and not entry.get("superseded_reason"):
                errors.append(f"Entry {idx} ({ac_id}): Superseded AC must provide a reason")
        return len(errors) == 0, errors

    def test_valid_ledger(self) -> None:
        ledger = [
            {
                "id": "AC-1",
                "outcome": "Verification gate strips Python options safely",
                "requirement_source": "User M1 spec",
                "planned_check": "python3 -m unittest tests/test_verification_gate.py",
                "status": "verified",
            },
            {
                "id": "AC-2",
                "outcome": "Old requirement replaced",
                "requirement_source": "User prompt update",
                "planned_check": "N/A",
                "status": "superseded",
                "superseded_reason": "Scope adjusted by user in turn 3",
            },
        ]
        valid, errors = self.validate_ac_ledger(ledger)
        self.assertTrue(valid, errors)

    def test_invalid_ledger_detects_duplicates_and_missing_fields(self) -> None:
        invalid_ledger = [
            {
                "id": "AC-1",
                "outcome": "",  # missing outcome
                "requirement_source": "spec",
                "planned_check": "test",
                "status": "pending",
            },
            {
                "id": "AC-1",  # duplicate ID
                "outcome": "outcome",
                "requirement_source": "spec",
                "planned_check": "test",
                "status": "unknown_status",  # invalid status
            },
            {
                "id": "AC-2",
                "outcome": "outcome",
                "requirement_source": "spec",
                "planned_check": "test",
                "status": "superseded",
                # missing superseded_reason
            },
        ]
        valid, errors = self.validate_ac_ledger(invalid_ledger)
        self.assertFalse(valid)
        self.assertEqual(len(errors), 4)


if __name__ == "__main__":
    unittest.main()
