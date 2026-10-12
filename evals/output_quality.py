#!/usr/bin/env python3
"""Independent output-quality scoring; model execution is explicitly opt-in."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
ROUTES = {"DIRECT", "LOCAL_LOOKUP", "RESEARCH", "IMPLEMENT", "COMPLEX_IMPLEMENT",
          "REVIEW_ONLY", "REVIEW_VERIFY"}


class EvalError(RuntimeError):
    """An eval response or execution violated its contract."""


def observed_route(response, preferred_routes=()):
    """Copy only a documented route token, never arbitrary response text."""
    routes = [line.strip().partition(":")[2].split(";", 1)[0].strip()
              for line in response.get("response", "").splitlines()
              if line.strip().startswith("Harness:")]
    return next((route for route in routes if route in preferred_routes),
                next((route for route in routes if route in ROUTES), None))


def safe_turn_summary(response, turn, duration):
    """Retain observable counters without responses, IDs or CLI diagnostics."""
    try:
        from .quota_benchmark import BenchmarkError, normalized_usage
    except ImportError:
        from quota_benchmark import BenchmarkError, normalized_usage
    try:
        usage = normalized_usage(response)
    except BenchmarkError:
        usage = None
    summary = {"turn": turn, "status": "SUCCESS", "route": observed_route(response),
               "duration_seconds": round(duration, 3), "usage": usage}
    diagnostics = safe_event_diagnostics(response.get("event_diagnostics"))
    if diagnostics is not None:
        summary["event_diagnostics"] = diagnostics
    return summary


def safe_event_diagnostics(diagnostics):
    """Whitelist diagnostic shapes even for legacy terminal envelopes."""
    if not isinstance(diagnostics, dict):
        return None
    safe = {}
    if diagnostics.get("response_source") == "last_completed_agent_response_step":
        safe["response_source"] = diagnostics["response_source"]
    for key in ("agent_response_steps", "subagent_steps", "errored_steps",
                "aggregate_claim_count", "final_response_claim_count", "duplicate_command_calls"):
        value = diagnostics.get(key)
        if type(value) is int and value >= 0:
            safe[key] = value
    advertised = diagnostics.get("native_mcp_invoker_advertised")
    if "native_mcp_invoker_advertised" in diagnostics and (advertised is None or type(advertised) is bool):
        safe["native_mcp_invoker_advertised"] = advertised
    duration = diagnostics.get("initialization_seconds")
    if "initialization_seconds" in diagnostics and (duration is None or
            (type(duration) in (int, float) and 0 <= duration < float("inf"))):
        safe["initialization_seconds"] = duration
    categories = diagnostics.get("command_categories_heuristic")
    if isinstance(categories, dict):
        safe["command_categories_heuristic"] = {
            key: value for key, value in categories.items()
            if key in {"acceptance_metadata", "tests", "git", "source_read", "other"}
            and type(value) is int and value >= 0
        }
    tools = diagnostics.get("tools")
    if isinstance(tools, dict):
        safe_tools = {}
        for name, metric in tools.items():
            if name not in ResponseSteps.TOOL_NAMES | {"other"} or not isinstance(metric, dict):
                continue
            counts = {key: metric.get(key) for key in ("calls", "errors", "output_bytes")}
            duration = metric.get("duration_seconds")
            if (all(type(value) is int and value >= 0 for value in counts.values())
                    and type(duration) in (int, float) and 0 <= duration < float("inf")):
                safe_tools[name] = dict(counts, duration_seconds=duration)
        safe["tools"] = safe_tools
    return safe or None


def require_response_contract(result, case):
    """Check observable response structure; prose is never behavioral proof."""
    text = result.get("response")
    if not isinstance(text, str):
        raise EvalError("terminal result has no text response")
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    harness_lines = [line for line in lines if line.startswith("Harness:")]
    routes = [line.partition(":")[2].split(";", 1)[0].strip() for line in harness_lines]
    expected_routes = case.get("allowed_routes", [case["route"]]) if case.get("quality_eval") else [case["route"]]
    if not any(route in expected_routes for route in routes):
        raise EvalError("Harness status line does not name route " + " or ".join(expected_routes))
    if case.get("inline_fast_path") and not any(
        "mode: inline-fast-path" in line for line in harness_lines
    ):
        raise EvalError("inline fast-path mode is missing from the Harness status line")
    if any(term not in text for term in case.get("response_contains", [])):
        raise EvalError("missing expected response terms")
    if any(term.casefold() in text.casefold() for term in case.get("response_not_contains", [])):
        raise EvalError("response contains forbidden terms")
    if case.get("response_only_lines") and lines != case["response_only_lines"]:
        raise EvalError("unexpected response lines")
    if case.get("response_line_count") is not None and len(lines) != case["response_line_count"]:
        raise EvalError("unexpected response line count")


def response_envelope(path):
    result = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    return validate_response_envelope(result)


def validate_response_envelope(result):
    if not isinstance(result, dict) or result.get("status") != "SUCCESS":
        raise EvalError("unexpected response status")
    if not isinstance(result.get("response"), str):
        raise EvalError("terminal result has no text response")
    conversation = result.get("conversation_id")
    if not isinstance(conversation, str) or not conversation.strip():
        raise EvalError("response has no conversation ID")
    return result


class ResponseSteps:
    """Separate completed handoffs from CLI aggregation, without copying tool data."""

    TOOL_NAMES = {"invoke_subagent", "send_message", "run_command", "view_file",
                  "grep_search", "find_by_name", "list_dir", "write_to_file",
                  "replace_file_content", "multi_replace_file_content", "call_mcp_tool"}

    def __init__(self):
        self.steps = {}
        self.native_mcp_invoker_advertised = None
        self.initialization_seconds = None

    def update(self, step):
        index, kind, state = (step.get(key) for key in ("step_index", "step_type", "state"))
        if (type(index) is not int or index < 0 or not isinstance(kind, str)
                or not isinstance(state, str) or state not in {"ACTIVE", "DONE", "ERROR"}):
            known_states = {"ACTIVE", "DONE", "ERROR", "CANCELLED", "PENDING", "RUNNING", "COMPLETED"}
            label = state if isinstance(state, str) and state in known_states else type(state).__name__
            raise EvalError("invalid response-step metadata: index=" + type(index).__name__
                            + ", kind=" + type(kind).__name__ + ", state=" + label
                            + ", content_fields=" + str(sum(bool(step.get(key)) for key in
                                ("text_delta", "tool_name", "tool_info", "subagent_info"))))
        row = self.steps.setdefault(index, {"kind": kind, "done": False, "text": ""})
        nontext = "text_delta" not in step or (isinstance(step["text_delta"], str) and step["text_delta"] == "")
        if (row["kind"] == "tool" and kind == "subagent" and nontext
                and isinstance(step.get("subagent_info"), (dict, list)) and step["subagent_info"]):
            # The CLI promotes the invocation step when worker metadata arrives.
            # Keep its original tool identity so this remains one observed call.
            row["kind"] = kind
        if row["kind"] != kind or (row["done"] and (state != row["state"] or not nontext)):
            known_kinds = {"agent_response", "checkpoint", "error_message", "finish", "subagent",
                           "system_message", "tool", "unknown", "user_input"}
            old_kind = row["kind"] if row["kind"] in known_kinds else "other"
            new_kind = kind if kind in known_kinds else "other"
            raise EvalError("conflicting or repeated completed step: previous_kind=" + old_kind
                            + ", next_kind=" + new_kind + ", previous_state=" + row.get("state", "unset")
                            + ", next_state=" + state + ", has_text=" + str(bool(step.get("text_delta")))
                            + ", has_subagent=" + str(bool(step.get("subagent_info"))))
        if kind == "agent_response":
            delta = step.get("text_delta", "")
            if not isinstance(delta, str):
                raise EvalError("invalid response-step text")
            row["text"] += delta
            if len(row["text"].encode("utf-8")) > 128 * 1024:
                raise EvalError("response step exceeds size limit")
        if kind == "tool":
            name = step.get("tool_name")
            if isinstance(name, str):
                row["tool"] = name if name in self.TOOL_NAMES else "other"
            else:
                row.setdefault("tool", "other")
            info = step.get("tool_info")
            if isinstance(info, dict):
                output = info.get("output")
                if isinstance(output, str):
                    row["output_bytes"] = len(output.encode("utf-8"))
                row["error"] = row.get("error", False) or bool(info.get("error"))
                parameters = info.get("parameters")
                command = parameters.get("CommandLine") if isinstance(parameters, dict) else None
                if row.get("tool") == "run_command" and isinstance(command, str):
                    row["command_fingerprint"] = hashlib.sha256(command.encode()).digest()
                    row["command_category"] = self.command_category(command)
        duration = step.get("duration_seconds")
        if type(duration) in (int, float) and 0 <= duration < float("inf"):
            row["duration"] = duration
        row["state"] = state
        row["done"] = state in {"DONE", "ERROR"}
        if state == "ERROR":
            row["error"] = True

    @staticmethod
    def command_category(command):
        """Lexical diagnostic only; never proof of a check or of wasted work."""
        if any(marker in command for marker in (
                ".codex-claude-harness-verification.json", "checkEvents", "currentUserStep")):
            return "acceptance_metadata"
        if re.search(r"\b(?:pytest|unittest)\b|\btest_[\w.-]+\.py\b", command):
            return "tests"
        if re.search(r"\bgit\s", command):
            return "git"
        if re.search(r"\b(?:rg|cat|sed|head|tail)\s", command):
            return "source_read"
        return "other"

    @staticmethod
    def claim_count(text):
        fence, count = None, 0
        for line in text.splitlines():
            line = line.strip()
            if line.startswith(("```", "~~~")):
                marker = line[:3]
                fence = marker if fence is None else None if fence == marker else fence
            elif fence is None and line.startswith("HARNESS_RESULT:"):
                count += 1
        return count

    def final_response(self, result):
        responses = [(index, row) for index, row in sorted(self.steps.items())
                     if row["kind"] == "agent_response"]
        if not responses or any(not row["done"] for _, row in responses):
            raise EvalError("no completed final response step")
        index, last = responses[-1]
        if last["state"] != "DONE":
            raise EvalError("final response step failed")
        if any(i > index and row["kind"] in {"tool", "subagent", "user_input"}
               for i, row in self.steps.items()):
            raise EvalError("tool or user step follows final response")
        if any(row["kind"] in {"tool", "subagent"} and not row["done"]
               for row in self.steps.values()):
            raise EvalError("unfinished execution step before final response")
        if any(i > index and row["state"] == "ERROR" for i, row in self.steps.items()):
            raise EvalError("error step follows final response")
        text = last["text"]
        if not text.strip() or not result["response"].rstrip().endswith(text.rstrip()):
            raise EvalError("final response disagrees with terminal aggregate")
        metrics = {}
        command_fingerprints = []
        command_categories = {}
        for row in self.steps.values():
            if "tool" not in row:
                continue
            name = row["tool"]
            metric = metrics.setdefault(name, {"calls": 0, "errors": 0,
                                              "output_bytes": 0, "duration_seconds": 0})
            metric["calls"] += 1
            metric["errors"] += int(row.get("error", False))
            metric["output_bytes"] += row.get("output_bytes", 0)
            metric["duration_seconds"] = round(metric["duration_seconds"] + row.get("duration", 0), 3)
            if "command_fingerprint" in row:
                command_fingerprints.append(row["command_fingerprint"])
                category = row["command_category"]
                command_categories[category] = command_categories.get(category, 0) + 1
        return dict(result, response=text, event_diagnostics={
            "response_source": "last_completed_agent_response_step",
            "agent_response_steps": len(responses),
            "subagent_steps": sum(row["kind"] == "subagent" for row in self.steps.values()),
            "errored_steps": sum(row["state"] == "ERROR" for row in self.steps.values()),
            "aggregate_claim_count": self.claim_count(result["response"]),
            "final_response_claim_count": self.claim_count(text),
            "native_mcp_invoker_advertised": self.native_mcp_invoker_advertised,
            "initialization_seconds": self.initialization_seconds,
            "duplicate_command_calls": len(command_fingerprints) - len(set(command_fingerprints)),
            "command_categories_heuristic": command_categories,
            "tools": metrics,
        })


class StreamSession:
    """Drive the public CLI NDJSON protocol without retaining tool diagnostics."""

    def __init__(self, command, workspace, initial_turn=1, capture_responses=False):
        self.started = time.monotonic()
        self.process = subprocess.Popen(
            command, cwd=str(workspace), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, text=True, bufsize=1,
        )
        self.events = queue.Queue()
        self.conversation = None
        self.initialized = False
        self.initial_turn = initial_turn
        self.response_steps = ResponseSteps() if capture_responses else None
        self.reader = threading.Thread(target=self._read_lines, daemon=True)
        self.reader.start()

    def _read_lines(self):
        try:
            for line in self.process.stdout:
                self.events.put(line)
        except (OSError, ValueError):
            pass
        finally:
            self.events.put(None)

    def _event(self, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise EvalError("stream session timed out waiting for a result")
        try:
            line = self.events.get(timeout=remaining)
        except queue.Empty:
            raise EvalError("stream session timed out waiting for a result") from None
        if line is None:
            return None
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            raise EvalError("stream session emitted malformed JSON") from None
        if (not isinstance(event, dict) or not isinstance(event.get("event"), str)
                or event["event"] not in {"init", "step_update", "result"}):
            raise EvalError("stream session emitted an invalid event")
        return event

    def _require_conversation(self, conversation):
        if not isinstance(conversation, str) or not conversation.strip():
            raise EvalError("stream event has no conversation ID")
        if self.conversation is not None and conversation != self.conversation:
            raise EvalError("conversation ID changed between user turns")
        self.conversation = conversation

    def ask(self, prompt, turn, deadline, send_prompt=True):
        if send_prompt:
            try:
                self.process.stdin.write(json.dumps({"event": "user", "message": {"content": prompt}}) + "\n")
                self.process.stdin.flush()
            except (OSError, ValueError):
                raise EvalError("stream session input closed before user turn completed") from None
        while True:
            event = self._event(deadline)
            if event is None:
                raise EvalError("stream session ended before a terminal result")
            kind = event["event"]
            if kind == "init":
                if self.initialized or turn != self.initial_turn:
                    raise EvalError("stream session emitted duplicate initialization")
                self._require_conversation(event.get("conversation_id"))
                if self.response_steps is not None:
                    self.response_steps.initialization_seconds = round(time.monotonic() - self.started, 3)
                    init = event.get("init")
                    tools = init.get("tools") if isinstance(init, dict) else None
                    if isinstance(tools, list) and all(isinstance(name, str) for name in tools):
                        self.response_steps.native_mcp_invoker_advertised = "call_mcp_tool" in tools
                self.initialized = True
                continue
            if not self.initialized:
                raise EvalError("stream session emitted an event before initialization")
            if kind == "step_update":
                step = event.get("step_update")
                if not isinstance(step, dict):
                    raise EvalError("stream session emitted an invalid step event")
                if "conversation_id" in step:
                    self._require_conversation(step["conversation_id"])
                if self.response_steps is not None:
                    self.response_steps.update(step)
                continue
            result = validate_response_envelope(event.get("result"))
            self._require_conversation(result["conversation_id"])
            count = result.get("num_turns")
            if type(count) is not int or count != turn:
                raise EvalError("stream session emitted an out-of-order or duplicate result")
            return self.response_steps.final_response(result) if self.response_steps is not None else result

    def finish(self, timeout):
        self.process.stdin.close()
        deadline = time.monotonic() + min(timeout, 5)
        # Detect extra results after the final requested turn instead of silently
        # accepting a broken protocol as a successful eval.
        while self._event(deadline) is not None:
            raise EvalError("stream session emitted an event after the final result")
        try:
            status = self.process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            raise EvalError("stream session did not exit after input closed") from None
        if status:
            raise EvalError("agy exited nonzero after stream session")

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=1)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=1)
        self.reader.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None and not stream.closed:
                stream.close()


def execute_turns(turns, model, workspace, timeout, session_mode="process"):
    if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
        raise EvalError("turn timeout must be positive and finite")
    common = ["agy", "--model", model, "--add-dir", str(workspace), "--sandbox",
              "--mode=accept-edits", "--print-timeout", str(math.ceil(timeout)) + "s"]
    summaries = []
    if session_mode == "stream":
        started = time.monotonic()
        session = StreamSession(common + ["--new-project", "--input-format", "stream-json",
                                         "--output-format", "stream-json"], workspace)
        try:
            for index, prompt in enumerate(turns):
                if index:
                    started = time.monotonic()
                response = session.ask(prompt, index + 1, started + timeout)
                summaries.append(safe_turn_summary(response, index + 1, time.monotonic() - started))
            session.finish(timeout)
        finally:
            session.close()
        return response, summaries
    if session_mode not in {"process", "process-events"}:
        raise EvalError("unknown session mode")
    conversation = None
    for index, prompt in enumerate(turns):
        command = common + ["-p", prompt, "--output-format",
                            "stream-json" if session_mode == "process-events" else "json"]
        command += ["--conversation", conversation] if conversation else ["--new-project"]
        started = time.monotonic()
        if session_mode == "process-events":
            session = StreamSession(command, workspace, index + 1, capture_responses=True)
            session.conversation = conversation
            try:
                response = session.ask(prompt, index + 1, started + timeout, send_prompt=False)
                session.finish(timeout)
            finally:
                session.close()
        else:
            completed = subprocess.run(command, cwd=str(workspace), capture_output=True,
                                       text=True, timeout=timeout, check=False)
            if completed.returncode:
                raise EvalError("agy exited nonzero on user turn " + str(index + 1))
            try:
                response = validate_response_envelope(json.loads(completed.stdout))
            except json.JSONDecodeError:
                raise EvalError("agy emitted malformed JSON") from None
        if conversation and response["conversation_id"] != conversation:
            raise EvalError("conversation ID changed between user turns")
        conversation = response["conversation_id"]
        summaries.append(safe_turn_summary(response, index + 1, time.monotonic() - started))
    return response, summaries


def completion_claim(text):
    """Read an optional result envelope outside fenced code blocks."""
    claims = []
    fence = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            if fence is None:
                fence = marker
            elif marker == fence:
                fence = None
            continue
        if fence is None and stripped.startswith("HARNESS_RESULT:"):
            claims.append(stripped.partition(":")[2].strip())
    if not claims:
        return None
    if len(claims) != 1:
        raise EvalError("expected exactly one HARNESS_RESULT claim")
    try:
        result = json.loads(claims[0])
    except json.JSONDecodeError as error:
        raise EvalError("malformed HARNESS_RESULT claim") from error
    if not isinstance(result, dict) or result.get("status") not in {"complete", "partial", "blocked"}:
        raise EvalError("invalid HARNESS_RESULT status")
    rows = result.get("requirements")
    if not isinstance(rows, list) or not rows:
        raise EvalError("HARNESS_RESULT requires a nonempty requirement list")
    ids = set()
    for row in rows:
        if (not isinstance(row, dict) or not isinstance(row.get("id"), str)
                or not row["id"] or row["id"] in ids
                or row.get("status") not in {"passed", "failed", "blocked", "unverified"}):
            raise EvalError("invalid or duplicate HARNESS_RESULT requirement")
        ids.add(row["id"])
    passed = sum(row["status"] == "passed" for row in rows)
    if result["status"] == "complete" and passed != len(rows):
        raise EvalError("complete claim includes unfinished requirements")
    return {"status": result["status"], "passed": passed, "total": len(rows)}


def expanded_command(command, workspace, response_path=None):
    expanded = [arg.replace("{evals}", str(EVALS)).replace("{workspace}", str(workspace))
                .replace("{response}", str(response_path)) for arg in command]
    # Windows Python installations need not expose a `python3` executable.
    if expanded and expanded[0] == "python3":
        expanded[0] = sys.executable
    return expanded


def score_acceptance(case, workspace, response, timeout=30):
    """Execute every runner-owned criterion, including after another fails."""
    with tempfile.TemporaryDirectory(prefix="harness-eval-judge-") as judge_directory:
        response_path = pathlib.Path(judge_directory) / "response.json"
        response_path.write_text(json.dumps(response), encoding="utf-8")
        return _score_acceptance(case, workspace, response, response_path, timeout)


def _score_acceptance(case, workspace, response, response_path, timeout):
    rows = []
    for criterion in case.get("acceptance_criteria", []):
        try:
            completed = subprocess.run(
                expanded_command(criterion["verify"], workspace, response_path), cwd=str(workspace),
                capture_output=True, text=True, timeout=timeout, check=False,
                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
            )
            status = "passed" if completed.returncode == 0 else "failed"
        except (OSError, subprocess.TimeoutExpired):
            status = "unverified"
        rows.append({"id": criterion["id"], "description": criterion["description"], "status": status})
    claim_error = None
    try:
        claim = completion_claim(response.get("response", ""))
        if claim is None and case.get("requires_completion_claim"):
            raise EvalError("missing HARNESS_RESULT claim")
        if claim and case.get("requires_completion_claim") and claim["status"] != "complete":
            claim_error = "final HARNESS_RESULT is not complete"
    except EvalError as error:
        claim = None
        claim_error = str(error)
    passed = sum(row["status"] == "passed" for row in rows)
    return {
        "event": "quality_score", "case": case["id"], "route": case["route"],
        "passed": passed, "total": len(rows),
        "coverage": passed / len(rows) if rows else None,
        "criteria": rows, "claimed": claim,
        "completion_claim_error": claim_error,
        "false_complete": bool(claim and claim["status"] == "complete" and passed != len(rows)),
        "evidence_kind": case.get("evidence_kind", "independent_behavioral_checks"),
    }


def run_case(case, model, timeout=900, session_mode="process"):
    # Imports work both as a module and as a directly invoked script.
    try:
        from .quota_benchmark import safe_fixture_path
        from .validate_changed_paths import changed_path_error, repository_changed_paths
    except ImportError:
        from quota_benchmark import safe_fixture_path
        from validate_changed_paths import changed_path_error, repository_changed_paths

    turns = [case["prompt"]] + case.get("turns", [])
    if not all(isinstance(turn, str) and turn.strip() for turn in turns):
        raise EvalError("turns must contain nonempty user messages")
    missing = [command for command in case.get("requires", [])
               if command != "python3" and not shutil.which(command)]
    if missing:
        raise EvalError("required runtime unavailable: " + ", ".join(missing))
    with tempfile.TemporaryDirectory(prefix=".harness-eval.", dir=str(ROOT)) as temporary:
        workspace = pathlib.Path(temporary) / "workspace"
        shutil.copytree(safe_fixture_path(case["fixture"]), workspace)
        for arguments in (
            ["init", "-q"], ["config", "user.name", "Harness Eval"],
            ["config", "user.email", "harness-eval@example.invalid"],
            ["config", "commit.gpgsign", "false"],
            ["config", "core.hooksPath", str(pathlib.Path(temporary) / "empty-hooks")],
            ["add", "."], ["commit", "-qm", "baseline"],
        ):
            subprocess.run(["git"] + arguments, cwd=str(workspace), check=True, capture_output=True)
        response, turn_summaries = execute_turns(turns, model, workspace, timeout, session_mode)
        response_contract_error = None
        try:
            require_response_contract(response, case)
        except EvalError as error:
            response_contract_error = str(error)
        changed = repository_changed_paths(workspace)
        scope_error = changed_path_error(changed, set(case.get("required_changed_paths", [])),
                                         set(case["allowed_changed_paths"]))
        score = score_acceptance(case, workspace, response)
        public_verification = "not_required"
        if case.get("verify"):
            try:
                checked = subprocess.run(
                    expanded_command(case["verify"], workspace), cwd=str(workspace),
                    capture_output=True, text=True, timeout=30, check=False,
                )
                public_verification = "passed" if checked.returncode == 0 else "failed"
            except (OSError, subprocess.TimeoutExpired):
                public_verification = "unverified"
        score["public_verification"] = public_verification
        score["turns"] = len(turns)
        score["model"] = model
        score["session_mode"] = session_mode
        allowed_routes = case.get("allowed_routes", [case["route"]])
        score["route"] = observed_route(response, allowed_routes)
        score["response_contract_error"] = response_contract_error
        score["turn_summaries"] = turn_summaries
        score["scope_error"] = scope_error
        score["success"] = (not scope_error and bool(changed) == case["expect_change"]
                            and score["total"] > 0 and score["passed"] == score["total"]
                            and not score["false_complete"]
                            and not response_contract_error and not score["completion_claim_error"]
                            and public_verification in {"passed", "not_required"})
        return score


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", required=True)
    parser.add_argument("--model", default=os.environ.get("HARNESS_EVAL_MODEL", "gemini-3.8-flash-high"))
    parser.add_argument("--session-mode", choices=("process", "process-events", "stream"), default="process-events",
                        help="process-events separates final handoff from aggregation; stream reuses a process")
    parser.add_argument("--confirm-quota-use", action="store_true")
    arguments = parser.parse_args()
    if not arguments.confirm_quota_use:
        parser.error("live quality evals require --confirm-quota-use")
    try:
        cases = json.loads((EVALS / "cases.json").read_text(encoding="utf-8"))
        case = next((item for item in cases if item["id"] == arguments.case), None)
        if case is None or not case.get("quality_eval"):
            raise EvalError("unknown quality eval case")
        score = run_case(case, arguments.model, session_mode=arguments.session_mode)
        print(json.dumps(score, sort_keys=True))
        return 0 if score["success"] else 1
    except (EvalError, OSError, ValueError, subprocess.SubprocessError) as error:
        # Subprocess exception text can contain argv, including conversation IDs.
        if isinstance(error, subprocess.TimeoutExpired):
            detail = "external command timed out"
        elif isinstance(error, (OSError, subprocess.SubprocessError)):
            detail = "external command failed"
        else:
            detail = str(error)
        print(json.dumps({"event": "quality_error", "error": type(error).__name__, "detail": detail}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
