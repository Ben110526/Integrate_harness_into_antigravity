#!/usr/bin/env python3
"""Opt-in real-history compaction eval; native compaction is observed externally.

The preparation phase sends genuine turns through the first-party CLI. The
caller then resumes that conversation in the native TUI and invokes /compact
if available. Final scoring accepts native evidence separately from model text;
no prompt can pretend that compaction occurred. Private state must stay ignored.
"""
from __future__ import annotations

import argparse
import dataclasses
import itertools
import json
import math
import os
import pathlib
import re
import stat
import tempfile
import time

try:
    from . import output_quality as quality
except ImportError:
    import output_quality as quality

LABEL = "WORKSHOP-7Q2"
TRACKS = ("design", "python", "testing")
FINAL_KEYS = {"session_label", "time_zone", "attendee_limit", "budget_vnd",
              "events", "approval_policy", "notification_policy"}
MAX_ARCHIVE_BATCHES = 80
MAX_HISTORY_BYTES = 5 * 1024 * 1024


def candidates():
    """Deterministic task data, not tool output or fabricated chat history."""
    return [{"id": f"W{i:02}", "track": TRACKS[(i - 1) % 3],
             "fee_vnd": (8 + (i * 7) % 16) * 100_000,
             "capacity": 24 + (i * 11) % 25, "score": 45 + (i * 13) % 51,
             "venue": "Library" if i % 5 else "Cafe"}
            for i in range(1, 49)]


def best_selection(capacity=32, budget=5_500_000, excluded=()):
    pools = [[row for row in candidates() if row["track"] == track
              and row["capacity"] >= capacity and row["venue"] == "Library"
              and row["id"] not in excluded] for track in TRACKS]
    choices = [rows for rows in itertools.product(*pools)
               if sum(row["fee_vnd"] for row in rows) <= budget]
    return min(choices, key=lambda rows: (-sum(row["score"] for row in rows),
                                        sum(row["fee_vnd"] for row in rows),
                                        tuple(row["id"] for row in rows)))


def cancelled_id():
    return best_selection()[0]["id"]


def planning_turns(archive_batches=0, archive_batch_bytes=50 * 1024):
    if type(archive_batches) is not int or not 0 <= archive_batches <= MAX_ARCHIVE_BATCHES:
        raise quality.EvalError("archive batches must be an integer from zero to eighty")
    if type(archive_batch_bytes) is not int or not 1024 <= archive_batch_bytes <= 50 * 1024:
        raise quality.EvalError("archive batch size must be between 1 and 50 KiB")
    turns = [
        "We are planning a community workshop series. This is planning only: do not use tools, "
        "run commands, edit files, contact anyone, or book anything. Preserve the cumulative "
        "requirements across this conversation. Session label: WORKSHOP-7Q2. Use time zone "
        "Asia/Ho_Chi_Minh. Initially plan for 24 attendees with a total fee budget of 6,000,000 VND. "
        "Eventually choose exactly one event for each track: design, python, testing. Maximize "
        "the sum of their scores; on ties minimize total fees, then choose the lexicographically "
        "smallest tuple of IDs in track order design, python, testing. Do not finalize yet. "
        "Keep each interim answer to one short acknowledgement, apart from required harness status."
    ]
    for index in range(6):
        batch = candidates()[index * 8:(index + 1) * 8]
        lines = [f"{r['id']} | {r['track']} | fee {r['fee_vnd']} VND | capacity {r['capacity']} "
                 f"| score {r['score']} | venue {r['venue']}" for r in batch]
        turns.append(
            f"Candidate batch {index + 1} of 6 follows. These are independent alternatives; "
            "fees cover the whole event, capacity is the maximum attendees, and higher score "
            "means better suitability. Keep all candidates for the eventual comparison. "
            "No selection is final yet.\n" + "\n".join(lines))
    turns.extend([
        "Logistics constraint: only Library venues are allowed. Cafe alternatives are ineligible "
        "even if their fee or score looks better. Also preserve approval_policy as "
        "ask_before_booking and notification_policy as no_messages. Those mean ask before any "
        "booking and send no messages; do not take those actions in this planning task.",
        "Correction to the earlier attendee requirement: use 32 attendees instead of 24. "
        "Reject any candidate whose capacity is below 32. Keep every other active requirement.",
        "Correction to the earlier budget: use 5,500,000 VND instead of 6,000,000. "
        "The combined fees of the three selected events must fit that cap. Keep all other requirements.",
        f"The organizer has cancelled candidate {cancelled_id()}. Remove that candidate from "
        "consideration, keeping the other candidates and earlier constraints. Do not replace "
        "the whole task or treat this as permission to book or contact anyone.",
        "For the eventual final answer, provide one JSON object with exactly these keys: "
        "session_label, time_zone, attendee_limit, budget_vnd, events, approval_policy, "
        "notification_policy. events must be three objects in track order design, python, "
        "testing, each containing exactly id, track, fee_vnd. Use integer numbers, not formatted "
        "currency. Include the required Harness status separately. Do not finalize yet; simply "
        "acknowledge this output format now.",
    ])
    turns.extend(archive_turn(index, archive_batches, archive_batch_bytes)
                 for index in range(archive_batches))
    if sum(len(turn.encode()) for turn in turns) > MAX_HISTORY_BYTES:
        raise quality.EvalError("actual user history exceeds the 5 MiB limit")
    return turns


