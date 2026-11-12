import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "plugin/codex-claude-harness/scripts/resume_after_quota.py"
spec = importlib.util.spec_from_file_location("resume_after_quota", SCRIPT)
resume = importlib.util.module_from_spec(spec)
spec.loader.exec_module(resume)
PARENT = "12345678-abcd-1234-cdef-123456789012"
ANSWER = 'HARNESS_RESULT: {"status":"complete","requirements":[{"id":"A","status":"passed"}]}'


@unittest.skipUnless(os.name == "posix", "POSIX private jobs and advisory locks")
class ResumeAfterQuotaTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.job = self.root / "job.json"
        self.results = self.root / "results"
        self.results.mkdir(mode=0o700)
        self.settings = {
            "version": 1, "workspace": str(self.root), "conversation": PARENT,
            "agy": str(self.root / "agy"), "notBefore": "2020-01-01T00:00:00Z",
            "resultsDirectory": str(self.results),
        }
        self.save_job()
        self.stub()  # The entire suite uses a local synthetic executable.

    def save_job(self):
        self.job.write_text(json.dumps(self.settings))
        self.job.chmod(0o600)

    def stub(self, status="SUCCESS", code=0, parent=PARENT, response=ANSWER, errors="", duplicate=False,
             result_error=None, steps=()):
        events = [
            {"event": "init", "conversation_id": PARENT},
            {"event": "step_update", "step_update": {"step_index": 0, "step_type": "user_input", "state": "DONE"}},
            *({"event": "step_update", "step_update": step} for step in steps),
            {"event": "step_update", "step_update": {"step_index": 11, "step_type": "agent_response",
                                                     "text_delta": ANSWER, "state": "DONE"}},
            {"event": "result", "result": {"status": status, "conversation_id": parent, "response": response}}
        ]
        if result_error:
            events[-1]["result"]["error"] = result_error
        if duplicate:
            events.append(events[-1])
        body = "\n".join(json.dumps(event) for event in events)
        binary = Path(self.settings["agy"])
        binary.write_text(
            f"#!{sys.executable}\n"
            "import json, os, sys\n"
            "with open('submissions', 'a') as f: print(json.dumps(sys.argv[1:]), file=f)\n"
            "with open('stdin.jsonl', 'wb') as f: f.write(sys.stdin.buffer.read())\n"
            f"print({body!r})\n"
            f"print({errors!r}, file=sys.stderr)\n"
            f"sys.exit({code})\n"
        )
        binary.chmod(0o700)

    def run_job(self):
        return subprocess.run([sys.executable, "-B", str(SCRIPT), str(self.job)],
                              capture_output=True, text=True, timeout=5)

    def status(self):
        return json.loads((self.results / "status.json").read_bytes())

    def test_pre_due_and_duplicate_launch(self):
        self.settings["notBefore"] = "2099-11-19T07:00:36Z"
        self.save_job()
        first = self.run_job()
        self.assertEqual((first.returncode, json.loads(first.stdout)["state"]), (0, "scheduled"))
        self.assertFalse((self.root / "submissions").exists())
        self.assertFalse((self.results / "status.json").exists())
        self.settings["notBefore"] = "2020-01-01T00:00:00Z"
        self.save_job()
        self.assertEqual(self.run_job().returncode, 0)
        self.assertEqual(self.run_job().returncode, 0)
        commands = (self.root / "submissions").read_text().splitlines()
        self.assertEqual(len(commands), 1)
        args = json.loads(commands[0])
        self.assertEqual(args, ["--sandbox", "--print-timeout", "1800s", "--input-format", "stream-json",
                                "--output-format", "stream-json", "--conversation", PARENT])
        data = (self.root / "stdin.jsonl").read_bytes()
        self.assertTrue(data.endswith(b"\n"))
        self.assertEqual([json.loads(line) for line in data.splitlines()],
                         [{"event": "user", "message": {"content": resume.PROMPT}}])
        state = self.status()
        self.assertEqual((state["state"], state["nativeStatus"], state["cliExit"]), ("finished", "SUCCESS", 0))
        self.assertEqual(state["claim"], {"status": "complete", "passed": 1, "total": 1})
        self.assertEqual(state["claimStep"], 11)
        self.assertEqual((self.results / "status.json").stat().st_mode & 0o777, 0o600)
        self.assertNotIn(PARENT, json.dumps(state))

    def test_optional_execution_mode_is_validated_and_preserved(self):
        for mode in ("--dangerously-skip-permissions", None, ""):
            self.settings["mode"] = mode
            self.save_job()
            with self.subTest(mode=mode):
                self.assertEqual(self.run_job().returncode, 2)
                self.assertFalse((self.root / "submissions").exists())
        self.settings["mode"] = "accept-edits"
        self.save_job()
        self.assertEqual(self.run_job().returncode, 0)
        args = json.loads((self.root / "submissions").read_text())
        self.assertEqual([value for value in args if value.startswith("--mode")], ["--mode=accept-edits"])

    def test_supervised_zero_timeout_disables_native_limit_and_local_watchdog(self):
        self.settings["printTimeoutSeconds"] = 0
        self.save_job()
        with mock.patch.object(resume.threading, "Timer") as timer:
            self.assertEqual(resume.execute(self.job), ("finished", 0))
        timer.assert_not_called()
        args = json.loads((self.root / "submissions").read_text())
        self.assertEqual(args[args.index("--print-timeout") + 1], "0s")

    def test_positive_timeout_keeps_watchdog_grace_and_invalid_values_do_not_dispatch(self):
        for invalid in (-1, True, False, 1.5, "1800", None, resume.MAX_PRINT_TIMEOUT_SECONDS + 1):
            with self.subTest(invalid=invalid):
                self.settings["printTimeoutSeconds"] = invalid
                self.save_job()
                self.assertEqual(self.run_job().returncode, 2)
                self.assertFalse((self.root / "submissions").exists())
        self.settings["printTimeoutSeconds"] = 3600
        self.save_job()
        with mock.patch.object(resume.threading, "Timer") as timer:
            self.assertEqual(resume.execute(self.job), ("finished", 0))
        self.assertEqual(timer.call_args.args[0], 3660)
        timer.return_value.start.assert_called_once()
        timer.return_value.cancel.assert_called_once()
        args = json.loads((self.root / "submissions").read_text())
        self.assertEqual(args[args.index("--print-timeout") + 1], "3600s")

    def test_error_preserves_authored_claim_and_reset_without_replay(self):
        self.stub(status="ERROR", errors="PRIVATE-RAW RESOURCE_EXHAUSTED 429. Resets in 167h6m34s")
        first = self.run_job()
        self.assertEqual(first.returncode, 1)
        self.assertEqual(self.run_job().returncode, 1)
        self.assertEqual(len((self.root / "submissions").read_text().splitlines()), 1)
        state = self.status()
        self.assertEqual(state["reason"], "quota")
        self.assertEqual(state["nativeStatus"], "ERROR")
        self.assertEqual(state["cliExit"], 0)
        self.assertEqual(state["claim"]["status"], "complete")
        self.assertEqual(state["diagnostics"], {"stderr": "quota"})
        self.assertNotIn("retryNotBefore", state)
        self.assertNotIn("PRIVATE-RAW", first.stdout + first.stderr + json.dumps(state))
        initial = datetime(2026, 11, 12, 7, 54, 2, tzinfo=timezone.utc)
        self.assertEqual(resume.diagnostic("429. Resets in 167h6m34s", initial),
                         ("quota", "2026-11-19T07:00:36Z"))

    def test_native_success_and_process_exit_are_independent(self):
        self.stub(code=3)
        self.assertEqual(self.run_job().returncode, 1)
        state = self.status()
        self.assertEqual((state["state"], state["nativeStatus"], state["cliExit"]), ("interrupted", "SUCCESS", 3))

    def test_terminal_error_is_preserved_even_with_no_new_error_step(self):
        self.stub(status="ERROR", result_error="operation timed out")
        self.assertEqual(self.run_job().returncode, 1)
        state = self.status()
        self.assertEqual((state["state"], state["nativeStatus"], state["cliExit"], state["reason"]),
                         ("interrupted", "ERROR", 0, "timeout"))
        self.assertEqual(state["claim"]["status"], "complete")
        self.assertEqual(state["diagnostics"], {"terminal": "timeout"})

    def test_terminal_quota_cannot_refresh_a_replayed_reset_deadline(self):
        old_quota = {"step_index": 3, "step_type": "error_message", "error": "429. Resets in 167h."}
        steps = [
            {"step_type": "user_input", "step_index": 0, "state": "DONE"},
            old_quota,
            {"step_type": "user_input", "step_index": 8, "state": "DONE"},
            old_quota,
            dict(old_quota, conversation_id="child", step_index=9),
        ]
        self.stub(status="ERROR", result_error=old_quota["error"], steps=steps)
        self.assertEqual(self.run_job().returncode, 1)
        state = self.status()
        self.assertEqual((state["nativeStatus"], state["cliExit"], state["reason"]), ("ERROR", 0, "quota"))
        self.assertEqual(state["diagnostics"], {"terminal": "quota"})
        self.assertNotIn("retryNotBefore", state)

    def test_only_fresh_quota_step_sets_the_retry_deadline(self):
        steps = [
            {"step_type": "user_input", "step_index": 8, "state": "DONE"},
            {"step_index": 9, "step_type": "error_message", "error": "429. Resets in 1h."},
        ]
        self.stub(status="ERROR", steps=steps, result_error="429. Resets in 167h.", errors="429. Resets in 3h.")
        started = datetime.now(timezone.utc)
        self.assertEqual(self.run_job().returncode, 1)
        state = self.status()
        self.assertEqual(state["diagnostics"], {"currentStep": "quota", "stderr": "quota", "terminal": "quota"})
        deadline = datetime.fromisoformat(state["retryNotBefore"].replace("Z", "+00:00"))
        self.assertAlmostEqual((deadline - started).total_seconds(), 3600, delta=5)

    def test_wrong_conversation_and_duplicate_result_are_invalid(self):
        for case in ("wrong", "duplicate"):
            with self.subTest(case):
                receipt = resume.Receipt(PARENT)
                receipt.event({"event": "init", "conversation_id": PARENT})
                result = {"event": "result", "result": {"status": "SUCCESS", "conversation_id": PARENT, "response": ""}}
                if case == "wrong":
                    result["result"]["conversation_id"] = "other"
                receipt.event(result)
                if case == "duplicate":
                    receipt.event(result)
                self.assertTrue(receipt.invalid)

    def test_outer_response_cannot_invent_acceptance(self):
        self.stub(response=ANSWER.replace("complete", "blocked"))
        self.assertEqual(self.run_job().returncode, 0)
        self.assertEqual(self.status()["state"], "finished")
        self.assertIsNone(self.status()["claim"])
        self.assertNotIn("claimStep", self.status())

    def test_replayed_answer_cannot_certify_a_turn_without_a_fresh_response(self):
        old_user = {"step_type": "user_input", "step_index": 1, "state": "DONE"}
        old_answer = {"step_type": "agent_response", "step_index": 4, "state": "DONE", "text_delta": ANSWER}
        user = dict(old_user, step_index=7)
        unfinished = dict(old_answer, step_index=9, state="ACTIVE")
        for steps in ([old_answer], [old_user, old_answer, user], [user, old_answer], [user, unfinished, old_answer]):
            with self.subTest(steps=steps):
                receipt = resume.Receipt(PARENT)
                receipt.event({"event": "init", "conversation_id": PARENT})
                for step in steps:
                    receipt.event({"event": "step_update", "step_update": step})
                receipt.event({"event": "result", "result": {"status": "SUCCESS", "response": ANSWER}})
                self.assertEqual(receipt.native_status, "SUCCESS")
                self.assertFalse(receipt.invalid)
                self.assertIsNone(receipt.claim)

    def test_older_step_arriving_late_cannot_displace_current_answer(self):
        receipt = resume.Receipt(PARENT)
        receipt.event({"event": "init", "conversation_id": PARENT})
        for kind, index, text in (("user_input", 7, ""), ("agent_response", 11, ANSWER), ("agent_response", 9, "waiting")):
            receipt.event({"event": "step_update", "step_update": {
                "step_type": kind, "step_index": index, "state": "DONE", "text_delta": text}})
        receipt.event({"event": "result", "result": {"status": "SUCCESS", "response": ANSWER}})
        self.assertEqual(receipt.claim, {"status": "complete", "passed": 1, "total": 1})

    def test_parent_identity_comes_from_init_and_subagent_metadata_cannot_substitute_for_final(self):
        receipt = resume.Receipt(PARENT)
        receipt.event({"event": "project_info"})
        receipt.event({"event": "init", "conversation_id": PARENT})
        receipt.event({"event": "step_update", "step_update": {
            "conversation_id": PARENT, "step_type": "user_input", "step_index": 7, "state": "DONE"}})
        receipt.event({"event": "step_update", "step_update": {
            "conversation_id": "child", "step_index": 8, "step_type": "agent_response", "state": "DONE",
            "text_delta": ANSWER}})
        receipt.event({"event": "step_update", "step_update": {
            "conversation_id": PARENT, "step_index": 9, "step_type": "tool", "tool_name": "send_message",
            "tool_info": {"error": {"message": "RESOURCE_EXHAUSTED. Resets in 1h."}}}})
        receipt.event({"event": "result", "result": {"status": "ERROR", "response": ANSWER}})
        self.assertFalse(receipt.invalid)
        self.assertIsNone(receipt.claim)
        self.assertEqual(receipt.reason, "quota")
        self.assertIsNotNone(receipt.retry)

    def test_crash_and_concurrent_trigger_do_not_resubmit(self):
        def interrupted(_job):
            self.assertEqual(resume.execute(self.job), ("active", resume.BUSY))
            raise KeyboardInterrupt()
        with mock.patch.object(resume, "run_native", side_effect=interrupted):
            with self.assertRaises(KeyboardInterrupt):
                resume.execute(self.job)
        self.assertEqual(self.status()["state"], "submitted")
        self.assertEqual(resume.execute(self.job), ("reconcile_previous_attempt", 1))
        self.assertFalse((self.root / "submissions").exists())

    def test_public_job_or_results_and_uncertain_state_fail_closed(self):
        self.job.chmod(0o644)
        self.assertEqual(self.run_job().returncode, 2)
        self.job.chmod(0o600)
        self.results.chmod(0o755)
        self.assertEqual(self.run_job().returncode, 2)
        self.results.chmod(0o700)
        status = self.results / "status.json"
        status.write_text("null")
        status.chmod(0o600)
        self.assertEqual(self.run_job().returncode, 2)
        self.assertFalse((self.root / "submissions").exists())


if __name__ == "__main__":
    unittest.main()
