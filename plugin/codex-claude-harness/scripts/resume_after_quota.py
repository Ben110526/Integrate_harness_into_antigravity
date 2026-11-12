#!/usr/bin/env python3
"""Resume one existing Antigravity conversation from a private, dated job (POSIX)."""

import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import tempfile
import threading
from datetime import datetime, timedelta, timezone


PROMPT = (
    "Continue the interrupted task in this conversation from its latest handoff. "
    "Reconcile the checkpoint, existing worker conversations and actual workspace diff. "
    "Retain the task ID, authors and completed edits. Copy unchanged requirement "
    "records verbatim, including their original sourceStep. "
    "For the new turn, advance the existing contract revision as required and refresh scope "
    "with its existing verifier. If the CLI refuses contact with that verifier, record "
    "the refusal and assign one independent replacement for scope and delivery. "
    "Obtain any missing handoff from its original owner. "
    "If the handoffs are already complete, ask the original owner to reconfirm the most "
    "recently recovered handoff. Preserve completed edits. After the last confirmation, "
    "inspect the combined diff, run the required combined checks and have the scope "
    "verifier independently review delivery against those fresh results. "
    "Report actual owners, blockers, results and observed evidence."
)
JOB_FIELDS = {"version", "workspace", "conversation", "agy", "notBefore", "resultsDirectory"}
DEFAULT_PRINT_TIMEOUT_SECONDS = 1800
WATCHDOG_GRACE_SECONDS = 60
# agy parses a signed 64-bit nanosecond duration; the Python watchdog also
# needs room for the grace period on this platform.
MAX_PRINT_TIMEOUT_SECONDS = min((2**63 - 1) // 1_000_000_000, int(threading.TIMEOUT_MAX) - WATCHDOG_GRACE_SECONDS)
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}")
QUOTA = re.compile(r"RESOURCE_EXHAUSTED|\b429\b|quota.{0,50}(?:reached|exhausted|limit)|too many requests", re.I)
RESET = re.compile(r"\b(?:resets? in|retry after|retry-after:)\s*((?:\d{1,8}\s*[dhms]\s*)+)(?!\w)", re.I)
SUCCESS = 0
INCOMPLETE = 1
BUSY = 75
INVALID = 2


def stamp(when):
    return when.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now():
    return datetime.now(timezone.utc)