def archive_turn(index, total=MAX_ARCHIVE_BATCHES, batch_bytes=50 * 1024):
    """Generate one bounded real-data turn for staged native context growth."""
    if (type(index) is not int or type(total) is not int
            or not 0 <= index < total <= MAX_ARCHIVE_BATCHES):
        raise quality.EvalError("archive index must be inside the bounded batch plan")
    if type(batch_bytes) is not int or not 1024 <= batch_bytes <= 50 * 1024:
        raise quality.EvalError("archive batch size must be between 1 and 50 KiB")
    header = (
            f"Archived alternatives batch {index + 1} of {total}. These are genuine "
            "historical workshop alternatives supplied for the planning record. Every venue "
            "in this batch is Cafe, so these alternatives remain ineligible under the existing "
            "venue constraint; do not mix them with active options. Preserve the earlier active "
            "requirements and corrections. Acknowledge briefly; do not finalize or take actions.\n")
    lines, size, row = [], len(header.encode()), 1
    while True:
        line = (f"AR{index + 1:02}-{row:04} | {TRACKS[(row - 1) % 3]} | fee "
                    f"{(7 + row % 24) * 100_000} VND | capacity {20 + row % 45} | score "
                    f"{40 + row % 60} | venue Cafe | format "
                    f"{('guided practice', 'peer discussion', 'case review')[row % 3]}\n")
        if size + len(line.encode()) > batch_bytes:
            break
        lines.append(line)
        size += len(line.encode())
        row += 1
    return header + "".join(lines)


FINAL_PROMPT = (
    "Now finalize the workshop selection using the full active requirements and corrections "
    "already agreed in this conversation. Return the requested JSON object and required Harness "
    "status. Do not use tools, run commands, edit files, contact anyone, or book anything."
)


@dataclasses.dataclass(frozen=True)
class NativeCompactionEvidence:
    """Construct only at the native UI/event boundary, never from model prose."""
    observed: bool
    manual: bool

    def __post_init__(self):
        if type(self.observed) is not bool or type(self.manual) is not bool:
            raise quality.EvalError("native compaction evidence must contain booleans")

    @classmethod
    def native_ui_status(cls, status, manual=True):
        # Caller supplies the CLI's status notification, not a whole transcript
        # that could contain model quotations of this exact phrase.
        return cls(status == "Conversation compacted", manual)

    @classmethod
    def native_ui_boundary(cls, label, before_context_tokens, after_context_tokens):
        """Only the caller's native divider and measured context, never prose."""
        valid = (label == "Compacted" and type(before_context_tokens) is int
                 and type(after_context_tokens) is int
                 and 0 <= after_context_tokens < before_context_tokens)
        return cls(valid, False)


