"""Offline regressions for the native compaction eval; never consume model quota."""
import io
import json
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

from evals import compaction_quality as compaction
from evals.output_quality import EvalError


def response(**changes):
    obj = {"session_label": compaction.LABEL, "time_zone": "Asia/Ho_Chi_Minh",
           "attendee_limit": 32, "budget_vnd": 5_500_000,
           "events": [{key: row[key] for key in ("id", "track", "fee_vnd")}
                      for row in compaction.best_selection(excluded=(compaction.cancelled_id(),))],
           "approval_policy": "ask_before_booking", "notification_policy": "no_messages"}
    obj.update(changes)
    return {"response": json.dumps(obj) + "\nHarness: DIRECT; passed: planning; failed/skipped: none"}


EVIDENCE = compaction.NativeCompactionEvidence.native_ui_status("Conversation compacted")
HISTORY = {"same_conversation": True, "task_tool_calls": 0, "task_subagent_steps": 0,
           "completed_turns": 12}


class FakeNativeStage:
    def __init__(self, counts, conversation="private-id", changed=None):
        self.conversation = conversation
        self.initialized = False
        self.process = SimpleNamespace(stdin=io.StringIO())
        self.events = [{"event": "init", "conversation_id": conversation}]
        for index, count in enumerate(counts):
            text = response()["response"]
            self.events.extend([
                {"event": "step_update", "step_update": {"step_index": index * 10 + 1,
                 "step_type": "agent_response", "state": "DONE", "text_delta": text}},
                {"event": "result", "result": {"status": "SUCCESS", "response": text,
                 "conversation_id": changed or conversation, "num_turns": count}},
            ])
        self.finish_calls = 0
        self.close_calls = 0

    def _event(self, deadline):
        return self.events.pop(0)

    def _require_conversation(self, value):
        if value != self.conversation:
            raise EvalError("conversation identity changed")

    def finish(self, timeout):
        self.finish_calls += 1

    def close(self):
        self.close_calls += 1


