"""Task-scoped coverage, provenance, revisions, and relevant observed evidence."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch


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

    def post_before_terminal(self, step, command):
        # The native callback can arrive while the transcript ends at the previous step.
        self.call("post", {"stepIdx": step, "error": "", "cwd": str(self.workspace),
                           "toolCall": {"name": "run_command", "args": {
                               "CommandLine": command, "WaitMsBeforeAsync": 10000}}})

    def publish_terminal(self, step, exit_code, output=""):
        times = "Created At: 2026-11-12T14:08:17+07:00\nCompleted At: 2026-11-12T14:08:17+07:00\n"
        # CLI 1.5.6 repeats the timestamp pair. The exit line is outside the command output.
        content = times * 2 + f"Command exited with code {exit_code}.\n\n"
        if exit_code:
            content += ("There were sandbox errors that may or may not be related to the failure. "
                        "If you think the failure is because of running in the sandbox, you can run "
                        "the command again with `BypassSandbox` set to true to request explicit "
                        "user permission.\n\n")
        content += "Command output:\n" + output
        self.records.append({"step_index": step, "source": "MODEL", "type": "GENERIC",
                             "status": "DONE", "content": content})
        self.transcript(*self.records)

    def test_delivery_reconciles_native_command_after_callback(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        command = "python3 -m unittest -q test_private_check_name"
        self.post_before_terminal(5, command)
        pending_state = self.state()
        self.assertFalse(pending_state.get("checkEvents"))
        self.assertNotIn("test_private_check_name", json.dumps(pending_state))
        self.publish_terminal(5, 0, output="test_private_stdout")
        self.review("delivery", 6)
        self.assertAllows(self.finish())
        state = self.state()
        self.assertEqual([(row["step"], row["success"], row["behavioral"])
                          for row in state["checkEvents"]], [(5, True, True)])
        for private in ("test_private_check_name", "test_private_stdout"):
            self.assertNotIn(private, json.dumps(state))

    def test_deferred_nonzero_exit_needs_same_command_to_pass(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        command = "python3 -m unittest -q"
        self.post_before_terminal(5, command)
        self.publish_terminal(5, 1, output="Command exited with code 0.\nOK")
        self.post_before_terminal(6, "python3 -m unittest -q test_other")
        self.publish_terminal(6, 0)
        other = [self.row(evidence=[6], reason="Separate arithmetic check.")]
        self.review("delivery", 7, rows=other)
        self.assertContinues(self.finish(step=8, rows=other))
        self.assertEqual(list(self.state()["failedChecks"].values()), [5])
        self.post_before_terminal(9, command)
        self.publish_terminal(9, 0)
        rerun = [self.row(evidence=[9], reason="Reran the failing arithmetic check.")]
        self.review("delivery", 10, rows=rerun)
        self.assertAllows(self.finish(step=11, rows=rerun))
        self.assertFalse(self.state()["failedChecks"])

    def test_late_terminal_publication_cannot_verify_a_newer_edit(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        command = "python3 -m unittest -q"
        self.post_before_terminal(5, command)
        self.write(step=6)
        self.publish_terminal(5, 0)
        self.review("delivery", 7)
        self.assertContinues(self.finish(step=8))
        self.post_before_terminal(9, command)
        self.publish_terminal(9, 0)
        rows = [self.row(evidence=[9], reason="The arithmetic tests cover the latest edit.")]
        self.review("delivery", 10, rows=rows)
        self.assertAllows(self.finish(step=11, rows=rows))

    def test_stop_observes_late_failure_after_passing_delivery_review(self):
        self.prepared()
        self.post_before_terminal(7, "python3 -m unittest -q")
        self.publish_terminal(7, 1)
        self.assertContinues(self.finish(step=8))
        self.assertEqual(list(self.state()["failedChecks"].values()), [7])

    def advisory(self, **overrides):
        scripts = Path(__file__).resolve().parents[1] / "plugin" / "codex-claude-harness" / "scripts"
        result = subprocess.run(
            [sys.executable, str(scripts / "lifecycle_guard.py"), "context"],
            input=json.dumps({**self.common, "invocationNum": 1, **overrides}),
            text=True, capture_output=True, check=True,
        )
        self.assertEqual(result.stderr, "")
        return "".join(hint["ephemeralMessage"] for hint in json.loads(result.stdout).get("injectSteps", []))

    def test_preinvocation_persists_only_observed_terminal_checks(self):
        advisory = self.advisory
        initial_files = set(self.artifacts.iterdir())
        self.assertIn("behavioral=[], static=[]", advisory())
        self.assertEqual(set(self.artifacts.iterdir()), initial_files)

        self.register()
        self.review("scope", 3)
        self.write(step=4)
        self.post_before_terminal(5, "python3 -m unittest -q")
        self.assertIn("behavioral=[], static=[]", advisory())
        self.publish_terminal(5, 0)
        self.publish_terminal(6, 0)  # No run_command callback for this step.
        self.assertIn("behavioral=[5], static=[]", advisory())
        state = self.state()
        self.assertEqual([(row["step"], row["success"]) for row in state["checkEvents"]], [(5, True)])
        self.assertFalse(state.get("pendingCommands"))

        self.assertIn("behavioral=[5], static=[]", advisory())
        self.assertEqual(self.state(), state)

    def dispatch(self, step, worker, tool="invoke_subagent"):
        self.records.extend([
            self.model_record("", step - 1, tool_calls=[{"name": tool, "args": {"Prompt": "private assignment"}}]),
            {"source": "MODEL", "type": "GENERIC", "status": "DONE", "step_index": step,
             "content": "Created At: 2026-11-12T07:54:00Z\nCompleted At: 2026-11-12T07:54:00Z\n"
                        "Created the following subagent:\n" + json.dumps({"conversationId": worker})},
        ])

    def worker_message(self, step, sender, body):
        self.records.append({"source": "SYSTEM", "type": "SYSTEM_MESSAGE", "status": "DONE", "step_index": step,
                             "content": "The following is a <SYSTEM_MESSAGE> not sent by the user.\n\n"
                                        "<SYSTEM_MESSAGE>\n[Message] timestamp=2026-11-12T07:54:02Z "
                                        f"sender={sender} priority=MESSAGE_PRIORITY_HIGH content={body}\n</SYSTEM_MESSAGE>"})
        self.transcript(*self.records)

    def test_interrupted_stop_checkpoints_original_threads_without_accepting_a_handoff(self):
        self.register()
        self.command(3, "npm test", error="exit 1")
        before = self.state()
        left, right = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
        self.dispatch(5, left)
        self.dispatch(7, right)
        self.worker_message(8, left, "private handoff or question")
        failure = f'The subagent Worker with id "{right}" encountered an error and has either stopped or failed to start execution: '
        self.worker_message(9, "system", failure + "RESOURCE_EXHAUSTED (code 429): Resets in 167h6m34s.")
        self.assertAllows(self.stop(terminationReason="ERROR", fullyIdle=False))
        expected = {left: {"dispatchStep": 5, "messageStep": 8},
                    right: {"dispatchStep": 7, "interruptionStep": 9, "reason": "quota",
                            "reportedResetAt": "2026-11-19T07:00:36Z"}}
        state = self.state()
        self.assertEqual(state.pop("workerCheckpoint"), expected)
        self.assertEqual(state, before)
        self.assertIn("Interrupted assignments", self.advisory())
        self.worker_message(10, "system", failure + "read tcp operation timed out")
        self.worker_message(11, right, "private response")
        self.advisory()
        self.assertEqual(self.state()["workerCheckpoint"][right],
                         {"dispatchStep": 7, "interruptionStep": 10, "reason": "timeout", "messageStep": 11})
        self.assertNotIn("private", json.dumps(self.state()))

        self.advance("Continue this same task.", step=12)
        self.worker_message(13, right, "the prior owner can hand off during resume")
        self.assertNotIn("Interrupted assignments", self.advisory())
        self.assertEqual(self.state()["workerCheckpoint"][right]["messageStep"], 11)
        self.register(step=14, revision=2)
        self.assertEqual(self.state()["workerCheckpoint"][right]["messageStep"], 13)
        self.assertIn("Interrupted assignments", self.advisory())
        self.assertEqual(self.state()["failedChecks"], before["failedChecks"])
        self.advance("Replace with docs.", step=15)
        self.register([self.requirement(request="docs", source=15)], step=16, task="docs",
                      replacesTask={"taskId": "arithmetic", "request": "Replace with docs."})
        self.assertNotIn("workerCheckpoint", self.state())
        self.assertNotIn("Interrupted assignments", self.advisory())

    def test_recovery_requires_a_real_dispatch_and_top_level_system_error(self):
        worker = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        failure = (f'The subagent Worker with id "{worker}" encountered an error and has either stopped or '
                   'failed to start execution: RESOURCE_EXHAUSTED (code 429)')
        self.register()
        self.dispatch(5, worker, tool="run_command")
        self.worker_message(6, "system", failure)
        self.assertNotIn("Interrupted assignments", self.advisory())
        self.assertNotIn("workerCheckpoint", self.state())
        self.dispatch(8, worker)
        self.worker_message(9, worker, failure)
        self.assertNotIn("Interrupted assignments", self.advisory())
        self.assertEqual(self.state()["workerCheckpoint"], {worker: {"dispatchStep": 8, "messageStep": 9}})

    def test_checkpoint_preserves_unreadable_rows_and_rejects_an_unanchored_tail(self):
        self.register()
        worker = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.dispatch(5, worker)
        self.worker_message(6, worker, "private reply")
        path = self.artifacts / ".codex-claude-harness-verification.json"
        original = self.state()
        broken = {worker: {"dispatchStep": 5, "messageStep": "malformed", "reason": "timeout", "interruptionStep": 7}}
        path.write_text(json.dumps({**original, "workerCheckpoint": broken}))
        advisory = self.advisory()
        self.assertIn("current user step=1", advisory)
        self.assertNotIn("Interrupted assignments", advisory)
        self.assertEqual(self.state()["workerCheckpoint"], broken)
        path.write_text(json.dumps(original))
        self.transcript(*self.records[1:])  # tail lost the user who registered this scope
        self.assertEqual(self.advisory(), "")
        self.assertEqual(self.state(), original)

    def test_only_a_later_known_parent_message_offers_a_leaf_handoff_from_existing_work(self):
        parent = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
        self.write(step=3)
        self.worker_message(4, "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", "private input")
        self.assertEqual(self.advisory(parentConversationId=parent), "")
        self.worker_message(5, parent, "private follow-up")
        message = self.advisory(parentConversationId=parent)
        self.assertIn("Return the missing handoff", message)
        self.assertNotIn("private", message)
        self.assertNotIn("MAIN non-inline", message)

    def test_complete_requires_both_reviews_and_matching_observed_evidence(self):
        self.prepared()
        self.assertAllows(self.finish())

    def test_worker_check_in_shared_workspace_cannot_complete_coordinator_contract(self):
        self.register()
        self.review("scope", 3)
        worker_dir = self.base / "worker-artifacts"
        worker_context = {
            "conversationId": "implementer",
            "parentConversationId": self.common["conversationId"],
            "artifactDirectoryPath": str(worker_dir),
        }
        check = "python3 -m pytest -q"
        with patch.object(self, "artifacts", worker_dir), patch.dict(self.common, worker_context):
            assignment = self.user_record("Implement the assigned add operation in app.py.")
            self.common["transcriptPath"] = str(self.transcript(assignment))
            self.write(step=4)
            self.command(5, check)
            report = self.model_record("Changed app.py. The arithmetic tests passed at step 5.", step=6)
            self.assertAllows(self.grounded_stop(self.transcript(assignment, report)))
            self.assertNotIn("taskContract", self.state())
            self.assertEqual(self.state()["checkEvents"][-1]["step"], 5)

        self.assertFalse(self.state().get("checkEvents"))
        worker_rows = [self.row(evidence=[5], reason="The worker reported successful arithmetic tests.")]
        self.review("delivery", 6, rows=worker_rows)
        self.assertContinues(self.finish(rows=worker_rows))
        self.assertIn("delivery", self.state()["acceptanceReviewErrors"])

        self.command(8, check)
        rows = [self.row(evidence=[8], reason="The coordinator reran the arithmetic tests after handoff.")]
        self.review("delivery", 9, rows=rows)
        self.assertAllows(self.finish(step=10, rows=rows))

    def test_legacy_cached_success_cannot_back_review_or_complete_after_upgrade(self):
        self.prepared()
        path = self.artifacts / ".codex-claude-harness-verification.json"
        state = self.state()
        state.pop("commandEvidenceVersion")
        path.write_text(json.dumps(state), encoding="utf-8")
        self.assertContinues(self.finish())
        self.assertEqual(self.state()["taskContract"]["taskId"], "arithmetic")
        self.assertEqual(self.state()["lastWriteStep"], 4)
        self.review("delivery", 8)
        self.assertIn("delivery", self.state().get("acceptanceReviewErrors", {}))
        self.command(9, "python3 -m pytest -q")
        self.review("delivery", 10, rows=[self.row(evidence=[9], reason="Fresh completed arithmetic check.")])
        self.assertAllows(self.finish(step=11, rows=[self.row(evidence=[9])]))

    def test_running_tool_error_retains_failure_debt_without_terminal_check_row(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        path = self.transcript(*self.records, {"source": "MODEL", "type": "GENERIC", "status": "RUNNING",
                                              "step_index": 5, "content": "Synthetic partial output."})
        self.call("post", {"transcriptPath": str(path), "stepIdx": 5, "error": "explicit tool error",
                           "toolCall": {"name": "run_command", "args": {
                               "CommandLine": "python3 -m unittest -q", "Cwd": str(self.workspace)}}})
        self.assertFalse(self.state().get("checkEvents"))
        self.assertEqual(len(self.state()["failedChecks"]), 1)
        self.command(6, "python3 -m pytest -q")
        self.review("delivery", 7, rows=[self.row(evidence=[6], reason="Another completed check.")])
        self.assertContinues(self.finish(step=8, rows=[self.row(evidence=[6])]))
        self.command(9, "python3 -m unittest -q")
        self.review("delivery", 10, rows=[self.row(evidence=[9], reason="The failed tool call completed successfully.")])
        self.assertFalse(self.state()["failedChecks"])
        self.assertAllows(self.finish(step=11, rows=[self.row(evidence=[9])]))

    def test_native_full_transcript_bootstraps_and_completes_v2_contract(self):
        full = self.artifacts / "transcript_full.jsonl"
        self.records = [{**self.user_record(self.request), "source": "USER_EXPLICIT", "type": "USER_INPUT"}]
        full.write_text("\n".join(json.dumps(row) for row in self.records) + "\n", encoding="utf-8")
        self.common["transcriptPath"] = str(full)
        self.register()
        state_path = self.artifacts / ".codex-claude-harness-verification.json"
        self.assertTrue(state_path.is_file(), "native transcript must register the first contract")
        self.assertEqual(self.state()["taskContract"]["userStep"], 1)
        self.review("scope", 3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6)
        result = {"status": "complete", "taskId": "arithmetic", "revision": 1,
                  "requirements": [self.row(evidence=[5])]}
        records = self.records + [self.model_record("HARNESS_RESULT: " + json.dumps(result), step=7)]
        full.write_text("\n".join(json.dumps(row) for row in records) + "\n", encoding="utf-8")
        self.assertAllows(self.grounded_stop(full))

    def test_native_protocol_registration_requires_exact_current_artifact_target(self):
        value = {"version": 2, "taskId": "arithmetic", "revision": 1,
                 "requirements": [self.requirement()]}
        content = json.dumps(value)
        filename = "harness-task-contract.json"
        for target in (self.workspace / filename, self.artifacts / "nested" / filename):
            target.parent.mkdir(exist_ok=True)
            target.write_text(content, encoding="utf-8")
            self.post(2, "write_file", {"Path": str(target), "Content": content, "Overwrite": True,
                                        "IsArtifact": True, "TargetFile": str(self.artifacts / filename)})
            self.assertNotIn("taskContract", self.state())
        target = self.artifacts / filename
        try:
            target.symlink_to(self.workspace / filename)
        except OSError:
            return
        self.post(3, "write_file", {"Path": str(target), "Content": content, "Overwrite": True})
        self.assertNotIn("taskContract", self.state())

    def test_native_protocol_file_without_observed_write_does_not_register(self):
        target = self.artifacts / "harness-task-contract.json"
        value = {"version": 2, "taskId": "arithmetic", "revision": 1,
                 "requirements": [self.requirement()]}
        target.write_text(json.dumps(value), encoding="utf-8")
        self.assertContinues(self.finish())
        self.assertNotIn("taskContract", self.state())

    def test_delivery_review_citing_unrecorded_check_is_rejected(self):
        self.register()
        self.review("scope", 3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6, rows=[self.row(evidence=[99], reason="Invented step.")])
        self.assertContinues(self.finish(rows=[self.row(evidence=[99])]))
        self.assertIn("delivery", self.state().get("acceptanceReviewErrors", {}))

    def test_complete_rejected_when_all_static_after_logic_write(self):
        self.register([self.requirement(verification="static")])
        self.review("scope", 3)
        self.write(step=4)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6)
        result = self.finish()
        self.assertEqual(result["decision"], "continue", result)
        self.assertIn("declared static", result["reason"])

    def test_all_static_contract_can_complete_without_logic_writes(self):
        self.register([self.requirement(verification="static")])
        self.review("scope", 3)
        self.command(5, "python3 -m pytest -q")
        self.review("delivery", 6, rows=[self.row(evidence=[5], reason="The check covers the static change.")])
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