def valid_harness_status(text):
    """One plain status outside code fences, with both nonempty result fields."""
    lines, fence = [], None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = marker if fence is None else None if fence == marker else fence
        elif fence is None and stripped.startswith("Harness:"):
            lines.append(stripped)
    if len(lines) != 1:
        return False
    match = re.fullmatch(r"Harness:\s*([A-Z_]+)\s*;\s*passed:\s*([^;]+);\s*failed/skipped:\s*(.+)", lines[0])
    return bool(match and match[1] in quality.ROUTES and match[2].strip() and match[3].strip())

def response_object(text):
    """Accept exactly one JSON object plus Harness status; reject extra prose."""
    body = "\n".join(line for line in text.splitlines()
                     if not line.strip().startswith("Harness:")).strip()
    if body.startswith("```json\n") and body.endswith("\n```"):
        body = body[len("```json\n"):-len("\n```")]
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        return None
    return result if isinstance(result, dict) else None


def score_response(response, evidence, history=None):
    text = response.get("response", "")
    obj = response_object(text) if isinstance(text, str) else None
    obj = obj or {}
    expected = [{key: row[key] for key in ("id", "track", "fee_vnd")}
                for row in best_selection(excluded=(cancelled_id(),))]
    checks = {
        "native_compaction_observed": isinstance(evidence, NativeCompactionEvidence) and evidence.observed,
        "exact_output_shape": set(obj) == FINAL_KEYS,
        "earliest_session_label_retained": obj.get("session_label") == LABEL,
        "earliest_time_zone_retained": obj.get("time_zone") == "Asia/Ho_Chi_Minh",
        "corrected_attendee_limit": type(obj.get("attendee_limit")) is int and obj["attendee_limit"] == 32,
        "corrected_budget": type(obj.get("budget_vnd")) is int and obj["budget_vnd"] == 5_500_000,
        "optimal_active_candidates": obj.get("events") == expected
            and all(type(row.get("fee_vnd")) is int for row in obj.get("events", []) if isinstance(row, dict)),
        "approval_constraint_retained": obj.get("approval_policy") == "ask_before_booking",
        "no_messages_constraint_retained": obj.get("notification_policy") == "no_messages",
        "harness_status_present": valid_harness_status(text) if isinstance(text, str) else False,
    }
    if history is not None:
        checks["same_conversation"] = bool(history.get("same_conversation"))
        checks["no_task_tool_calls"] = history.get("task_tool_calls") == 0
        checks["no_task_subagent_steps"] = history.get("task_subagent_steps") == 0
        planned = history.get("planned_user_turns", len(planning_turns()))
        checks["all_preparation_turns_completed"] = (type(planned) is int and planned >= 12
                                                     and history.get("completed_turns") == planned)
    return {"event": "compaction_quality_score", "passed": sum(checks.values()),
            "total": len(checks), "overall_pass": all(checks.values()), "checks": checks,
            "uncompacted_behavior_diagnostic_pass": all(value for key, value in checks.items()
                                                        if key != "native_compaction_observed"),
            "manual_compaction": evidence.manual if isinstance(evidence, NativeCompactionEvidence) else None,
            "automatic_compaction_observed": bool(isinstance(evidence, NativeCompactionEvidence)
                                                    and evidence.observed and not evidence.manual)}


def native_turn(prompt, model, workspace, timeout, conversation=None, previous_turns=0,
                allow_compaction_turn_gap=False, event_observer=None):
    """Use public NDJSON; native /compact may advance its turn counter."""
    if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
        raise quality.EvalError("turn timeout must be positive and finite")
    command = ["agy", "--agent", "default", "--model", model, "--add-dir", str(workspace), "--sandbox",
               "--mode=accept-edits", "--print-timeout", str(math.ceil(timeout)) + "s",
               "-p", prompt, "--output-format", "stream-json"]
    command += ["--conversation", conversation] if conversation else ["--new-project"]
    started = time.monotonic()
    session = quality.StreamSession(command, workspace, capture_responses=True)
    session.conversation = conversation
    try:
        while True:
            event = session._event(started + timeout)
            if event is None:
                raise quality.EvalError("native session ended before result")
            if event_observer is not None:
                event_observer(event)
            if event["event"] == "init":
                if session.initialized:
                    raise quality.EvalError("duplicate native initialization")
                session._require_conversation(event.get("conversation_id"))
                session.initialized = True
            elif not session.initialized:
                raise quality.EvalError("native event before initialization")
            elif event["event"] == "step_update":
                step = event.get("step_update")
                if not isinstance(step, dict):
                    raise quality.EvalError("invalid native step")
                if "conversation_id" in step:
                    session._require_conversation(step["conversation_id"])
                session.response_steps.update(step)
            else:
                result = quality.validate_response_envelope(event.get("result"))
                session._require_conversation(result["conversation_id"])
                count = result.get("num_turns")
                if (type(count) is not int or count <= previous_turns
                        or (not allow_compaction_turn_gap and count != previous_turns + 1)):
                    raise quality.EvalError("native turn counter did not advance")
                response = session.response_steps.final_response(result)
                session.finish(timeout)
                return response, quality.safe_turn_summary(response, count, time.monotonic() - started)
    finally:
        session.close()


