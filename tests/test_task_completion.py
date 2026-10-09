#!/usr/bin/env python3
"""Completion must account for the user's requirements and recorded checks."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


_FIXTURE_SPEC = importlib.util.spec_from_file_location(
    "verification_gate_fixtures", Path(__file__).with_name("test_verification_gate.py")
)
assert _FIXTURE_SPEC is not None and _FIXTURE_SPEC.loader is not None
_fixtures = importlib.util.module_from_spec(_FIXTURE_SPEC)
_FIXTURE_SPEC.loader.exec_module(_fixtures)


class TaskCompletionTests(unittest.TestCase):
    def test_failed_check_before_formatter_remains_outstanding(self):
        self.register()
        self.command(3, "python3 -m pytest -q && black .", error="exit code 1")
        self.command(4, "npm test")
        self.assertContinues(self.finish())
        self.command(6, "python3 -m pytest -q && black .")
        self.command(7, "npm test")
        self.assertAllows(self.finish(rows=[self.row(evidence=[7])], step=8))

    def test_failed_mixed_formatter_static_check_remains_outstanding(self):
        self.register()
        self.command(3, "black . && ruff check .", error="exit code 1")
        self.command(4, "npm test")
        self.assertContinues(self.finish())
        self.command(6, "black . && ruff check .")
        self.command(7, "npm test")
        self.assertAllows(self.finish(rows=[self.row(evidence=[7])], step=8))

    def test_unresolved_failure_survives_bounded_evidence_history(self):
        self.register()
        self.command(3, "npm test", error="exit code 1")
        self.write(step=4)
        for step in range(5, 134):
            self.command(step, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[133])], step=134))
        self.command(135, "npm test")
        self.assertAllows(self.finish(rows=[self.row(evidence=[135])], step=136))

    # Reuse the hook process fixtures without inheriting their test cases.
    call = _fixtures.VerificationGateTests.call
    post = _fixtures.VerificationGateTests.post
    stop = _fixtures.VerificationGateTests.stop
    write = _fixtures.VerificationGateTests.write
    command = _fixtures.VerificationGateTests.command
    transcript = _fixtures.VerificationGateTests.transcript
    user_record = staticmethod(_fixtures.VerificationGateTests.user_record)
    model_record = staticmethod(_fixtures.VerificationGateTests.model_record)
    grounded_stop = _fixtures.VerificationGateTests.grounded_stop

    def setUp(self) -> None:
        _fixtures.VerificationGateTests.setUp(self)
        self.request = "Fix add, subtract, multiply, and divide."
        self.records = [self.user_record(self.request)]
        self.path = self.transcript(*self.records)
        self.common["transcriptPath"] = str(self.path)

    @staticmethod
    def requirement(identifier="AC-1", request="add", verification="behavioral"):
        return {
            "id": identifier,
            "request": request,
            "acceptance": "Requested operation returns the expected result.",
            "verification": verification,
        }

    def register(self, requirements=None, step=2, **overrides):
        contract = {
            "version": 1,
            "requirements": requirements if requirements is not None else [self.requirement()],
            **overrides,
        }
        content = json.dumps(contract)
        target = self.artifacts / "harness-task-contract.json"
        target.write_text(content, encoding="utf-8")
        return self.post(step, "write_to_file", {
            "IsArtifact": True, "TargetFile": str(target), "CodeContent": content,
        })

    @staticmethod
    def row(identifier="AC-1", status="passed", evidence=None, **overrides):
        return {
            "id": identifier,
            "status": status,
            "evidenceSteps": [4] if evidence is None else evidence,
            **overrides,
        }

    def finish(self, status="complete", rows=None, step=5, execution=0, prefix=""):
        result = {"status": status, "requirements": rows if rows is not None else [self.row()]}
        content = prefix + "HARNESS_RESULT: " + json.dumps(result)
        return self.finish_text(content, step=step, execution=execution)

    def finish_text(self, content, step=5, execution=0):
        self.path = self.transcript(*self.records, self.model_record(content, step=step))
        return self.grounded_stop(self.path, execution=execution)

    def prepared(self, requirements=None):
        self.register(requirements)
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")

    def assertContinues(self, result):
        self.assertEqual(result["decision"], "continue", result)

    def assertAllows(self, result):
        self.assertEqual(result["decision"], "allow", result)

    def test_complete_accepts_registered_requirement_and_post_write_check(self):
        self.prepared()
        self.assertAllows(self.finish())

    def test_four_requests_cannot_finish_with_only_two_rows(self):
        requirements = [self.requirement(f"AC-{i}", request)
                        for i, request in enumerate(("add", "subtract", "multiply", "divide"), 1)]
        self.prepared(requirements)
        self.assertContinues(self.finish(rows=[self.row("AC-1"), self.row("AC-2")]))

    def test_four_requests_complete_with_four_verified_rows(self):
        requirements = [self.requirement(f"AC-{i}", request)
                        for i, request in enumerate(("add", "subtract", "multiply", "divide"), 1)]
        self.prepared(requirements)
        self.assertAllows(self.finish(rows=[self.row(f"AC-{i}") for i in range(1, 5)]))

    def test_missing_contract_cannot_report_complete(self):
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertContinues(self.finish())

    def test_missing_report_cannot_finish_normal_workspace_work(self):
        self.prepared()
        self.assertContinues(self.finish_text("Implemented everything; all tests passed."))

    def test_missing_report_remains_blocked_on_repeated_stop(self):
        self.prepared()
        self.assertContinues(self.finish_text("Done."))
        self.assertContinues(self.finish_text("Done.", execution=1))
        self.assertContinues(self.finish_text("Done.", execution=2))

    def test_duplicate_and_unknown_requirement_rows_are_rejected(self):
        self.prepared()
        for rows in ([self.row(), self.row()], [self.row("AC-99")]):
            with self.subTest(rows=rows):
                self.assertContinues(self.finish(rows=rows))

    def test_complete_rejects_nonpassed_requirement(self):
        self.prepared()
        for status in ("failed", "blocked", "unverified"):
            with self.subTest(status=status):
                self.assertContinues(self.finish(rows=[self.row(status=status, evidence=[], reason="Not verified.")]))

    def test_invented_evidence_step_is_rejected(self):
        self.prepared()
        self.assertContinues(self.finish(rows=[self.row(evidence=[999])]))

    def test_prewrite_evidence_is_rejected(self):
        self.register()
        self.command(3, "python3 -m pytest -q")
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[3])], step=6))

    def test_static_check_cannot_satisfy_behavioral_requirement(self):
        self.register()
        self.write(step=3, target=self.workspace / "README.md")
        self.command(4, "git diff --check")
        self.assertContinues(self.finish())

    def test_static_requirement_accepts_recorded_static_check(self):
        self.register([self.requirement(verification="static")])
        self.write(step=3, target=self.workspace / "README.md")
        self.command(4, "git diff --check")
        self.assertAllows(self.finish())

    def test_failed_evidence_step_is_rejected_even_with_later_success(self):
        self.register()
        self.write(step=3)
        self.command(4, "python3 -m pytest -q", error="exit code 1")
        self.command(5, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[4])], step=6))

    def test_outstanding_failed_check_prevents_complete(self):
        self.prepared()
        self.command(5, "npm test", error="exit code 1")
        self.assertContinues(self.finish(step=6))

    def test_same_failed_check_successfully_rerun_allows_complete(self):
        self.prepared()
        self.command(5, "npm test", error="exit code 1")
        self.command(6, "npm test")
        self.assertAllows(self.finish(rows=[self.row(evidence=[6])], step=7))

    def test_check_failure_before_latest_write_does_not_poison_fixed_work(self):
        self.register()
        self.command(3, "npm test", error="exit code 1")
        self.write(step=4)
        self.command(5, "npm test")
        self.assertAllows(self.finish(rows=[self.row(evidence=[5])], step=6))

    def test_no_check_waiver_cannot_support_complete(self):
        self.register()
        self.write(step=3)
        self.command(4, "printf '%s\\n' 'HARNESS_NO_RUNNABLE_CHECK: repository has no checks'")
        self.assertContinues(self.finish())

    def test_truthful_partial_or_blocked_can_finish_without_checks(self):
        self.register()
        self.write(step=3)
        for status in ("partial", "blocked"):
            with self.subTest(status=status):
                rows = [self.row(status="unverified", evidence=[], reason="No runnable behavioral check is available.")]
                self.assertAllows(self.finish(status=status, rows=rows))

    def test_partial_requires_reason_for_every_unpassed_requirement(self):
        self.prepared()
        self.assertContinues(self.finish(status="partial", rows=[self.row(status="unverified", evidence=[])]))

    def test_partial_cannot_hide_unverified_passed_requirement(self):
        self.prepared()
        rows = [self.row(evidence=[999])]
        self.assertContinues(self.finish(status="partial", rows=rows))

    def test_contract_registered_after_write_cannot_report_complete(self):
        self.write(step=2)
        self.register(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertContinues(self.finish())

    def test_late_contract_allows_truthful_partial_recovery(self):
        self.write(step=2)
        self.register(step=3)
        rows = [self.row(status="unverified", evidence=[], reason="Contract was registered after the change.")]
        self.assertAllows(self.finish(status="partial", rows=rows))

    def test_contract_requirement_must_quote_current_user_request(self):
        self.prepared([self.requirement(request="Deploy to production")])
        self.assertContinues(self.finish())

    def test_contract_cannot_be_replaced_to_remove_unfinished_requirement(self):
        self.register([self.requirement(), self.requirement("AC-2", "subtract")])
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.register([self.requirement()], step=5)
        self.assertContinues(self.finish(step=6))

    def test_invalid_contract_replacement_invalidates_completion(self):
        self.prepared()
        self.register([], step=5)
        self.assertContinues(self.finish(step=6))

    def test_multiple_result_markers_are_rejected(self):
        self.prepared()
        report = "HARNESS_RESULT: " + json.dumps({"status": "complete", "requirements": [self.row()]})
        self.assertContinues(self.finish_text(report + "\n" + report))

    def test_new_user_turn_cannot_reuse_previous_contract_or_evidence(self):
        self.prepared()
        self.assertAllows(self.finish())
        self.records.append(self.user_record("Fix subtract.", step=6))
        self.transcript(*self.records)
        self.write(step=7)
        self.command(8, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[8])], step=9))

    def test_new_user_turn_can_register_fresh_contract(self):
        self.prepared()
        self.assertAllows(self.finish())
        self.records.append(self.user_record("Fix subtract.", step=6))
        self.transcript(*self.records)
        self.register([self.requirement(request="subtract")], step=7)
        self.write(step=8)
        self.command(9, "python3 -m pytest -q")
        self.assertAllows(self.finish(rows=[self.row(evidence=[9])], step=10))

    def test_unknown_transcript_schema_keeps_legacy_fail_open_behavior(self):
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        path = self.transcript({"role": "user", "content": self.request}, {"role": "assistant", "content": "Done."})
        self.assertAllows(self.grounded_stop(path))

    def test_explicit_inline_fast_path_without_contract_uses_existing_gate(self):
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertAllows(self.finish_text("Harness: IMPLEMENT; mode: inline-fast-path; passed: focused check; failed/skipped: none"))

    def test_malformed_report_does_not_reuse_prior_valid_report(self):
        self.prepared()
        self.assertAllows(self.finish())
        self.assertContinues(self.finish_text('HARNESS_RESULT: {"status":', step=6))

    def test_report_evidence_steps_must_be_integer_step_numbers(self):
        self.prepared()
        for evidence in (["4"], [True], [4.0], [-1], []):
            with self.subTest(evidence=evidence):
                self.assertContinues(self.finish(rows=[self.row(evidence=evidence)]))

    def test_unknown_report_status_is_rejected(self):
        self.prepared()
        self.assertContinues(self.finish(status="success"))
        self.assertContinues(self.finish(rows=[self.row(status="done")]))

    def test_mentioning_inline_mode_does_not_create_exception(self):
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertContinues(self.finish_text("I did not use mode: inline-fast-path.\nHarness: IMPLEMENT; passed: focused check"))

    def test_new_user_read_only_turn_does_not_inherit_old_mutation(self):
        self.prepared()
        self.assertAllows(self.finish())
        self.records.append(self.user_record("Explain the change.", step=6))
        self.assertAllows(self.finish_text("The operation handles its input.", step=7))

    def test_evidence_after_final_response_is_rejected(self):
        self.register()
        self.write(step=3)
        self.command(6, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[6])], step=5))

    def test_evidence_at_final_response_step_is_rejected(self):
        self.prepared()
        self.assertContinues(self.finish(step=4))

    def test_boolean_contract_version_is_rejected(self):
        self.register(version=True)
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertContinues(self.finish())

    def test_nonlist_contract_inventory_is_rejected(self):
        self.register(requirements={"AC-1": self.requirement()})
        self.write(step=3)
        self.command(4, "python3 -m pytest -q")
        self.assertContinues(self.finish())

    def test_invalid_initial_contract_can_be_repaired_before_implementation(self):
        self.register(version="1")
        self.register(step=3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.assertAllows(self.finish(rows=[self.row(evidence=[5])], step=6))

    def test_original_contract_restoration_recovers_rejected_replacement(self):
        self.prepared()
        self.register([], step=5)
        self.assertContinues(self.finish(step=6))
        self.register(step=7)
        self.assertAllows(self.finish(step=8))

    def test_acceptance_cannot_be_weakened_with_same_requirement_id(self):
        self.prepared()
        weakened = self.requirement()
        weakened["acceptance"] = "Only build output exists."
        self.register([weakened], step=5)
        self.assertContinues(self.finish(step=6))

    def test_verification_cannot_be_downgraded_with_same_requirement_id(self):
        self.prepared()
        self.register([self.requirement(verification="static")], step=5)
        self.assertContinues(self.finish(step=6))

    def test_failed_check_persists_across_unrelated_write_and_check(self):
        self.register()
        self.command(3, "npm test", error="exit code 1")
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[5])], step=6))

    def test_failed_mutation_and_test_chain_cannot_be_hidden_by_other_check(self):
        self.register()
        self.command(3, "black . && python3 -m pytest -q", error="exit code 1")
        self.command(4, "npm test")
        self.assertContinues(self.finish())

    def test_truthful_partial_after_failures_can_finish(self):
        self.register()
        self.command(3, "npm test", error="exit code 1")
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        rows = [self.row(status="failed", evidence=[], reason="npm test failed and has not passed again after the change.")]
        self.assertAllows(self.finish(status="partial", rows=rows, step=6))

    def test_truthful_partial_after_failed_mutation_test_chain_can_finish(self):
        self.register()
        self.command(3, "black . && python3 -m pytest -q", error="exit code 1")
        self.command(4, "npm test")
        rows = [self.row(status="failed", evidence=[], reason="The formatting and behavioral test chain failed; completion remains unverified.")]
        self.assertAllows(self.finish(status="partial", rows=rows))

    def test_read_only_explanation_can_mention_result_marker(self):
        self.assertAllows(self.finish_text("The HARNESS_RESULT marker carries the structured completion status."))

    def test_read_only_explanation_can_show_fenced_result_example(self):
        example = {"status": "complete", "requirements": [self.row()]}
        content = "Example report syntax:\n```text\nHARNESS_RESULT: " + json.dumps(example) + "\n```"
        self.assertAllows(self.finish_text(content))

    def test_active_contract_cannot_use_fenced_result_example_as_report(self):
        self.prepared()
        example = {"status": "complete", "requirements": [self.row()]}
        content = "Example report syntax:\n```text\nHARNESS_RESULT: " + json.dumps(example) + "\n```"
        self.assertContinues(self.finish_text(content))

    def test_contract_cannot_be_bypassed_with_inline_marker(self):
        self.prepared()
        self.assertContinues(self.finish_text("Harness: IMPLEMENT; mode: inline-fast-path; passed: all; failed/skipped: none"))


if __name__ == "__main__":
    unittest.main()
