"""Deterministic eval-runner checks; these never contact a model or an MCP."""
import json
import os
import pathlib
import queue
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from evals import output_quality
from evals.output_quality import (
    EvalError, completion_claim, execute_turns, require_response_contract, safe_turn_summary, score_acceptance,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
CASES = {case["id"]: case for case in json.loads((ROOT / "evals/cases.json").read_text())}
SOLUTION = '''class WaitingList:
    def __init__(self, capacity):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("invalid capacity")
        self.capacity = capacity
        self.names = []

    def _name(self, name):
        if not isinstance(name, str) or not name.strip():
            raise ValueError("invalid name")
        return name.strip()

    def join(self, name):
        name = self._name(name)
        if name in self.names or len(self.names) >= self.capacity:
            raise ValueError("duplicate or full")
        self.names.append(name)
        return len(self.names)

    def snapshot(self):
        return self.names[:]

    def cancel(self, name):
        name = self._name(name)
        if name not in self.names:
            return False
        self.names.remove(name)
        return True

    def position(self, name):
        name = self._name(name)
        return self.names.index(name) + 1 if name in self.names else None

    def next(self):
        return self.names.pop(0) if self.names else None

    def join_many(self, names):
        normalized = [self._name(name) for name in names]
        if (len(set(normalized)) != len(normalized)
                or any(name in self.names for name in normalized)
                or len(self.names) + len(normalized) > self.capacity):
            raise ValueError("invalid batch")
        positions = list(range(len(self.names) + 1, len(self.names) + len(normalized) + 1))
        self.names.extend(normalized)
        return positions
'''
NONATOMIC = SOLUTION[:SOLUTION.index('    def join_many')] + '''    def join_many(self, names):
        return [self.join(name) for name in names]
'''


def complete_response(count=8):
    return {"response": "Harness: IMPLEMENT; passed: implementation; failed/skipped: none\nHARNESS_RESULT: " + json.dumps({
        "status": "complete", "requirements": [
            {"id": "AC-" + str(i), "status": "passed", "evidenceSteps": [i]}
            for i in range(1, count + 1)
        ],
    })}


class FakeStreamOutput:
    def __init__(self):
        self.lines = queue.Queue()
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        line = self.lines.get()
        if line is None:
            raise StopIteration
        return line

    def close(self):
        self.closed = True


class FakeStreamInput:
    def __init__(self, process):
        self.process = process
        self.closed = False
        self.pending = ""

    def write(self, value):
        self.pending += value

    def flush(self):
        self.process.prompts.append(json.loads(self.pending))
        self.pending = ""
        index = len(self.process.prompts) - 1
        for event in self.process.turn_events[index]:
            self.process.emit(event)

    def close(self):
        if not self.closed:
            self.closed = True
            for event in self.process.trailing_events:
                self.process.emit(event)
            self.process.returncode = self.process.exit_status
            self.process.stdout.lines.put(None)


class FakeStreamProcess:
    def __init__(self, turn_events, trailing_events=(), exit_status=0, resist_terminate=False):
        self.turn_events = turn_events
        self.trailing_events = trailing_events
        self.exit_status = exit_status
        self.resist_terminate = resist_terminate
        self.stdout = FakeStreamOutput()
        self.stdin = FakeStreamInput(self)
        self.prompts = []
        self.returncode = None
        self.terminated = False
        self.killed = False

    def emit(self, event):
        self.stdout.lines.put(event if isinstance(event, str) else json.dumps(event) + "\n")

    def poll(self):
        return self.returncode

    def wait(self, timeout):
        if self.returncode is None:
            raise subprocess.TimeoutExpired(["private-argument"], timeout, output="private-output")
        return self.returncode

    def terminate(self):
        self.terminated = True
        if not self.resist_terminate:
            self.returncode = -15
            self.stdout.lines.put(None)

    def kill(self):
        self.killed = True
        self.returncode = -9
        self.stdout.lines.put(None)


def stream_init(conversation="private-conversation"):
    return {"event": "init", "conversation_id": conversation, "init": {}}


def stream_result(turn, conversation="private-conversation", **changes):
    result = {"status": "SUCCESS", "conversation_id": conversation, "num_turns": turn,
              "response": "Harness: DIRECT; private response", "duration_seconds": turn * 100,
              "usage": dict(input_tokens=turn * 2, output_tokens=turn * 3, thinking_tokens=0,
                            cache_read_tokens=turn * 5, total_tokens=turn * 10)}
    result.update(changes)
    return {"event": "result", "result": result}


class OutputQualityEvalTests(unittest.TestCase):
    def test_response_steps_separate_stop_repair_without_relaxing_final_claim(self):
        trace = output_quality.ResponseSteps()
        draft = complete_response()["response"]
        final = draft.replace('"complete"', '"partial"')
        for index, text in ((2, draft), (5, final)):
            trace.update({"step_index": index, "step_type": "agent_response", "state": "ACTIVE",
                          "text_delta": text[:17]})
            trace.update({"step_index": index, "step_type": "agent_response", "state": "DONE",
                          "text_delta": text[17:]})
        trace.update({"step_index": 3, "step_type": "tool", "state": "DONE",
                      "tool_name": "run_command", "duration_seconds": 0.5,
                      "tool_info": {"output": "private output", "parameters": {"secret": "private"}}})
        result = trace.final_response({"response": draft + "\n" + final})
        self.assertEqual(result["response"], final)
        self.assertEqual(completion_claim(result["response"])["status"], "partial")
        self.assertEqual(result["event_diagnostics"]["aggregate_claim_count"], 2)
        self.assertEqual(result["event_diagnostics"]["final_response_claim_count"], 1)
        self.assertEqual(result["event_diagnostics"]["tools"]["run_command"]["calls"], 1)
        self.assertNotIn("private", json.dumps(result["event_diagnostics"]))
        duplicate = output_quality.ResponseSteps()
        duplicate.update({"step_index": 1, "step_type": "agent_response", "state": "DONE",
                          "text_delta": draft + "\n" + draft})
        with self.assertRaisesRegex(EvalError, "exactly one"):
            completion_claim(duplicate.final_response({"response": draft + "\n" + draft})["response"])

    def test_response_steps_reject_missing_unfinished_conflicting_or_stale_handoff(self):
        scenarios = [
            ([], "no completed"),
            ([dict(step_index=1, step_type="agent_response", state="ACTIVE", text_delta="final")], "no completed"),
            ([dict(step_index=1, step_type="agent_response", state="DONE", text_delta="stale"),
              dict(step_index=2, step_type="tool", state="DONE")], "follows final"),
            ([dict(step_index=1, step_type="agent_response", state="DONE", text_delta="stale"),
              dict(step_index=2, step_type="subagent", state="DONE", subagent_info={"subagents":[]})], "follows final"),
            ([dict(step_index=1, step_type="agent_response", state="DONE", text_delta="different")], "disagrees"),
        ]
        for steps, message in scenarios:
            with self.subTest(message=message):
                trace = output_quality.ResponseSteps()
                for step in steps:
                    trace.update(step)
                with self.assertRaisesRegex(EvalError, message):
                    trace.final_response({"response": "final"})
        for step in (dict(step_index=True, step_type="tool", state="DONE"),
                     dict(step_index=0, step_type="agent_response", state="DONE", text_delta=None)):
            with self.subTest(step=step), self.assertRaises(EvalError):
                output_quality.ResponseSteps().update(step)
        trace = output_quality.ResponseSteps()
        done = dict(step_index=1, step_type="agent_response", state="DONE", text_delta="final")
        trace.update(done)
        with self.assertRaisesRegex(EvalError, "repeated"):
            trace.update(done)
        with self.assertRaisesRegex(EvalError, "disagrees"):
            trace.final_response({"response": "final\nHARNESS_RESULT: untraced trailing handoff"})

    def test_process_events_uses_print_output_events_without_sending_stdin_prompt(self):
        processes = []
        for turn in (1, 2):
            process = FakeStreamProcess([])
            for event in [stream_init(), {"event": "step_update", "step_update": {
                    "conversation_id": "private-conversation", "step_index": turn * 10,
                    "step_type": "agent_response", "state": "DONE", "text_delta": "final"}},
                    stream_result(turn, response="final")]:
                process.emit(event)
            process.returncode = 0
            process.stdout.lines.put(None)
            processes.append(process)
        with mock.patch.object(output_quality.subprocess, "Popen", side_effect=processes) as popen:
            result, summaries = execute_turns(["first", "second"], "model", ROOT, 1, "process-events")
        self.assertEqual(result["response"], "final")
        self.assertEqual(popen.call_count, 2)
        commands = [call.args[0] for call in popen.call_args_list]
        self.assertIn("--new-project", commands[0])
        self.assertIn("--conversation", commands[1])
        for process, command, prompt in zip(processes, commands, ["first", "second"]):
            self.assertEqual(command[command.index("-p") + 1], prompt)
            self.assertEqual(command[command.index("--output-format") + 1], "stream-json")
            self.assertEqual(command[command.index("--print-timeout") + 1], "1s")
            self.assertEqual(process.prompts, [])
            self.assertNotIn("--input-format", command)
        self.assertNotIn("private", json.dumps(summaries))

    def test_error_steps_are_failures_and_require_a_later_done_final_response(self):
        trace = output_quality.ResponseSteps()
        trace.update(dict(step_index=1, step_type="tool", state="ACTIVE", tool_name="run_command"))
        trace.update(dict(step_index=1, step_type="tool", state="ERROR"))
        trace.update(dict(step_index=2, step_type="agent_response", state="ERROR", text_delta="failed draft"))
        with self.assertRaisesRegex(EvalError, "final response step failed"):
            trace.final_response({"response": "failed draft"})
        trace.update(dict(step_index=3, step_type="agent_response", state="DONE", text_delta="final"))
        result = trace.final_response({"response": "failed draft\nfinal"})
        self.assertEqual(result["response"], "final")
        self.assertEqual(result["event_diagnostics"]["errored_steps"], 2)
        self.assertEqual(result["event_diagnostics"]["tools"]["run_command"]["errors"], 1)
        self.assertEqual(result["event_diagnostics"]["tools"]["run_command"]["calls"], 1)

    def test_final_handoff_rejects_pending_execution_and_later_errors(self):
        for kind in ("tool", "subagent"):
            with self.subTest(kind=kind):
                trace = output_quality.ResponseSteps()
                trace.update(dict(step_index=1, step_type=kind, state="ACTIVE"))
                trace.update(dict(step_index=2, step_type="agent_response", state="DONE", text_delta="final"))
                with self.assertRaisesRegex(EvalError, "unfinished execution"):
                    trace.final_response({"response": "final"})
                trace.update(dict(step_index=1, step_type=kind, state="DONE"))
                self.assertEqual(trace.final_response({"response": "final"})["response"], "final")
        for kind in ("error_message", "other"):
            with self.subTest(kind=kind):
                trace = output_quality.ResponseSteps()
                trace.update(dict(step_index=2, step_type="agent_response", state="DONE", text_delta="draft"))
                trace.update(dict(step_index=3, step_type=kind, state="ERROR"))
                with self.assertRaisesRegex(EvalError, "error step follows"):
                    trace.final_response({"response": "draft"})
                trace.update(dict(step_index=4, step_type="agent_response", state="DONE", text_delta="recovered"))
                self.assertEqual(trace.final_response({"response": "draft\nrecovered"})["response"], "recovered")

    def test_subagent_promotion_and_metadata_refresh_keep_one_invocation(self):
        trace = output_quality.ResponseSteps()
        trace.update(dict(step_index=1, step_type="tool", state="ACTIVE", tool_name="invoke_subagent"))
        trace.update(dict(step_index=1, step_type="subagent", state="DONE",
                          subagent_info={"subagents":[{"conversation_id":"private", "status":"running"}]}))
        trace.update(dict(step_index=1, step_type="subagent", state="DONE",
                          subagent_info={"subagents":[{"conversation_id":"private", "status":"done"}]}))
        trace.update(dict(step_index=2, step_type="agent_response", state="DONE", text_delta="final"))
        trace.update(dict(step_index=2, step_type="agent_response", state="DONE", duration_seconds=1))
        result = trace.final_response({"response":"final"})
        self.assertEqual(result["response"], "final")
        self.assertEqual(result["event_diagnostics"]["tools"]["invoke_subagent"]["calls"], 1)
        self.assertNotIn("private", json.dumps(result["event_diagnostics"]))
        bad = output_quality.ResponseSteps()
        bad.update(dict(step_index=1, step_type="tool", state="ACTIVE", tool_name="invoke_subagent"))
        with self.assertRaisesRegex(EvalError, "conflicting"):
            bad.update(dict(step_index=1, step_type="agent_response", state="DONE", text_delta="fake final"))

    def test_command_diagnostics_keep_categories_without_values_or_fingerprints(self):
        trace = output_quality.ResponseSteps()
        commands = ["python3 -c 'print(currentUserStep)' # private",
                    "python3 -m unittest test_private.py", "git diff", "rg private source.py", "echo private"]
        for index, command in enumerate(commands):
            trace.update(dict(step_index=index, step_type="tool", state="DONE", tool_name="run_command",
                              tool_info={"parameters":{"CommandLine":command}}))
        trace.update(dict(step_index=6, step_type="agent_response", state="DONE", text_delta="final"))
        metrics = trace.final_response({"response":"final"})["event_diagnostics"]
        self.assertEqual(metrics["command_categories_heuristic"],
                         {"acceptance_metadata":1,"tests":1,"git":1,"source_read":1,"other":1})
        self.assertNotIn("private", json.dumps(metrics))
        self.assertNotIn("fingerprint", json.dumps(metrics))
        self.assertEqual(safe_turn_summary({"response": "final", "event_diagnostics": metrics}, 1, 0)
                         ["event_diagnostics"], metrics)

    def test_command_metadata_refresh_uses_retained_tool_identity(self):
        trace = output_quality.ResponseSteps()
        for index in (1, 2):
            trace.update(dict(step_index=index, step_type="tool", state="ACTIVE", tool_name="run_command"))
            trace.update(dict(step_index=index, step_type="tool", state="DONE",
                              tool_info={"parameters":{"CommandLine":"python3 -m unittest -q # private"}}))
        trace.update(dict(step_index=3, step_type="agent_response", state="DONE", text_delta="final"))
        metrics = trace.final_response({"response":"final"})["event_diagnostics"]
        self.assertEqual(metrics["tools"]["run_command"]["calls"], 2)
        self.assertEqual(metrics["command_categories_heuristic"], {"tests": 2})
        self.assertEqual(metrics["duplicate_command_calls"], 1)
        self.assertNotIn("private", json.dumps(metrics))
        self.assertNotIn("fingerprint", json.dumps(metrics))

    def test_diagnostic_shapes_drop_arbitrary_nested_values_in_legacy_modes(self):
        diagnostics = {
            "raw_output": "private-output", "response_source": "private-source",
            "agent_response_steps": True, "subagent_steps": -1, "errored_steps": "private-count",
            "aggregate_claim_count": 2, "final_response_claim_count": 1, "duplicate_command_calls": 0,
            "native_mcp_invoker_advertised": "private-inventory", "initialization_seconds": float("nan"),
            "command_categories_heuristic": {"tests": 3, "private-command": 4, "source_read": True},
            "tools": {
                "run_command": {"calls": 2, "errors": 0, "output_bytes": 10, "duration_seconds": 0.5,
                                "output": "private-output", "parameters": {"secret": "private"}},
                "private-tool": {"calls": 1, "errors": 0, "output_bytes": 0, "duration_seconds": 0},
                "view_file": {"calls": 1, "errors": 0, "output_bytes": 0, "duration_seconds": float("inf")},
                "grep_search": {"calls": 1, "errors": True, "output_bytes": 0, "duration_seconds": 0},
            },
        }
        expected = {
            "aggregate_claim_count": 2, "final_response_claim_count": 1, "duplicate_command_calls": 0,
            "command_categories_heuristic": {"tests": 3},
            "tools": {"run_command": {"calls": 2, "errors": 0, "output_bytes": 10, "duration_seconds": 0.5}},
        }
        for mode in ("process", "stream"):
            with self.subTest(mode=mode):
                event = stream_result(1, event_diagnostics=diagnostics)
                if mode == "process":
                    process = subprocess.CompletedProcess(["agy"], 0, json.dumps(event["result"]), "private-stderr")
                    context = mock.patch.object(output_quality.subprocess, "run", return_value=process)
                else:
                    process = FakeStreamProcess([[stream_init(), event]])
                    context = mock.patch.object(output_quality.subprocess, "Popen", return_value=process)
                with context:
                    _, summaries = execute_turns(["request"], "model", ROOT, 1, mode)
                self.assertEqual(summaries[0]["event_diagnostics"], expected)
                self.assertNotIn("private", json.dumps(summaries))
        for invalid in (None, "private", ["private"], {"raw_output": "private"}):
            self.assertNotIn("event_diagnostics", safe_turn_summary({"response":"final", "event_diagnostics":invalid}, 1, 0))


    def test_stream_mode_reuses_one_process_and_preserves_prompt_and_safe_counters(self):
        process = FakeStreamProcess([
            [stream_init(), {"event": "step_update", "step_update": {
                "conversation_id": "private-conversation", "text_delta": "private-tool-output"}}, stream_result(1)],
            [stream_result(2)],
        ])
        with mock.patch.object(output_quality.subprocess, "Popen", return_value=process) as popen:
            response, summaries = execute_turns(["first\nrequest", "second"], "unchanged-model", ROOT, 1, "stream")
        self.assertEqual(response["num_turns"], 2)
        self.assertEqual(popen.call_count, 1)
        command = popen.call_args[0][0]
        self.assertEqual(command[command.index("--input-format") + 1], "stream-json")
        self.assertEqual(command[command.index("--output-format") + 1], "stream-json")
        self.assertEqual(command[command.index("--model") + 1], "unchanged-model")
        self.assertIn("--sandbox", command)
        self.assertIn("--mode=accept-edits", command)
        self.assertIn("--new-project", command)
        self.assertNotIn("-p", command)
        self.assertNotIn("--dangerously-skip-permissions", command)
        self.assertEqual(process.prompts, [
            {"event": "user", "message": {"content": "first\nrequest"}},
            {"event": "user", "message": {"content": "second"}},
        ])
        self.assertEqual([row["usage"]["total_tokens"] for row in summaries], [10, 20])
        self.assertTrue(all(0 <= row["duration_seconds"] < 1 for row in summaries))
        self.assertNotIn("private", json.dumps(summaries))
        self.assertTrue(process.stdin.closed and process.stdout.closed)
        self.assertFalse(process.terminated)

    def test_stream_timeout_is_bounded_and_kills_unresponsive_child(self):
        process = FakeStreamProcess([[stream_init()]], resist_terminate=True)
        with mock.patch.object(output_quality.subprocess, "Popen", return_value=process), \
                self.assertRaisesRegex(EvalError, "timed out") as raised:
            execute_turns(["request"], "model", ROOT, 0.02, "stream")
        self.assertTrue(process.terminated and process.killed)
        self.assertTrue(process.stdin.closed and process.stdout.closed)
        self.assertNotIn("private", str(raised.exception))

    @unittest.skipUnless(os.name != "nt", "POSIX fake agy launcher")
    def test_stream_exchange_with_real_pipes_uses_one_launcher_and_exits_cleanly(self):
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            launcher = temporary / "agy"
            log = temporary / "calls.json"
            launcher.write_text("#!" + sys.executable + '''
import json, os, pathlib, sys
log = pathlib.Path(os.environ["FAKE_STREAM_LOG"])
record = {"arguments": sys.argv[1:], "prompts": []}
print(json.dumps({"event": "init", "conversation_id": "private-pipe-conversation"}), flush=True)
for index, line in enumerate(sys.stdin, 1):
    record["prompts"].append(json.loads(line))
    log.write_text(json.dumps(record))
    print(json.dumps({"event": "step_update", "step_update": {"conversation_id": "private-pipe-conversation"}}), flush=True)
    print(json.dumps({"event": "result", "result": {"status": "SUCCESS", "conversation_id": "private-pipe-conversation", "num_turns": index,
        "response": "Harness: DIRECT; passed: exchange", "duration_seconds": index * 100}}), flush=True)
''')
            launcher.chmod(0o755)
            with mock.patch.dict(os.environ, PATH=str(temporary) + os.pathsep + os.environ["PATH"],
                                 FAKE_STREAM_LOG=str(log)):
                response, summaries = execute_turns(["first", "tiếp theo"], "model", temporary, 3, "stream")
            record = json.loads(log.read_text())
        self.assertEqual(response["num_turns"], 2)
        self.assertEqual([event["message"]["content"] for event in record["prompts"]], ["first", "tiếp theo"])
        self.assertEqual(len(summaries), 2)
        self.assertTrue(all(row["duration_seconds"] < 3 for row in summaries))
        self.assertNotIn("private", json.dumps(summaries))

    def test_stream_rejects_malformed_failed_and_out_of_order_results_and_cleans_up(self):
        scenarios = [
            ([stream_init(), "private invalid JSON"], "malformed JSON"),
            ([stream_init(), {"event": "result", "result": None}], "unexpected response status"),
            ([stream_init(), stream_result(1, status="ERROR", error="private-error")], "unexpected response status"),
            ([stream_init(), stream_result(2)], "out-of-order or duplicate"),
            ([stream_init(), stream_result(True)], "out-of-order or duplicate"),
            ([stream_init(), stream_result(1, response=None)], "no text response"),
            ([stream_result(1)], "before initialization"),
            ([stream_init(), stream_init()], "duplicate initialization"),
            ([stream_init(), {"event": "step_update", "step_update": None}], "invalid step event"),
            ([stream_init(), {"event": "private-event"}], "invalid event"),
            ([stream_init(), {"event": []}], "invalid event"),
        ]
        for events, message in scenarios:
            with self.subTest(message=message):
                process = FakeStreamProcess([events])
                with mock.patch.object(output_quality.subprocess, "Popen", return_value=process), \
                        self.assertRaisesRegex(EvalError, message) as raised:
                    execute_turns(["request"], "model", ROOT, 1, "stream")
                self.assertTrue(process.terminated)
                self.assertTrue(process.stdin.closed and process.stdout.closed)
                self.assertNotIn("private", str(raised.exception))

    def test_stream_requires_continuity_in_results_and_step_events(self):
        for second in (stream_result(2, "private-different"),
                       {"event": "step_update", "step_update": {"conversation_id": "private-different"}}):
            process = FakeStreamProcess([[stream_init(), stream_result(1)], [second]])
            with mock.patch.object(output_quality.subprocess, "Popen", return_value=process), \
                    self.assertRaisesRegex(EvalError, "conversation ID changed") as raised:
                execute_turns(["first", "second"], "model", ROOT, 1, "stream")
            self.assertNotIn("private", str(raised.exception))
            self.assertTrue(process.terminated)

    def test_stream_does_not_accept_duplicate_results_or_failed_final_exit(self):
        for process, prompts, message in (
            (FakeStreamProcess([[stream_init(), stream_result(1), stream_result(1)], [stream_result(2)]]),
             ["first", "second"], "out-of-order or duplicate"),
            (FakeStreamProcess([[stream_init(), stream_result(1)]], trailing_events=[stream_result(1)]),
             ["first"], "after the final result"),
            (FakeStreamProcess([[stream_init(), stream_result(1)]], exit_status=3),
             ["first"], "exited nonzero"),
        ):
            with self.subTest(message=message), \
                    mock.patch.object(output_quality.subprocess, "Popen", return_value=process), \
                    self.assertRaisesRegex(EvalError, message):
                execute_turns(prompts, "model", ROOT, 1, "stream")
            self.assertTrue(process.stdin.closed and process.stdout.closed)

    def test_stream_unexpected_eof_fails_and_default_cli_mode_observes_response_steps(self):
        process = FakeStreamProcess([[stream_init()]])
        process.stdout.lines.put(None)
        with mock.patch.object(output_quality.subprocess, "Popen", return_value=process), \
                self.assertRaisesRegex(EvalError, "ended before a terminal result"):
            execute_turns(["request"], "model", ROOT, 1, "stream")
        for extra, mode in (([], "process-events"), (["--session-mode", "process"], "process"),
                            (["--session-mode", "stream"], "stream")):
            with self.subTest(mode=mode), \
                    mock.patch.object(sys, "argv", ["output_quality.py", "--case", "multiturn-waiting-list",
                                      "--confirm-quota-use"] + extra), \
                    mock.patch.object(output_quality, "run_case", return_value={"success": True}) as run, \
                    mock.patch("builtins.print"):
                self.assertEqual(output_quality.main(), 0)
            run.assert_called_once_with(CASES["multiturn-waiting-list"],
                                        os.environ.get("HARNESS_EVAL_MODEL", "gemini-3.8-flash-high"),
                                        session_mode=mode)

    def test_cli_error_diagnostics_exclude_subprocess_arguments_and_output(self):
        errors = [
            subprocess.TimeoutExpired(["agy", "--conversation", "private-id"], 1,
                                      output="private-output", stderr="private-stderr"),
            subprocess.CalledProcessError(1, ["agy", "--conversation", "private-id"],
                                          output="private-output", stderr="private-stderr"),
            OSError("private-path"),
        ]
        for error in errors:
            with self.subTest(error=type(error).__name__), \
                    mock.patch.object(sys, "argv", ["output_quality.py", "--case",
                                      "multiturn-waiting-list", "--confirm-quota-use"]), \
                    mock.patch.object(output_quality, "run_case", side_effect=error), \
                    mock.patch("builtins.print") as printed:
                self.assertEqual(output_quality.main(), 1)
            payload = json.loads(printed.call_args[0][0])
            self.assertEqual(payload["event"], "quality_error")
            self.assertEqual(payload["error"], type(error).__name__)
            self.assertIn(payload["detail"], {"external command timed out", "external command failed"})
            self.assertNotIn("private", json.dumps(payload))

    def test_turn_summaries_copy_only_safe_documented_metadata(self):
        usage = dict(input_tokens=2, output_tokens=3, thinking_tokens=4,
                     cache_read_tokens=5, total_tokens=14, private="do-not-copy")
        response = dict(response="Harness: DIRECT; private response", status="SUCCESS",
                        conversation_id="private-conversation", usage=usage)
        summary = safe_turn_summary(response, 2, 1.23456)
        self.assertEqual(summary["turn"], 2)
        self.assertEqual(summary["status"], "SUCCESS")
        self.assertEqual(summary["route"], "DIRECT")
        self.assertEqual(summary["duration_seconds"], 1.235)
        self.assertEqual(set(summary["usage"]), set(usage) - {"private"})
        self.assertNotIn("private", json.dumps(summary))
        for invalid in (None, {}, dict(usage, input_tokens=True), dict(usage, total_tokens=-1)):
            response["usage"] = invalid
            self.assertIsNone(safe_turn_summary(response, 1, 0)["usage"])
        response["response"] = "Harness: ARBITRARY_PRIVATE_TOKEN; ignored"
        self.assertIsNone(safe_turn_summary(response, 1, 0)["route"])

    def test_multiturn_prompts_are_natural_requests_not_workflow_instructions(self):
        case = CASES["multiturn-waiting-list"]
        self.assertEqual(len(case["turns"]), 3)
        text = " ".join([case["prompt"]] + case["turns"]).casefold()
        for leaked_hint in ("ac-1", "subagent", "harness", "unittest", "pytest", "acceptance ledger"):
            self.assertNotIn(leaked_hint, text)
        self.assertIn("case-sensitive", text)
        self.assertEqual(len(case["acceptance_criteria"]), 8)
        for criterion in case["acceptance_criteria"]:
            self.assertIn("{evals}/acceptance/waiting_list_checks.py", criterion["verify"])
        self.assertEqual(case["required_changed_paths"], ["waiting_list.py"])
        self.assertEqual(case["allowed_changed_paths"], ["waiting_list.py", "test_waiting_list.py"])
        fixture = ROOT / "evals/fixtures/python-waiting-list"
        public_tests = (fixture / "test_waiting_list.py").read_text()
        self.assertIn("test_initial_duplicate_rule_ignores_case", public_tests)
        instructions = (fixture / "AGENTS.md").read_text()
        self.assertIn("You may run focused local tests", instructions)
        self.assertNotIn("Do not run terminal commands", instructions)

    def test_quality_route_alternatives_keep_legacy_route_checks_strict(self):
        case = CASES["multiturn-waiting-list"]
        self.assertEqual(case["allowed_routes"], ["IMPLEMENT", "COMPLEX_IMPLEMENT"])
        for route in case["allowed_routes"]:
            require_response_contract({"response": "Harness: " + route + "; passed: local checks"}, case)
        with self.assertRaises(EvalError):
            require_response_contract({"response": "Harness: DIRECT; passed: none"}, case)
        with self.assertRaises(EvalError):
            require_response_contract(
                {"response": "Harness: COMPLEX_IMPLEMENT; passed: local checks"},
                dict(case, quality_eval=False),
            )

    def test_behavioral_scores_detect_forgotten_requirement_despite_complete_claim(self):
        case = CASES["multiturn-waiting-list"]
        with tempfile.TemporaryDirectory() as directory:
            workspace = pathlib.Path(directory)
            target = workspace / "waiting_list.py"
            target.write_text(SOLUTION)
            correct = score_acceptance(case, workspace, complete_response())
            self.assertEqual((correct["passed"], correct["total"]), (8, 8))
            self.assertFalse(correct["false_complete"])
            target.write_text(NONATOMIC)
            forgotten = score_acceptance(case, workspace, complete_response())
        self.assertEqual((forgotten["passed"], forgotten["total"]), (7, 8))
        self.assertEqual(forgotten["coverage"], 7 / 8)
        self.assertTrue(forgotten["false_complete"])
        self.assertEqual([row["id"] for row in forgotten["criteria"] if row["status"] != "passed"], ["AC-7"])
        self.assertEqual(forgotten["claimed"]["passed"], 8)

    def test_baseline_fails_and_every_criterion_runs_after_failure(self):
        case = CASES["multiturn-waiting-list"]
        with mock.patch.dict(os.environ, {"PYTHONOPTIMIZE": "1"}):
            baseline = score_acceptance(case, ROOT / "evals/fixtures/python-waiting-list", {"response": ""})
        self.assertEqual((baseline["passed"], baseline["total"]), (0, 8))
        self.assertIsNone(baseline["claimed"])
        self.assertEqual(baseline["completion_claim_error"], "missing HARNESS_RESULT claim")
        self.assertEqual([row["id"] for row in baseline["criteria"]], ["AC-" + str(i) for i in range(1, 9)])

    def test_correct_behavior_does_not_mask_missing_completion_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = pathlib.Path(directory)
            (workspace / "waiting_list.py").write_text(SOLUTION)
            result = score_acceptance(CASES["multiturn-waiting-list"], workspace, {"response": "Harness: IMPLEMENT"})
            partial = score_acceptance(CASES["multiturn-waiting-list"], workspace,
                                       {"response": complete_response()["response"].replace('"complete"', '"partial"')})
        self.assertEqual(result["passed"], 8)
        self.assertEqual(result["completion_claim_error"], "missing HARNESS_RESULT claim")
        self.assertEqual(partial["passed"], 8)
        self.assertEqual(partial["claimed"]["status"], "partial")
        self.assertEqual(partial["completion_claim_error"], "final HARNESS_RESULT is not complete")

    def test_claim_parser_ignores_examples_and_rejects_invalid_counts(self):
        example = complete_response()["response"]
        self.assertIsNone(completion_claim("```text\n" + example + "\n```"))
        self.assertEqual(completion_claim(example)["total"], 8)
        for malformed in (
            'HARNESS_RESULT: nope',
            'HARNESS_RESULT: {"status":"complete","requirements":[]}',
            'HARNESS_RESULT: {"status":"complete","requirements":[{"id":"AC-1","status":"failed"}]}',
            example + "\n" + example,
        ):
            with self.subTest(malformed=malformed), self.assertRaises(EvalError):
                completion_claim(malformed)

    def test_simulated_mcp_selection_scores_decisions_without_claiming_execution(self):
        case = CASES["mcp-adaptive-selection-simulated"]
        selection = {
            "evidence_kind": "simulated_selection", "services_contacted": [],
            "selections": {"local_symbol": "local_search", "framework_api": "harness-context7",
                           "production_error": "harness-sentry", "rendered_page": "harness-playwright",
                           "sentry_unavailable": "supplied_logs"},
        }
        with tempfile.TemporaryDirectory() as directory:
            correct = score_acceptance(case, pathlib.Path(directory), {"response": "TOOL_SELECTION: " + json.dumps(selection)})
            self.assertEqual((correct["passed"], correct["total"]), (5, 5))
            self.assertEqual(correct["evidence_kind"], "simulated_selection")
            selection["selections"]["sentry_unavailable"] = "harness-sentry"
            unavailable = score_acceptance(case, pathlib.Path(directory), {"response": "TOOL_SELECTION: " + json.dumps(selection)})
            self.assertEqual((unavailable["passed"], unavailable["total"]), (4, 5))
            selection["services_contacted"] = ["harness-sentry"]
            invented_live = score_acceptance(case, pathlib.Path(directory), {"response": "TOOL_SELECTION: " + json.dumps(selection)})
            self.assertEqual(invented_live["passed"], 0)

    def test_simulated_selection_prompt_permits_artifact_and_protocol_lines(self):
        case = CASES["mcp-adaptive-selection-simulated"]
        self.assertIn("one plain-text line beginning TOOL_SELECTION:", case["prompt"])
        self.assertIn("Then add a separate normal Harness status line", case["prompt"])
        self.assertIn("using the REVIEW_ONLY route", case["prompt"])
        self.assertEqual(case["route"], "REVIEW_ONLY")
        self.assertEqual(len(case["acceptance_criteria"]), 5)
        selection = {
            "evidence_kind": "simulated_selection", "services_contacted": [],
            "selections": {"local_symbol": "local_search", "framework_api": "harness-context7",
                           "production_error": "harness-sentry", "rendered_page": "harness-playwright",
                           "sentry_unavailable": "supplied_logs"},
        }
        response = {"response": "TOOL_SELECTION: " + json.dumps(selection)
                    + "\nHarness: REVIEW_ONLY; passed: conceptual selection; failed/skipped: live MCP execution not required"}
        require_response_contract(response, case)
        with tempfile.TemporaryDirectory() as directory:
            score = score_acceptance(case, pathlib.Path(directory), response)
        self.assertEqual((score["passed"], score["total"]), (5, 5))
        with self.assertRaises(EvalError):
            require_response_contract({"response": response["response"].replace("REVIEW_ONLY", "DIRECT")}, case)

    @unittest.skipUnless(os.name != "nt", "POSIX fake agy launcher")
    def test_missing_route_keeps_independent_mcp_score_and_fails_overall(self):
        selection = {
            "evidence_kind": "simulated_selection", "services_contacted": [],
            "selections": {"local_symbol": "local_search", "framework_api": "harness-context7",
                           "production_error": "harness-sentry", "rendered_page": "harness-playwright",
                           "sentry_unavailable": "supplied_logs"},
        }
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            fake = temporary / "agy"
            envelope = {"status": "SUCCESS", "conversation_id": "private-conversation",
                        "response": "TOOL_SELECTION: " + json.dumps(selection)}
            envelope["num_turns"] = 1
            frames = [{"event":"init", "conversation_id":envelope["conversation_id"]},
                      {"event":"step_update", "step_update":{"step_index":1, "state":"DONE",
                       "step_type":"agent_response", "text_delta":envelope["response"]}},
                      {"event":"result", "result":envelope}]
            fake.write_text("#!" + sys.executable + "\nfor frame in " + repr([json.dumps(f) for f in frames]) + ":\n    print(frame)\n")
            fake.chmod(0o755)
            completed = subprocess.run(
                [sys.executable, str(ROOT / "evals/output_quality.py"), "--case",
                 "mcp-adaptive-selection-simulated", "--confirm-quota-use"],
                env=dict(os.environ, PATH=str(temporary) + os.pathsep + os.environ["PATH"]),
                capture_output=True, text=True, timeout=30,
            )
        self.assertEqual(completed.returncode, 1, completed.stdout + completed.stderr)
        score = json.loads(completed.stdout)
        self.assertEqual(score["event"], "quality_score")
        self.assertEqual((score["passed"], score["total"]), (5, 5))
        self.assertFalse(score["success"])
        self.assertIsNone(score["route"])
        self.assertIn("Harness status line", score["response_contract_error"])
        self.assertEqual(len(score["turn_summaries"]), 1)
        self.assertIsNone(score["turn_summaries"][0]["usage"])
        self.assertNotIn("private-conversation", completed.stdout)
        self.assertNotIn("TOOL_SELECTION:", completed.stdout)

    @unittest.skipUnless(os.name != "nt", "POSIX fake agy launcher")
    def test_live_runner_is_opt_in_and_preserves_conversation_across_turns(self):
        runner = ROOT / "evals/output_quality.py"
        refused = subprocess.run([sys.executable, str(runner), "--case", "multiturn-waiting-list"], capture_output=True, text=True)
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("--confirm-quota-use", refused.stderr)
        with tempfile.TemporaryDirectory() as directory:
            temporary = pathlib.Path(directory)
            fake = temporary / "agy"
            fake.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys
log = pathlib.Path(os.environ["FAKE_EVAL_LOG"])
calls = json.loads(log.read_text()) if log.exists() else []
args = sys.argv[1:]
calls.append(args)
log.write_text(json.dumps(calls))
if os.environ.get("FAKE_CONVERSATION_DRIFT") and len(calls) > 1:
    conversation = "different"
else:
    conversation = "same-conversation"
source = pathlib.Path(os.environ["FAKE_EVAL_SOLUTION"]).read_text()
pathlib.Path("waiting_list.py").write_text(source)
if os.environ.get("FAKE_WEAKEN_PUBLIC_TESTS"):
    pathlib.Path("test_waiting_list.py").write_text("import unittest\\nclass Weakened(unittest.TestCase):\\n    def test_placeholder(self):\\n        self.assertTrue(True)\\n")
else:
    pathlib.Path("test_waiting_list.py").write_text(pathlib.Path(os.environ["FAKE_EVAL_PUBLIC_TESTS"]).read_text())
response = json.loads(pathlib.Path(os.environ["FAKE_EVAL_RESPONSE"]).read_text())["response"]
result = {"status":"SUCCESS", "conversation_id":conversation, "response":response, "num_turns":len(calls)}
if args[args.index("--output-format") + 1] == "stream-json":
    print(json.dumps({"event":"init", "conversation_id":conversation}))
    print(json.dumps({"event":"step_update", "step_update":{"conversation_id":conversation,
        "step_index":len(calls)*10, "step_type":"agent_response", "state":"DONE", "text_delta":response}}))
    print(json.dumps({"event":"result", "result":result}))
else:
    print(json.dumps(result))
''')
            fake.chmod(0o755)
            solution = temporary / "solution.txt"; solution.write_text(SOLUTION)
            response = temporary / "response.json"; response.write_text(json.dumps(complete_response()))
            public_tests = temporary / "test_waiting_list.txt"
            initial_tests = (ROOT / "evals/fixtures/python-waiting-list/test_waiting_list.py").read_text()
            updated_tests = initial_tests.replace(
                '        with self.assertRaises(ValueError):\n            waiting.join(" mai ")\n        self.assertEqual(waiting.snapshot(), ["Mai"])',
                '        self.assertEqual(waiting.join(" mai "), 2)\n        self.assertEqual(waiting.snapshot(), ["Mai", "mai"])',
            ).replace("test_initial_duplicate_rule_ignores_case_without_mutation", "test_revised_duplicate_rule_is_case_sensitive")
            self.assertNotEqual(initial_tests, updated_tests)
            public_tests.write_text(updated_tests)
            log = temporary / "calls.json"
            env = dict(os.environ, PATH=str(temporary) + os.pathsep + os.environ["PATH"],
                       FAKE_EVAL_LOG=str(log), FAKE_EVAL_SOLUTION=str(solution), FAKE_EVAL_RESPONSE=str(response),
                       FAKE_EVAL_PUBLIC_TESTS=str(public_tests))
            command = [sys.executable, str(runner), "--case", "multiturn-waiting-list", "--confirm-quota-use"]
            completed = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            score = json.loads(completed.stdout)
            self.assertEqual((score["passed"], score["total"], score["turns"]), (8, 8, 4))
            self.assertEqual(score["public_verification"], "passed")
            self.assertIsNone(score["response_contract_error"])
            self.assertEqual([turn["turn"] for turn in score["turn_summaries"]], [1, 2, 3, 4])
            self.assertTrue(all(turn["status"] == "SUCCESS" and turn["route"] == "IMPLEMENT"
                                and turn["duration_seconds"] >= 0 for turn in score["turn_summaries"]))
            self.assertNotIn("same-conversation", completed.stdout)
            calls = json.loads(log.read_text())
            self.assertEqual(len(calls), 4)
            self.assertIn("--new-project", calls[0])
            for call in calls[1:]:
                self.assertNotIn("--new-project", call)
                self.assertEqual(call[call.index("--conversation") + 1], "same-conversation")
            self.assertEqual([call[call.index("-p") + 1] for call in calls],
                             [CASES["multiturn-waiting-list"]["prompt"]] + CASES["multiturn-waiting-list"]["turns"])
            log.unlink()
            integrated = subprocess.run(
                ["bash", str(ROOT / "evals/run-smoke.sh")],
                env=dict(env, HARNESS_EVAL_CASE="multiturn-waiting-list"),
                capture_output=True, text=True, timeout=30,
            )
            self.assertEqual(integrated.returncode, 0, integrated.stdout + integrated.stderr)
            self.assertIn('"passed": 8', integrated.stdout)
            self.assertEqual(len(json.loads(log.read_text())), 4)
            log.unlink(); solution.write_text(NONATOMIC)
            forgotten = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(forgotten.returncode, 1, forgotten.stdout)
            self.assertTrue(json.loads(forgotten.stdout)["false_complete"])
            log.unlink(); env["FAKE_WEAKEN_PUBLIC_TESTS"] = "1"
            weakened = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(weakened.returncode, 1, weakened.stdout + weakened.stderr)
            weakened_score = json.loads(weakened.stdout)
            self.assertEqual((weakened_score["passed"], weakened_score["total"]), (7, 8))
            self.assertIsNone(weakened_score["scope_error"])
            self.assertTrue(weakened_score["false_complete"])
            self.assertEqual(weakened_score["public_verification"], "passed")
            log.unlink(); env.pop("FAKE_WEAKEN_PUBLIC_TESTS")
            solution.write_text(SOLUTION)
            alternative_response = complete_response()
            alternative_response["response"] = alternative_response["response"].replace("Harness: IMPLEMENT;", "Harness: COMPLEX_IMPLEMENT;")
            response.write_text(json.dumps(alternative_response))
            alternative = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(alternative.returncode, 0, alternative.stdout + alternative.stderr)
            self.assertEqual(json.loads(alternative.stdout)["route"], "COMPLEX_IMPLEMENT")
            log.unlink()
            malformed_response = complete_response()
            malformed_response["response"] = malformed_response["response"].split("HARNESS_RESULT:")[0] + "HARNESS_RESULT: nope"
            response.write_text(json.dumps(malformed_response))
            malformed_claim = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            malformed_score = json.loads(malformed_claim.stdout)
            self.assertEqual(malformed_claim.returncode, 1, malformed_claim.stdout + malformed_claim.stderr)
            self.assertEqual((malformed_score["passed"], malformed_score["total"]), (8, 8))
            self.assertEqual(malformed_score["completion_claim_error"], "malformed HARNESS_RESULT claim")
            self.assertFalse(malformed_score["success"])
            response.write_text(json.dumps(alternative_response))
            log.unlink(); public_tests.write_text(initial_tests)
            stale_public = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(stale_public.returncode, 1, stale_public.stdout + stale_public.stderr)
            stale_score = json.loads(stale_public.stdout)
            self.assertEqual((stale_score["passed"], stale_score["total"]), (8, 8))
            self.assertEqual(stale_score["public_verification"], "failed")
            log.unlink(); env["FAKE_CONVERSATION_DRIFT"] = "1"
            drift = subprocess.run(command, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(drift.returncode, 1)
            self.assertIn("conversation ID changed", json.loads(drift.stdout)["detail"])


if __name__ == "__main__":
    unittest.main()