class NativePlanningSession:
    """One public NDJSON client per stage; permissions stay at their defaults."""

    def __init__(self, model, workspace, timeout=180, conversation=None, previous_turns=0,
                 known_failed_turns=0):
        if type(known_failed_turns) is not int or known_failed_turns not in (0, 1):
            raise quality.EvalError("at most one explicitly observed failed turn may be accounted for")
        if type(previous_turns) is not int or previous_turns < 0 or (known_failed_turns and not conversation):
            raise quality.EvalError("persistent resume requires observed native turn accounting")
        if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
            raise quality.EvalError("turn timeout must be positive and finite")
        self.model, self.workspace, self.timeout = model, pathlib.Path(workspace), timeout
        self.previous_turns, self.known_failed_turns = previous_turns, known_failed_turns
        self.first, self.closed, self.busy = True, False, False
        command = ["agy", "--agent", "default", "--model", model, "--add-dir", str(workspace),
                   "--sandbox", "--mode=accept-edits", "--print-timeout", str(math.ceil(timeout)) + "s",
                   "--input-format", "stream-json", "--output-format", "stream-json"]
        command += ["--conversation", conversation] if conversation else ["--new-project"]
        self.session = quality.StreamSession(command, workspace, capture_responses=True)
        self.session.conversation = conversation

    def __call__(self, prompt, model, workspace, timeout, conversation=None, previous_turns=0,
                 allow_compaction_turn_gap=False, event_observer=None):
        if (self.closed or self.busy or model != self.model or pathlib.Path(workspace) != self.workspace
                or previous_turns != self.previous_turns
                or (self.session.conversation is not None and conversation != self.session.conversation)):
            raise quality.EvalError("persistent stage inputs changed")
        if type(timeout) not in (int, float) or not 0 < timeout < float("inf"):
            raise quality.EvalError("turn timeout must be positive and finite")
        if allow_compaction_turn_gap:
            raise quality.EvalError("persistent stages require explicit bounded turn accounting")
        self.busy = True
        self.session.response_steps = quality.ResponseSteps()
        started = time.monotonic()
        try:
            self.session.process.stdin.write(json.dumps({"event": "user", "message": {"content": prompt}}) + "\n")
            self.session.process.stdin.flush()
        except (OSError, ValueError):
            raise quality.EvalError("persistent stage input closed") from None
        while True:
            event = self.session._event(started + timeout)
            if event is None:
                raise quality.EvalError("persistent stage ended before result")
            if event_observer is not None:
                event_observer(event)
            if event["event"] == "init":
                if self.session.initialized:
                    raise quality.EvalError("duplicate persistent initialization")
                self.session._require_conversation(event.get("conversation_id"))
                self.session.initialized = True
            elif not self.session.initialized:
                raise quality.EvalError("persistent event before initialization")
            elif event["event"] == "step_update":
                step = event.get("step_update")
                if not isinstance(step, dict):
                    raise quality.EvalError("invalid persistent step")
                if "conversation_id" in step:
                    self.session._require_conversation(step["conversation_id"])
                self.session.response_steps.update(step)
            else:
                result = quality.validate_response_envelope(event.get("result"))
                self.session._require_conversation(result["conversation_id"])
                count = result.get("num_turns")
                minimum = self.previous_turns + 1
                maximum = minimum + (self.known_failed_turns if self.first else 0)
                if type(count) is not int or not minimum <= count <= maximum:
                    raise quality.EvalError("persistent native turn counter violated its bounded plan")
                response = self.session.response_steps.final_response(result)
                summary = quality.safe_turn_summary(response, count, time.monotonic() - started)
                self.previous_turns, self.first, self.busy = count, False, False
                return response, summary

    def finish(self):
        if self.closed:
            return
        try:
            if self.busy:
                raise quality.EvalError("persistent stage has an unfinished turn")
            self.session.finish(self.timeout)
        finally:
            self.session.close()
            self.closed = True

    def close(self):
        if not self.closed:
            self.session.close()
            self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        if kind is None:
            self.finish()
        else:
            self.close()