class CompactionEvalTests(unittest.TestCase):
    def test_real_turn_plan_is_bounded_and_cumulative(self):
        turns = compaction.planning_turns()
        self.assertEqual(len(turns), 12)
        self.assertTrue(6_000 <= sum(len(turn.encode()) for turn in turns) <= 8_000)
        joined = "\n".join(turns)
        self.assertEqual(sum(joined.count(row["id"] + " |") for row in compaction.candidates()), 48)
        self.assertIn("32 attendees instead of 24", joined)
        self.assertIn("5,500,000 VND instead of 6,000,000", joined)
        self.assertNotIn(compaction.LABEL, compaction.FINAL_PROMPT)
        self.assertNotIn("5,500,000", compaction.FINAL_PROMPT)
        self.assertNotIn(compaction.cancelled_id(), compaction.FINAL_PROMPT)

    def test_correct_final_selection_and_native_observation_pass(self):
        score = compaction.score_response(response(), EVIDENCE, HISTORY)
        self.assertTrue(score["overall_pass"])
        self.assertEqual(score["passed"], score["total"])
        self.assertTrue(score["manual_compaction"])
        self.assertFalse(score["automatic_compaction_observed"])

    def test_model_assertion_or_checkpoint_does_not_substitute_native_status(self):
        for status in ("Nothing to compact yet.", "Compaction cancelled. Conversation was not compacted.",
                       "Compacting conversation", "Agent: Conversation compacted", "Conversation compacted\nextra"):
            evidence = compaction.NativeCompactionEvidence.native_ui_status(status)
            self.assertFalse(compaction.score_response(response(), evidence, HISTORY)["overall_pass"])
        self.assertFalse(compaction.score_response(response(), {"observed": True}, HISTORY)["overall_pass"])

    def test_stale_capacity_budget_and_cancelled_candidate_fail_independently(self):
        original = [{key: row[key] for key in ("id", "track", "fee_vnd")}
                    for row in compaction.best_selection()]
        score = compaction.score_response(response(attendee_limit=24, budget_vnd=6_000_000, events=original), EVIDENCE, HISTORY)
        self.assertFalse(score["checks"]["corrected_attendee_limit"])
        self.assertFalse(score["checks"]["corrected_budget"])
        self.assertFalse(score["checks"]["optimal_active_candidates"])
        self.assertTrue(score["checks"]["earliest_session_label_retained"])

    def test_context_sentinel_and_approval_constraints_are_checked(self):
        score = compaction.score_response(response(session_label="forgotten", time_zone="UTC",
                                                   approval_policy="always_allow", notification_policy="send"), EVIDENCE, HISTORY)
        for key in ("earliest_session_label_retained", "earliest_time_zone_retained",
                    "approval_constraint_retained", "no_messages_constraint_retained"):
            self.assertFalse(score["checks"][key])

    def test_no_extra_prose_keys_or_noninteger_currency(self):
        for candidate in (response(extra=True), response(budget_vnd=5_500_000.0),
                          {"response": "Here is the answer:\n" + response()["response"]}):
            self.assertFalse(compaction.score_response(candidate, EVIDENCE, HISTORY)["overall_pass"])

    def test_missing_harness_status_fails(self):
        candidate = response()
        candidate["response"] = candidate["response"].split("\nHarness:")[0]
        self.assertFalse(compaction.score_response(candidate, EVIDENCE, HISTORY)["checks"]["harness_status_present"])

    def test_tool_actions_incomplete_history_or_changed_conversation_fail(self):
        for history in (dict(HISTORY, task_tool_calls=1), dict(HISTORY, completed_turns=11),
                        dict(HISTORY, same_conversation=False)):
            self.assertFalse(compaction.score_response(response(), EVIDENCE, history)["overall_pass"])

    def test_public_score_contains_no_answer_or_opaque_identity(self):
        score = compaction.score_response(response(), EVIDENCE, dict(HISTORY, conversation="private-id"))
        text = json.dumps(score)
        for private in ("private-id", compaction.LABEL, "W19", "Asia/Ho_Chi_Minh", "response"):
            self.assertNotIn(private, text)

    def test_private_state_requires_ignored_path_and_restrictive_permissions(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(EvalError):
                compaction.write_private_state(pathlib.Path(temporary) / "public.json", {"conversation": "private"})
            path = pathlib.Path(temporary).resolve() / ".harness-eval.compaction" / "state.json"
            compaction.write_private_state(path, {"conversation": "private"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text())["conversation"], "private")
            compaction.write_private_state(path, {"conversation": "next"})
            self.assertEqual(json.loads(path.read_text())["conversation"], "next")

    def test_no_model_execution_without_explicit_run(self):
        with mock.patch.object(compaction, "prepare") as prepare, mock.patch("sys.stdout", new_callable=io.StringIO) as output:
            self.assertEqual(compaction.main([]), 0)
            prepare.assert_not_called()
            plan = json.loads(output.getvalue())
            self.assertFalse(plan["model_run"])
            self.assertTrue(plan["requires_native_compaction_observation"])

    def test_finish_refuses_unobserved_compaction_before_model_call(self):
        with mock.patch.object(compaction, "native_turn") as turn:
            with self.assertRaises(EvalError):
                compaction.finish({}, compaction.NativeCompactionEvidence(False, True), "model", pathlib.Path("."))
            turn.assert_not_called()

    def test_finish_resumes_identity_keeps_native_turns_and_filters_private_state(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12, history_user_bytes=6954, turn_summaries=[])
        candidate = dict(response(), conversation_id="private-id")
        with mock.patch.object(compaction, "native_turn", return_value=(candidate, {"turn": 14})) as turn:
            score = compaction.finish(state, EVIDENCE, "model", pathlib.Path("."))
            self.assertEqual(turn.call_args.args[4:6], ("private-id", 12))
            self.assertTrue(turn.call_args.kwargs["allow_compaction_turn_gap"])
            self.assertTrue(score["overall_pass"])
            self.assertEqual(score["pre_compaction_user_turns"], 12)
            self.assertNotIn("private-id", json.dumps(score))

    def test_prepare_rejects_public_state_path_before_model_call(self):
        with tempfile.TemporaryDirectory() as temporary, mock.patch.object(compaction, "native_turn") as turn:
            with self.assertRaises(EvalError):
                compaction.prepare("model", pathlib.Path(temporary), pathlib.Path(temporary) / "public.json")
            turn.assert_not_called()

    def test_native_turn_counter_requires_contiguous_history_before_compaction(self):
        for count, allow_gap, passes in ((13, False, True), (14, False, False),
                                        (14, True, True), (12, True, False), (True, True, False)):
            session = mock.Mock(initialized=False, conversation="private-id")
            result = dict(response(), status="SUCCESS", conversation_id="private-id", num_turns=count)
            session._event.side_effect = [
                {"event": "init", "conversation_id": "private-id"},
                {"event": "result", "result": result},
            ]
            session.response_steps.final_response.return_value = result
            with mock.patch.object(compaction.quality, "StreamSession", return_value=session) as launch:
                if passes:
                    compaction.native_turn("private prompt", "model", pathlib.Path("."), 1,
                                           "private-id", 12, allow_compaction_turn_gap=allow_gap)
                    session.finish.assert_called_once()
                else:
                    with self.assertRaises(EvalError):
                        compaction.native_turn("private prompt", "model", pathlib.Path("."), 1,
                                               "private-id", 12, allow_compaction_turn_gap=allow_gap)
                session.close.assert_called_once()
                self.assertEqual(launch.call_args.args[0][1:3], ["--agent", "default"])

    def test_archive_history_is_substantive_bounded_and_not_repeated_in_final(self):
        turns = compaction.planning_turns(8)
        self.assertEqual(len(turns), 20)
        size = sum(len(turn.encode()) for turn in turns)
        self.assertTrue(400_000 <= size <= 420_000)
        for index, turn in enumerate(turns[12:], 1):
            self.assertIn(f"AR{index:02}-0001", turn)
            self.assertIn("venue Cafe", turn)
            self.assertIn("remain ineligible", turn)
        self.assertNotIn("AR01", compaction.FINAL_PROMPT)
        maximum = compaction.planning_turns(80)
        self.assertEqual(len(maximum), 92)
        self.assertTrue(4_000_000 < sum(len(turn.encode()) for turn in maximum) < 5 * 1024 * 1024)
        for count in (-1, True, 81, 1.0):
            with self.assertRaises(EvalError):
                compaction.planning_turns(count)

    def test_archived_turns_must_all_complete(self):
        full = dict(HISTORY, completed_turns=20, planned_user_turns=20)
        self.assertTrue(compaction.score_response(response(), EVIDENCE, full)["overall_pass"])
        partial = dict(full, completed_turns=12)
        self.assertFalse(compaction.score_response(response(), EVIDENCE, partial)["overall_pass"])

    def test_uncompacted_behavior_diagnostic_never_passes_compaction(self):
        evidence = compaction.NativeCompactionEvidence(False, False)
        state = dict(HISTORY, conversation="private-id", native_turns=20, history_user_bytes=410000, turn_summaries=[])
        with mock.patch.object(compaction, "native_turn", return_value=(dict(response(), conversation_id="private-id"), {"turn": 21})):
            score = compaction.finish(state, evidence, "model", pathlib.Path("."), diagnose_uncompacted=True)
        self.assertFalse(score["overall_pass"])
        self.assertTrue(score["uncompacted_behavior_diagnostic_pass"])
        self.assertEqual(score["post_compaction_user_turns"], 0)
        self.assertFalse(score["automatic_compaction_observed"])

    def test_native_evidence_rejects_nonboolean_payloads(self):
        for observed, manual in ((1, True), (True, "private"), (None, False)):
            with self.assertRaises(EvalError):
                compaction.NativeCompactionEvidence(observed, manual)

    def test_native_automatic_boundary_requires_exact_divider_and_context_reduction(self):
        evidence = compaction.NativeCompactionEvidence.native_ui_boundary("Compacted", 120000, 48000)
        score = compaction.score_response(response(), evidence, HISTORY)
        self.assertTrue(score["overall_pass"])
        self.assertTrue(score["automatic_compaction_observed"])
        self.assertFalse(score["manual_compaction"])
        for label, before, after in (("Agent: Compacted", 100, 10), ("Compacted", 100, 100),
                                     ("Compacted", True, 0), ("Compacted", 100, -1)):
            self.assertFalse(compaction.NativeCompactionEvidence.native_ui_boundary(label, before, after).observed)

    def test_harness_status_rejects_duplicates_empty_fields_and_fenced_status(self):
        valid = "Harness: DIRECT; passed: planning; failed/skipped: none"
        self.assertTrue(compaction.valid_harness_status(valid))
        for text in (valid + "\n" + valid, valid.replace("planning", " "),
                     valid.replace("none", " "), valid.replace("DIRECT", "INVALID"),
                     "```\n" + valid + "\n```", "**" + valid + "**"):
            self.assertFalse(compaction.valid_harness_status(text))

    def test_private_state_refuses_symlinks_nonregular_and_unrelated_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = pathlib.Path(temporary).resolve() / ".harness-eval.compaction"
            base.mkdir()
            unrelated = base / "unrelated.json"
            unrelated.write_text('{"user": "preserve"}')
            link = base / "linked.json"
            link.symlink_to(unrelated)
            directory = base / "directory.json"
            directory.mkdir()
            parent_link = base / "linked-parent"
            parent_link.symlink_to(base, target_is_directory=True)
            for path in (unrelated, link, directory, parent_link / "new.json"):
                with self.assertRaises(EvalError):
                    compaction.write_private_state(path, {"conversation": "private"})
            self.assertEqual(unrelated.read_text(), '{"user": "preserve"}')
            self.assertTrue(link.is_symlink())

    def test_staged_archive_growth_counts_only_completed_actual_turns_and_bytes(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12,
                     planned_user_turns=12, history_user_bytes=6954,
                     archive_batches=0, archived_user_bytes=0, turn_summaries=[])
        counters = iter((13, 14))
        def native(*args, **kwargs):
            return dict(response(), conversation_id="private-id"), {"turn": next(counters)}
        with mock.patch.object(compaction, "native_turn", side_effect=native), \
                mock.patch.object(compaction, "write_private_state"):
            result = compaction.extend_history(state, 2, "model", pathlib.Path("."), pathlib.Path("state"))
        size = sum(len(compaction.archive_turn(index).encode()) for index in range(2))
        self.assertEqual(result["completed_turns"], 14)
        self.assertEqual(result["planned_user_turns"], 14)
        self.assertEqual(result["archive_batches"], 2)
        self.assertEqual(result["archived_user_bytes"], size)
        self.assertEqual(result["history_user_bytes"], 6954 + size)
        self.assertTrue(compaction.score_response(response(), EVIDENCE, result)["overall_pass"])

    def test_interrupted_archive_stage_keeps_declared_coverage_and_does_not_pass(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12,
                     planned_user_turns=12, history_user_bytes=6954,
                     archive_batches=0, archived_user_bytes=0, turn_summaries=[])
        with mock.patch.object(compaction, "native_turn", side_effect=[
                (dict(response(), conversation_id="private-id"), {"turn": 13}), EvalError("native failure")]), \
                mock.patch.object(compaction, "write_private_state"):
            with self.assertRaises(EvalError):
                compaction.extend_history(state, 16, "model", pathlib.Path("."), pathlib.Path("state"))
        self.assertEqual(state["planned_user_turns"], 28)
        self.assertEqual(state["completed_turns"], 13)
        self.assertEqual(state["history_user_bytes"], 6954 + len(compaction.archive_turn(0).encode()))
        self.assertFalse(compaction.score_response(response(), EVIDENCE, state)["overall_pass"])

    def test_archive_generator_rejects_unbounded_and_invalid_stage_inputs(self):
        for index, total, size in ((80, 80, 51200), (-1, 80, 51200), (0, 81, 51200),
                                   (True, 80, 51200), (0, 80, 51201)):
            with self.assertRaises(EvalError):
                compaction.archive_turn(index, total, size)

    def test_interrupted_stage_cannot_be_shrunk_to_claim_coverage(self):
        state = dict(HISTORY, conversation="private-id", native_turns=13,
                     planned_user_turns=28, completed_turns=13, history_user_bytes=58000,
                     archive_batches=1, archived_user_bytes=51046, turn_summaries=[])
        with mock.patch.object(compaction, "native_turn") as turn, \
                mock.patch.object(compaction, "write_private_state") as write:
            with self.assertRaises(EvalError):
                compaction.extend_history(state, 1, "model", pathlib.Path("."), pathlib.Path("state"))
            turn.assert_not_called()
            write.assert_not_called()
        self.assertEqual(state["planned_user_turns"], 28)
        self.assertFalse(compaction.score_response(response(), EVIDENCE, state)["overall_pass"])

    def test_standalone_subagent_step_without_tool_record_is_rejected(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12,
                     planned_user_turns=12, history_user_bytes=6954,
                     archive_batches=0, archived_user_bytes=0, turn_summaries=[])
        summary = {"turn": 13, "event_diagnostics": {"tools": {}, "subagent_steps": 1}}
        with mock.patch.object(compaction, "native_turn", return_value=(dict(response(), conversation_id="private-id"), summary)), \
                mock.patch.object(compaction, "write_private_state"):
            compaction.extend_history(state, 1, "model", pathlib.Path("."), pathlib.Path("state"))
            self.assertEqual(state["task_tool_calls"], 0)
            self.assertEqual(state["task_subagent_steps"], 1)
            score = compaction.finish(state, EVIDENCE, "model", pathlib.Path("."))
        self.assertEqual(score["task_subagent_steps"], 2)
        self.assertFalse(score["checks"]["no_task_subagent_steps"])
        self.assertFalse(score["overall_pass"])

    def test_persistent_stage_reuses_one_process_and_filters_private_identity(self):
        fake = FakeNativeStage([7, 8])
        observed = []
        with mock.patch.object(compaction.quality, "StreamSession", return_value=fake) as launch:
            with compaction.NativePlanningSession("model", pathlib.Path("."), conversation="private-id", previous_turns=6) as stage:
                _, first = stage("private prompt one", "model", pathlib.Path("."), 1, "private-id", 6, event_observer=observed.append)
                _, second = stage("private prompt two", "model", pathlib.Path("."), 1, "private-id", 7, event_observer=observed.append)
                self.assertEqual([first["turn"], second["turn"]], [7, 8])
                self.assertEqual(first["event_diagnostics"]["agent_response_steps"], 1)
                self.assertEqual(second["event_diagnostics"]["agent_response_steps"], 1)
            stage.finish()
        launch.assert_called_once()
        command = launch.call_args.args[0]
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--agent") + 1], "default")
        self.assertEqual(command[command.index("--input-format") + 1], "stream-json")
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertEqual(fake.finish_calls, 1)
        self.assertEqual(fake.close_calls, 1)
        self.assertEqual(len(observed), 5)
        self.assertEqual(len(fake.process.stdin.getvalue().splitlines()), 2)
        self.assertNotIn("private", json.dumps([first, second]))

    def test_persistent_resume_allows_only_one_explicit_initial_failed_turn_gap(self):
        for counts, known, passes in (([8, 9], 1, True), ([7, 8], 1, True),
                                     ([8], 0, False), ([9], 1, False), ([8, 10], 1, False)):
            fake = FakeNativeStage(counts)
            with mock.patch.object(compaction.quality, "StreamSession", return_value=fake):
                stage = compaction.NativePlanningSession("model", pathlib.Path("."), conversation="private-id", previous_turns=6, known_failed_turns=known)
                try:
                    if passes:
                        for _ in counts:
                            stage("request", "model", pathlib.Path("."), 1, "private-id", stage.previous_turns)
                        stage.finish()
                    else:
                        with self.assertRaises(EvalError):
                            for _ in counts:
                                stage("request", "model", pathlib.Path("."), 1, "private-id", stage.previous_turns)
                finally:
                    stage.close()

    def test_persistent_result_identity_mismatch_and_changed_inputs_fail(self):
        fake = FakeNativeStage([7], changed="other-private-id")
        with mock.patch.object(compaction.quality, "StreamSession", return_value=fake):
            with self.assertRaises(EvalError):
                with compaction.NativePlanningSession("model", pathlib.Path("."), conversation="private-id", previous_turns=6) as stage:
                    stage("request", "model", pathlib.Path("."), 1, "private-id", 6)
        self.assertEqual(fake.finish_calls, 0)
        self.assertEqual(fake.close_calls, 1)

    def test_optional_turn_runner_is_used_in_final_scoring(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12,
                     history_user_bytes=6954, turn_summaries=[])
        runner = mock.Mock(return_value=(dict(response(), conversation_id="private-id"), {"turn": 13}))
        with mock.patch.object(compaction, "native_turn") as one_shot:
            score = compaction.finish(state, EVIDENCE, "model", pathlib.Path("."), turn_runner=runner)
        one_shot.assert_not_called()
        self.assertFalse(runner.call_args.kwargs["allow_compaction_turn_gap"])
        self.assertTrue(score["overall_pass"])

    def test_final_scoring_integrates_with_actual_persistent_callable(self):
        state = dict(HISTORY, conversation="private-id", native_turns=12,
                     history_user_bytes=6954, turn_summaries=[])
        fake = FakeNativeStage([13])
        with mock.patch.object(compaction.quality, "StreamSession", return_value=fake):
            with compaction.NativePlanningSession("model", pathlib.Path("."),
                    conversation="private-id", previous_turns=12) as stage:
                score = compaction.finish(state, EVIDENCE, "model", pathlib.Path("."), turn_runner=stage)
                self.assertTrue(score["overall_pass"])
        self.assertEqual(fake.finish_calls, 1)
        self.assertEqual(fake.close_calls, 1)


if __name__ == "__main__":
    unittest.main()
