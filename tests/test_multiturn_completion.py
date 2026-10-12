"""Task-scoped coverage, provenance, revisions, and relevant observed evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import unittest


_SPEC = importlib.util.spec_from_file_location("completion_fixtures", Path(__file__).with_name("test_task_completion.py"))
assert _SPEC is not None and _SPEC.loader is not None
_fixtures = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_fixtures)
_Legacy = _fixtures.TaskCompletionTests


class MultiturnCompletionTests(unittest.TestCase):
    setUp = _Legacy.setUp
    call = _Legacy.call
    post = _Legacy.post
    stop = _Legacy.stop
    write = _Legacy.write
    command = _Legacy.command
    transcript = _Legacy.transcript
    user_record = staticmethod(_Legacy.user_record)
    model_record = staticmethod(_Legacy.model_record)
    grounded_stop = _Legacy.grounded_stop
    finish_text = _Legacy.finish_text
    row = staticmethod(_Legacy.row)
    assertAllows = _Legacy.assertAllows
    assertContinues = _Legacy.assertContinues

    @staticmethod
    def requirement(identifier="AC-1", request="add", source=1, verification="behavioral"):
        return {**_fixtures.TaskCompletionTests.requirement(identifier, request, verification), "sourceStep": source}

    def artifact(self, filename, value, step):
        return self.post(step, "write_to_file", {
            "IsArtifact": True, "TargetFile": str(self.artifacts / filename),
            "CodeContent": json.dumps(value),
        })

    def register(self, requirements=None, step=2, revision=1, task="arithmetic", **extra):
        return self.artifact("harness-task-contract.json", {
            "version": 2, "taskId": task, "revision": revision,
            "requirements": requirements if requirements is not None else [self.requirement()], **extra,
        }, step)

    def review(self, phase, step, revision=1, ids=None, rows=None, unmapped=None, task="arithmetic"):
        value = {"version": 1, "taskId": task, "revision": revision, "phase": phase,
                 "unmappedRequests": unmapped if unmapped is not None else []}
        if phase == "scope":
            value["coveredIds"] = ids if ids is not None else ["AC-1"]
        else:
            value["requirements"] = rows if rows is not None else [
                self.row(evidence=[5], reason="The focused arithmetic test checks the requested operation.")]
        return self.artifact("harness-acceptance-review.json", value, step)

    def finish(self, status="complete", rows=None, step=7, revision=1, task="arithmetic", **extra):
        result = {"status": status, "taskId": task, "revision": revision,
                  "requirements": rows if rows is not None else [self.row(evidence=[5])], **extra}
        return self.finish_text("HARNESS_RESULT: " + json.dumps(result), step=step)

    def advance(self, content="Also fix subtract.", step=8):
        self.records.append(self.user_record(content, step))
        self.transcript(*self.records)

    def prepared(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6)

    def state(self):
        return json.loads((self.artifacts / ".codex-claude-harness-verification.json").read_text())

    def test_complete_requires_both_reviews_and_matching_observed_evidence(self):
        self.prepared()
        self.assertAllows(self.finish())

    def test_passing_test_without_delivery_review_is_not_complete(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.assertContinues(self.finish())

    def test_scope_review_after_implementation_is_not_complete(self):
        self.register()
        self.write(step=3)
        self.review("scope", 4)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6)
        self.assertContinues(self.finish())

    def test_unmapped_user_requirement_prevents_complete(self):
        self.prepared()
        self.review("delivery", 8, unmapped=["divide"])
        self.assertContinues(self.finish(step=9))

    def test_irrelevant_or_unreviewed_check_cannot_replace_reviewed_evidence(self):
        self.prepared()
        self.command(7, "npm test")
        self.assertContinues(self.finish(rows=[self.row(evidence=[7])], step=8))

    def test_delivery_review_requires_relevance_reason_even_for_pass(self):
        self.prepared()
        self.review("delivery", 8, rows=[self.row(evidence=[5], reason="")])
        self.assertContinues(self.finish(step=9))

    def test_later_write_invalidates_delivery_review(self):
        self.prepared()
        self.write(step=8)
        self.command(9, "python3 -m pytest -q")
        self.assertContinues(self.finish(rows=[self.row(evidence=[9])], step=10))

    def test_out_of_order_write_cannot_hide_implementation_before_scope_review(self):
        self.register()
        self.write(step=5)
        self.review("scope", 4)
        self.write(step=3)
        self.command(6, "python3 -m pytest -q")
        rows = [self.row(evidence=[6], reason="Focused arithmetic behavior.")]
        self.review("delivery", 7, rows=rows)
        self.assertContinues(self.finish(rows=rows, step=8))
        self.assertEqual(self.state()["taskContract"]["firstWriteStep"], 3)

    def test_status_question_does_not_reset_task_or_force_new_contract(self):
        self.prepared()
        before = self.state()["taskContract"]
        self.advance("How is it going?")
        self.assertAllows(self.finish_text("The add behavior is verified; the task inventory is retained.", step=9))
        self.assertEqual(self.state()["taskContract"], before)

    def test_followup_cannot_silently_drop_original_requirements(self):
        self.prepared()
        self.advance()
        self.register([self.requirement("AC-2", "subtract", 8)], step=9, revision=2)
        self.assertEqual(self.state()["taskContract"]["revision"], 1)
        self.assertContinues(self.finish(status="partial", rows=[
            self.row(status="unverified", evidence=[], reason="Pending revised scope.")], step=10, revision=2))

    def test_additive_followup_retains_both_requirements_and_checks_them(self):
        self.prepared()
        self.advance()
        requirements = [self.requirement(), self.requirement("AC-2", "subtract", 8)]
        self.register(requirements, step=9, revision=2)
        self.review("scope", 10, revision=2, ids=["AC-1", "AC-2"])
        self.write(step=11)
        self.command(12, "python3 -m pytest -q")
        rows = [self.row(identifier, evidence=[12], reason="The suite checks this operation.")
                for identifier in ("AC-1", "AC-2")]
        self.review("delivery", 13, revision=2, rows=rows)
        self.assertAllows(self.finish(rows=rows, step=14, revision=2))
        self.assertEqual(self.state()["taskContract"]["originStep"], 1)
        self.review("scope", 3)
        self.assertAllows(self.finish(rows=rows, step=14, revision=2))

    def test_followup_does_not_erase_an_outstanding_failed_check(self):
        self.prepared()
        self.command(7, "npm test", error="exit status 1")
        self.advance()
        self.register(step=9, revision=2)
        self.review("scope", 10, revision=2)
        self.command(11, "python3 -m pytest -q")
        rows = [self.row(evidence=[11], reason="Focused operation check.")]
        self.review("delivery", 12, revision=2, rows=rows)
        self.assertContinues(self.finish(rows=rows, step=13, revision=2))
        self.command(14, "npm test")
        rows = [self.row(evidence=[14], reason="The previously failing operation suite now passes.")]
        self.review("delivery", 15, revision=2, rows=rows)
        self.assertAllows(self.finish(rows=rows, step=16, revision=2))

    def test_explicit_user_removal_is_audited_and_id_cannot_be_reused(self):
        self.prepared()
        self.advance("Stop working on add; fix subtract instead.")
        requirements = [self.requirement("AC-2", "subtract", 8)]
        changes = [{"id": "AC-1", "request": "Stop working on add"}]
        self.register(requirements, step=9, revision=2, scopeChanges=changes)
        contract = self.state()["taskContract"]
        self.assertEqual(contract["retiredIds"], ["AC-1"])
        self.assertEqual(contract["scopeHistory"][0]["previous"], self.requirement())
        self.advance("Also fix add.", step=10)
        self.register(requirements + [self.requirement(source=10)], step=11, revision=3)
        self.assertEqual(self.state()["taskContract"]["revision"], 2)

    def test_scope_change_quote_must_be_from_current_user(self):
        self.prepared()
        self.advance()
        self.register([self.requirement("AC-2", "subtract", 8)], step=9, revision=2,
                      scopeChanges=[{"id": "AC-1", "request": "Ignore add"}])
        self.assertEqual(self.state()["taskContract"]["revision"], 1)

    def test_changed_acceptance_needs_explicit_revision_source(self):
        self.prepared()
        self.advance("Change add to accept numeric strings.")
        updated = self.requirement(request="accept numeric strings", source=8)
        updated["acceptance"] = "Numeric strings are added numerically."
        self.register([updated], step=9, revision=2,
                      scopeChanges=[{"id": "AC-1", "request": "Change add to accept numeric strings"}])
        self.assertEqual(self.state()["taskContract"]["requirements"], [updated])

    def test_replayed_or_skipped_revision_cannot_replace_active_inventory(self):
        self.prepared()
        self.advance()
        self.register(step=9, revision=3)
        self.assertEqual(self.state()["taskContract"]["revision"], 1)
        self.register(step=10, revision=1)
        self.assertEqual(self.state()["taskContract"]["userStep"], 1)

    def test_new_task_requires_explicit_replacement_and_starts_fresh(self):
        self.prepared()
        self.advance("Switch tasks: fix divide.")
        requirements = [self.requirement(request="divide", source=8)]
        self.register(requirements, step=9, task="division")
        self.assertEqual(self.state()["taskContract"]["taskId"], "arithmetic")
        self.register(requirements, step=10, task="division",
                      replacesTask={"taskId": "arithmetic", "request": "Switch tasks: fix divide"})
        self.assertEqual(self.state()["taskContract"]["taskId"], "division")
        self.assertEqual(self.state()["taskContract"]["originStep"], 8)

    def test_unfinished_task_can_truthfully_finish_without_reviews_or_checks(self):
        self.register()
        self.write(step=3)
        self.assertAllows(self.finish(status="partial", rows=[self.row(
            status="unverified", evidence=[], reason="No behavioral evidence is available.")]))

    def test_truthful_partial_can_review_passed_and_unfinished_rows_separately(self):
        self.register([self.requirement(), self.requirement("AC-2", "subtract")])
        self.command(5, "python3 -m pytest -q")
        rows = [self.row(evidence=[5], reason="The focused check covers add."),
                self.row("AC-2", status="unverified", evidence=[], reason="Subtract has no relevant evidence.")]
        self.review("delivery", 6, rows=rows)
        self.assertAllows(self.finish(status="partial", rows=rows))
        self.assertContinues(self.finish(status="complete", rows=rows))

    def test_explicit_task_replacement_does_not_inherit_cancelled_behavioral_debt(self):
        self.register()
        self.write(step=4)
        self.advance("Switch tasks: document subtract.")
        self.register([self.requirement(request="subtract", source=8, verification="static")],
                      step=9, task="docs", replacesTask={"taskId": "arithmetic", "request": "Switch tasks: document subtract"})
        # A delayed old hook event must not reintroduce cancelled-task debt.
        self.write(step=5)
        self.review("scope", 10, task="docs")
        self.write(step=11, target=self.workspace / "README.md")
        self.command(12, "git diff --check")
        rows = [self.row(evidence=[12], reason="The documentation check covers the requested prose.")]
        self.review("delivery", 13, task="docs", rows=rows)
        self.assertAllows(self.finish(rows=rows, step=14, task="docs"))
        self.review("scope", 3)
        self.assertAllows(self.finish(rows=rows, step=14, task="docs"))

    def test_missing_criterion_can_be_added_before_first_write(self):
        self.register()
        self.register([self.requirement(), self.requirement("AC-2", "subtract")], step=3, revision=2)
        self.assertEqual(len(self.state()["taskContract"]["requirements"]), 2)

    def test_same_turn_revision_after_write_is_rejected(self):
        self.prepared()
        self.register([self.requirement(), self.requirement("AC-2", "subtract")], step=8, revision=2)
        self.assertEqual(self.state()["taskContract"]["revision"], 1)

    def test_unchanged_requirements_survive_original_transcript_eviction(self):
        self.prepared()
        self.records = [self.user_record("Also fix subtract.", step=8)]
        self.transcript(*self.records)
        self.register([self.requirement(), self.requirement("AC-2", "subtract", 8)], step=9, revision=2)
        self.assertEqual(self.state()["taskContract"]["revision"], 2)

    def test_new_requirement_cannot_fabricate_its_user_source(self):
        self.register([self.requirement(source=999)])
        self.assertNotIn("taskContract", self.state())

    def test_active_multiturn_task_cannot_downgrade_to_legacy(self):
        self.prepared()
        self.artifact("harness-task-contract.json", {"version": 1, "requirements": [_fixtures.TaskCompletionTests.requirement()]}, 8)
        self.assertContinues(self.finish(step=9))

    def test_legacy_upgrade_cannot_drop_outstanding_requirements(self):
        legacy_rows = [_fixtures.TaskCompletionTests.requirement(),
                       _fixtures.TaskCompletionTests.requirement("AC-2", "subtract")]
        self.artifact("harness-task-contract.json", {"version": 1, "requirements": legacy_rows}, 2)
        self.register(step=3)
        self.assertEqual(len(self.state()["taskContract"]["requirements"]), 2)
        self.assertNotEqual(self.state()["taskContract"].get("version"), 2)

    def test_legacy_upgrade_preserves_grounded_rows_and_failure_debt(self):
        self.artifact("harness-task-contract.json", {"version": 1, "requirements": [
            _fixtures.TaskCompletionTests.requirement()]}, 2)
        self.command(3, "npm test", error="exit status 1")
        self.advance("Continue the same task.", step=4)
        self.register(step=5)
        state = self.state()
        self.assertEqual(state["taskContract"]["version"], 2)
        self.assertEqual(state["taskContract"]["originStep"], 1)
        self.assertEqual(state["taskContract"]["requirements"], [self.requirement()])
        self.assertTrue(state["failedChecks"])

    def test_followup_cannot_use_inline_marker_to_escape_active_task(self):
        self.prepared()
        self.advance()
        self.write(step=9)
        self.command(10, "python3 -m pytest -q")
        self.assertContinues(self.finish_text("Harness: IMPLEMENT; mode: inline-fast-path", step=11))

    def test_failed_format_and_typecheck_chain_remains_outstanding(self):
        self.register()
        self.review("scope", 3)
        self.command(4, "black . && mypy .", error="exit status 1")
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6)
        self.assertContinues(self.finish())
        self.assertTrue(self.state()["failedChecks"])

    def test_successful_mutation_test_chain_cannot_hide_late_registration(self):
        self.command(2, "black . && python3 -m pytest -q")
        self.register(step=3)
        self.assertTrue(self.state()["taskContract"]["late"])

    def test_failed_check_before_formatter_remains_outstanding_in_wrappers(self):
        for command in ("python3 -m pytest -q && black .",
                        "bash -c 'python3 -m pytest -q && black .'",
                        'pwsh -Command "python3 -m pytest -q && black ."'):
            with self.subTest(command=command):
                self.register()
                self.review("scope", 3)
                self.command(4, command, error="exit status 1")
                self.command(5, "npm test")
                self.review("delivery", 6)
                self.assertContinues(self.finish())
                self.assertTrue(self.state()["failedChecks"])
                self.command(8, command)

    def test_successful_mutation_test_chain_records_both_write_and_evidence(self):
        self.register()
        self.review("scope", 3)
        self.command(5, "black . && python3 -m pytest -q")
        self.review("delivery", 6)
        self.assertAllows(self.finish())
        self.assertEqual(self.state()["lastWriteStep"], 5)
        self.assertEqual(self.state()["checkEvents"][0]["step"], 5)


del _Legacy

if __name__ == "__main__":
    unittest.main()