def write_private_state(path, state):
    path = pathlib.Path(os.path.abspath(path))
    # Ignore naming is enforced even before a live run creates model history.
    if not any(part.startswith(".harness-eval.") for part in path.parts):
        raise quality.EvalError("private state must be inside an ignored .harness-eval. path")
    for ancestor in (path, *path.parents):
        if ancestor.is_symlink():
            raise quality.EvalError("private state path must not contain symlinks")
    if path.exists():
        if not stat.S_ISREG(path.stat().st_mode):
            raise quality.EvalError("private state target is not a regular file")
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise quality.EvalError("private state target is not owned by this eval") from None
        marker = existing.get("_compaction_eval_state") if isinstance(existing, dict) else None
        if type(marker) is not int or marker != 1:
            raise quality.EvalError("private state target is not owned by this eval")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Replacing our own state avoids truncating a symlink/hardlink target.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".compaction-state-", delete=False) as stream:
            temporary = pathlib.Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(dict(state, _compaction_eval_state=1), stream)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def prepare(model, workspace, state_path, timeout=180, progress=None, archive_batches=0,
            event_observer=None, turn_runner=None):
    turns = planning_turns(archive_batches)
    state = {"conversation": None, "native_turns": 0, "completed_turns": 0,
             "same_conversation": True, "task_tool_calls": 0,
             "task_subagent_steps": 0,
             "history_user_bytes": 0,
             "planned_user_turns": len(turns), "archive_batches": 0,
             "archived_user_bytes": 0,
             "turn_summaries": []}
    write_private_state(state_path, state)
    for index, prompt in enumerate(turns, 1):
        response, summary = (turn_runner or native_turn)(prompt, model, workspace, timeout, state["conversation"],
                                                        state["native_turns"], event_observer=event_observer)
        state["conversation"] = response["conversation_id"]
        state["native_turns"] = summary["turn"]
        state["completed_turns"] = index
        state["history_user_bytes"] += len(prompt.encode())
        if index > 12:
            state["archive_batches"] += 1
            state["archived_user_bytes"] += len(prompt.encode())
        state["task_tool_calls"] += sum(row["calls"] for row in summary.get("event_diagnostics", {}).get("tools", {}).values())
        state["task_subagent_steps"] += summary.get("event_diagnostics", {}).get("subagent_steps", 0)
        state["turn_summaries"].append(summary)
        write_private_state(state_path, state)
        if progress:
            progress({"completed_turns": index, "requested_turns": len(turns)})
    return state