def private_json(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as file:
        info = os.fstat(file.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise ValueError("unsafe private file")
        data = file.read(16385)
        if len(data) > 16384:
            raise ValueError("invalid private file")
        return json.loads(data)


def validate_job(job):
    if (not isinstance(job, dict) or set(job) - {"mode", "printTimeoutSeconds"} != JOB_FIELDS
            or type(job["version"]) is not int or job["version"] != 1):
        raise ValueError("invalid job")
    if "mode" in job and job["mode"] not in ("auto", "plan", "accept-edits"):
        raise ValueError("invalid execution mode")
    timeout = job.get("printTimeoutSeconds", DEFAULT_PRINT_TIMEOUT_SECONDS)
    if type(timeout) is not int or not 0 <= timeout <= MAX_PRINT_TIMEOUT_SECONDS:
        raise ValueError("invalid print timeout")
    if not isinstance(job["conversation"], str) or not UUID.fullmatch(job["conversation"]):
        raise ValueError("invalid conversation")
    for key in ("workspace", "agy", "resultsDirectory"):
        path = Path(job[key])
        if not path.is_absolute() or ".." in path.parts:
            raise ValueError("expected absolute path")
    if not isinstance(job["notBefore"], str):
        raise ValueError("expected UTC deadline")
    deadline = datetime.fromisoformat(job["notBefore"].replace("Z", "+00:00"))
    if deadline.tzinfo is None or deadline.utcoffset() != timedelta(0):
        raise ValueError("expected UTC deadline")
    directory = Path(job["resultsDirectory"])
    info = directory.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ValueError("unsafe results directory")
    return deadline, directory


def save_status(path, status):
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".resume-status-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as file:
            json.dump(status, file, sort_keys=True)
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)


def diagnostic(text, now=None):
    if not isinstance(text, str):
        return None, None
    if QUOTA.search(text):
        match = RESET.search(text) if now is not None else None
        if match:
            scale = {"d": 86400, "h": 3600, "m": 60, "s": 1}
            seconds = sum(int(n) * scale[unit.lower()] for n, unit in re.findall(r"(\d+)\s*([dhms])", match[1], re.I))
            if 0 < seconds <= 366 * 86400:
                return "quota", stamp(now + timedelta(seconds=seconds))
        return "quota", None
    if re.search(r"timed out|timeout|deadline exceeded", text, re.I):
        return "timeout", None
    return None, None


def claim_summary(response):
    rows = [line.partition(":")[2].strip() for line in response.splitlines()
            if line.startswith("HARNESS_RESULT:")]
    if len(rows) != 1:
        return None
    try:
        claim = json.loads(rows[0])
        criteria = claim["requirements"]
        if claim["status"] not in ("complete", "partial", "blocked") or not isinstance(criteria, list) or not criteria:
            return None
        if any(row["status"] not in ("passed", "failed", "blocked", "unverified") for row in criteria):
            return None
        passed = sum(row["status"] == "passed" for row in criteria)
        return {"status": claim["status"], "passed": passed, "total": len(criteria)}
    except (KeyError, ValueError, TypeError):
        return None


class Receipt:
    """Keep identifiers in memory and store only safe summaries of this CLI turn."""

    def __init__(self, conversation):
        self.conversation = conversation
        self.initialized = False
        self.invalid = False
        self.native_status = None
        self.claim = None
        self.step = None
        self.response = ""
        self.completed = False
        self.user_step = -1
        self.reason = None
        self.terminal_reason = None
        self.retry = None

    def observe_error(self, message, now=None):
        reason, reset = diagnostic(message, now)
        if reason and (self.reason != "quota" or reason == "quota"):
            self.reason = reason
        if reset:
            self.retry = max(self.retry or reset, reset)

    def event(self, value):
        if not isinstance(value, dict) or not isinstance(value.get("event"), str):
            self.invalid = True
            return
        kind = value.get("event")
        if kind not in ("init", "step_update", "result"):
            return  # Future CLI metadata cannot certify task or transport success.
        if self.native_status is not None:
            self.invalid = True
            return
        if kind == "init":
            if self.initialized or value.get("conversation_id") != self.conversation:
                self.invalid = True
            self.initialized = True
            return
        if not self.initialized:
            self.invalid = True
        if kind == "step_update":
            step = value.get("step_update")
            if not isinstance(step, dict):
                self.invalid = True
                return
            if step.get("conversation_id", self.conversation) != self.conversation:
                return  # A child stream must never contribute a parent response or claim.
            index = step.get("step_index")
            if step.get("step_type") == "user_input" and step.get("state") == "DONE":
                # Resuming may replay prior turns. Scope both claims and
                # provider countdowns to the latest parent user input.
                if type(index) is int and index > self.user_step:
                    self.user_step = index
                    self.reason = self.retry = None
                    self.step = None
                    self.response = ""
                    self.completed = False
            elif type(index) is int and 0 <= self.user_step < index:
                if step.get("step_type") == "error_message":
                    self.observe_error(step.get("error") or step.get("text_delta"), utc_now())
                elif step.get("tool_name") in ("invoke_subagent", "send_message"):
                    info = step.get("tool_info")
                    error = info.get("error") if isinstance(info, dict) else None
                    if isinstance(error, dict):
                        self.observe_error(error.get("message"), utc_now())
            if step.get("step_type") == "agent_response":
                delta = step.get("text_delta", "")
                if type(index) is not int or not isinstance(delta, str):
                    self.invalid = True
                    return
                if self.user_step < 0 or index <= self.user_step or (self.step is not None and index < self.step):
                    return
                if index != self.step:
                    self.step = index
                    self.response = ""
                self.response = (self.response + delta)[-131072:]
                self.completed = str(step.get("state")).upper() == "DONE"
            return
        result = value.get("result")
        if kind != "result" or not isinstance(result, dict):
            self.invalid = True
            return
        status = result.get("status")
        known = ("SUCCESS", "ERROR", "CANCELED", "INTERRUPTED", "INVALID", "WAITING", "RUNNING",
                 "FAILURE", "FAILED", "CANCELLED", "BLOCKED")
        self.native_status = status if status in known else "unknown"
        if result.get("conversation_id", self.conversation) != self.conversation or self.native_status == "unknown":
            self.invalid = True
        self.terminal_reason, _ = diagnostic(result.get("error") or result.get("error_message") or result.get("message"))
        response = result.get("response")
        if not isinstance(response, str):
            self.invalid = True
        elif self.completed and self.response.strip() and response.rstrip().endswith(self.response.rstrip()):
            self.claim = claim_summary(self.response)


def run_native(job):
    command = [job["agy"], "--sandbox"]
    timeout = job.get("printTimeoutSeconds", DEFAULT_PRINT_TIMEOUT_SECONDS)
    if "mode" in job:
        command.append("--mode=" + job["mode"])
    command += ["--print-timeout", f"{timeout}s", "--input-format", "stream-json",
                "--output-format", "stream-json", "--conversation", job["conversation"]]
    message = {"event": "user", "message": {"content": PROMPT}}
    receipt = Receipt(job["conversation"])
    with subprocess.Popen(command, cwd=job["workspace"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, start_new_session=True) as process:
        def expire():
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)

        # Drain stderr concurrently. Keep only a classified native diagnostic.
        errors = Receipt(job["conversation"])
        def read_errors():
            for line in process.stderr:
                errors.observe_error(line[:65536].decode("utf-8", "replace"))

        reader = threading.Thread(target=read_errors, daemon=True)
        reader.start()
        timer = None
        if timeout:
            timer = threading.Timer(timeout + WATCHDOG_GRACE_SECONDS, expire)
            timer.daemon = True
            timer.start()
        try:
            # Closing stdin after one message lets agy finish the turn and exit.
            try:
                with process.stdin as stdin:
                    stdin.write((json.dumps(message) + "\n").encode("utf-8"))
            except BrokenPipeError:
                receipt.invalid = True
            for line in process.stdout:
                if not line.strip():
                    continue
                try:
                    receipt.event(json.loads(line))
                except (ValueError, TypeError, RecursionError):
                    receipt.invalid = True
            code = process.wait()
            reader.join()
        finally:
            if timer is not None:
                timer.cancel()
    ok = not receipt.invalid and receipt.native_status == "SUCCESS" and code == 0
    reason = None
    sources = (("currentStep", receipt.reason), ("stderr", errors.reason), ("terminal", receipt.terminal_reason))
    diagnostics = {source: value for source, value in sources if value}
    if not ok:
        reason = next(iter(diagnostics.values()), None)
        if reason is None:
            if receipt.invalid:
                reason = "invalid_stream"
            elif receipt.native_status is None:
                reason = "missing_result"
            else:
                reason = "cli_failure"
    status = {"state": "finished" if ok else "interrupted", "nativeStatus": receipt.native_status,
              "cliExit": code, "reason": reason, "claim": receipt.claim}
    if receipt.claim is not None and not receipt.invalid:
        status["claimStep"] = receipt.step
    if diagnostics and not ok:
        status["diagnostics"] = diagnostics
    if reason == "quota" and receipt.retry and not receipt.invalid:
        status["retryNotBefore"] = receipt.retry
    return status


def execute(job_file):
    import fcntl

    job = private_json(job_file)
    deadline, directory = validate_job(job)
    key = hashlib.sha256(json.dumps(job, sort_keys=True).encode()).hexdigest()
    status_file = directory / "status.json"
    lock = os.open(directory / ".resume.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(lock, "r+b") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return "active", BUSY
        try:
            saved = private_json(status_file)
        except FileNotFoundError:
            pass
        else:
            if not isinstance(saved, dict) or saved.get("job") != key:
                raise ValueError("results belong to another job")
            cli_exit = saved.get("cliExit")
            if (saved.get("state") == "finished" and saved.get("nativeStatus") == "SUCCESS"
                    and type(cli_exit) is int and cli_exit == 0):
                return "finished", SUCCESS
            return "reconcile_previous_attempt", INCOMPLETE
        if utc_now() < deadline:
            return "scheduled", SUCCESS
        if not Path(job["workspace"]).is_dir() or not os.access(job["agy"], os.X_OK):
            return "workspace_or_cli_unavailable", INVALID
        # Record before spawning: a crash cannot cause another dispatch on relaunch.
        record = {"version": 1, "job": key, "started": stamp(utc_now()), "state": "submitted"}
        save_status(status_file, record)
        try:
            result = run_native(job)
        except OSError:
            result = {"state": "interrupted", "reason": "execution_error"}
        record.update(result, ended=stamp(utc_now()))
        save_status(status_file, record)
        return record["state"], SUCCESS if record["state"] == "finished" else INCOMPLETE


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job", type=Path)
    args = parser.parse_args()
    try:
        state, code = execute(args.job)
    except (OSError, ValueError, TypeError, KeyError, ImportError, OverflowError):
        state, code = "invalid_or_unavailable_job", INVALID
    print(json.dumps({"state": state}))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