def extend_history(state, target_archive_batches, model, workspace, state_path, timeout=180,
                   progress=None, event_observer=None, archive_plan_total=MAX_ARCHIVE_BATCHES,
                   turn_runner=None):
    """Complete an explicitly sized stage; inspect native UI between stages.

    A stage's planned count is written before execution. Partial stages therefore
    fail coverage instead of changing planned count to disguise an early stop.
    The root driver may choose the next stage only after completing this stage.
    """
    current = state.get("archive_batches")
    previous_plan = state.get("planned_user_turns")
    if (type(current) is not int or type(target_archive_batches) is not int
            or type(archive_plan_total) is not int
            or type(previous_plan) is not int or previous_plan < 12
            or target_archive_batches < previous_plan - 12
            or not 0 <= current <= target_archive_batches <= archive_plan_total <= MAX_ARCHIVE_BATCHES
            or state.get("completed_turns") != 12 + current
            or type(state.get("task_subagent_steps")) is not int or state["task_subagent_steps"] < 0):
        raise quality.EvalError("invalid completed history or archive stage plan")
    prompts = [archive_turn(index, archive_plan_total) for index in range(current, target_archive_batches)]
    if state.get("history_user_bytes", MAX_HISTORY_BYTES) + sum(len(turn.encode()) for turn in prompts) > MAX_HISTORY_BYTES:
        raise quality.EvalError("actual user history exceeds the 5 MiB limit")
    state["planned_user_turns"] = 12 + target_archive_batches
    write_private_state(state_path, state)
    for prompt in prompts:
        response, summary = (turn_runner or native_turn)(prompt, model, workspace, timeout, state["conversation"],
                                                        state["native_turns"], event_observer=event_observer)
        state["conversation"] = response["conversation_id"]
        state["native_turns"] = summary["turn"]
        state["completed_turns"] += 1
        state["archive_batches"] += 1
        size = len(prompt.encode())
        state["history_user_bytes"] += size
        state["archived_user_bytes"] += size
        state["task_tool_calls"] += sum(row["calls"] for row in summary.get("event_diagnostics", {}).get("tools", {}).values())
        state["task_subagent_steps"] += summary.get("event_diagnostics", {}).get("subagent_steps", 0)
        state["turn_summaries"].append(summary)
        write_private_state(state_path, state)
        if progress:
            progress({"completed_turns": state["completed_turns"],
                      "requested_turns": state["planned_user_turns"]})
    return state


def finish(state, evidence, model, workspace, timeout=180, diagnose_uncompacted=False,
           event_observer=None, turn_runner=None):
    if not isinstance(evidence, NativeCompactionEvidence) or (not evidence.observed and not diagnose_uncompacted):
        raise quality.EvalError("actual native compaction has not been observed")
    response, summary = (turn_runner or native_turn)(FINAL_PROMPT, model, workspace, timeout,
                                    state["conversation"], state["native_turns"],
                                    allow_compaction_turn_gap=turn_runner is None, event_observer=event_observer)
    history = dict(state)
    history["same_conversation"] = response["conversation_id"] == state["conversation"]
    history["task_tool_calls"] += sum(row["calls"] for row in summary.get("event_diagnostics", {}).get("tools", {}).values())
    history["task_subagent_steps"] = (state["task_subagent_steps"]
        + summary.get("event_diagnostics", {}).get("subagent_steps", 0)
        if type(state.get("task_subagent_steps")) is int else None)
    score = score_response(response, evidence, history)
    score.update({"history_user_bytes": state["history_user_bytes"],
                  "pre_compaction_user_turns": state["completed_turns"],
                  "post_compaction_user_turns": int(evidence.observed),
                  "evaluation_user_turns": 1,
                  "archive_batches": state.get("archive_batches", 0),
                  "archived_user_bytes": state.get("archived_user_bytes", 0),
                  "task_tool_calls": history["task_tool_calls"],
                  "task_subagent_steps": history["task_subagent_steps"],
                  "turn_summaries": state["turn_summaries"] + [summary]})
    return score


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="authorize first-party model execution")
    parser.add_argument("--model", default="gemini-3.8-flash-high")
    parser.add_argument("--workspace", type=pathlib.Path)
    parser.add_argument("--state-path", type=pathlib.Path)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--archive-batches", type=int, default=0,
                        help="optional substantive excluded alternatives, at most 80 batches of 50 KiB")
    args = parser.parse_args(argv)
    if not args.run:
        turns = planning_turns(args.archive_batches)
        print(json.dumps({"event": "compaction_eval_plan", "user_turns": len(turns),
                          "history_user_bytes": sum(len(turn.encode()) for turn in turns),
                          "requires_native_compaction_observation": True, "model_run": False}))
        return 0
    if args.workspace is None or args.state_path is None:
        parser.error("--run requires --workspace and --state-path")
    prepare(args.model, args.workspace.resolve(), args.state_path, args.timeout,
            progress=lambda row: print(json.dumps(row), flush=True), archive_batches=args.archive_batches)
    print(json.dumps({"event": "compaction_preparation_complete", "completed_turns": 12 + args.archive_batches,
                      "requires_native_compaction_observation": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
