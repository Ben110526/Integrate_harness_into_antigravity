#!/usr/bin/env python3
"""Loopback fixture and independent scoring for interactive native MCP QA.

This module never starts an MCP client, answers Ask prompts, or changes settings.
The operator launches a fresh first-party session and approves scoped calls once.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import secrets
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def prompt_for(url):
    return (
        f"Check this registration page as a visitor: {url}. Report its initial status text, "
        "press Confirm registration, then report the exact confirmation text shown on the "
        "rendered page. Verify through the rendered page and actual button interaction; "
        "do not read server files or call page APIs directly. This is read-only QA; do not "
        "edit files or run commands."
    )


class BrowserProbe:
    def __init__(self, state_path=None):
        self.token = "CONFIRM-" + secrets.token_hex(12)
        self.hits = []
        self.state_path = pathlib.Path(state_path) if state_path else None
        self.lock = threading.Lock()
        probe = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                with probe.lock:
                    probe.hits.append({"path": self.path,
                                       "browser": "Chrome" in self.headers.get("User-Agent", "")})
                    probe.save_state()
                if self.path == "/":
                    body = b'''<!doctype html><html><head><title>Registration QA</title></head>
<body><h1>Registration status</h1><p id="status">Waiting for confirmation</p>
<button id="confirm">Confirm registration</button><script>
document.getElementById('confirm').onclick = async () => {
 document.getElementById('status').textContent = (await (await fetch('/confirmation')).json()).confirmation;
};</script></body></html>'''
                    kind = "text/html; charset=utf-8"
                elif self.path == "/confirmation":
                    body = json.dumps({"confirmation": probe.token}).encode()
                    kind = "application/json"
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", kind)
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_port}"
        self.thread = None
        self.save_state()

    def save_state(self):
        if self.state_path:
            self.state_path.write_text(json.dumps({"token": self.token, "hits": self.hits,
                                                   "url": self.url}) + "\n", encoding="utf-8")
            self.state_path.chmod(0o600)

    def start(self):
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        return self

    def close(self):
        if self.thread:
            self.server.shutdown()
            self.thread.join(timeout=2)
        self.server.server_close()


def score_report(report, token, hits):
    """Score only the final handoff; callers must not supply thoughts/tool output."""
    if not isinstance(report, str) or not isinstance(token, str) or not token:
        raise ValueError("a final report and nonempty fixture token are required")
    visible, fence = [], None
    for line in report.splitlines():
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = marker if fence is None else None if fence == marker else fence
        elif fence is None:
            visible.append(stripped)
    lines = [line for line in visible if line.startswith("Harness:")]
    match = re.fullmatch(
        r"Harness: REVIEW_VERIFY; passed: ([^\n;]+); failed/skipped: ([^\n]+)",
        lines[0]) if len(lines) == 1 else None
    status_valid = bool(match and all(field.strip() for field in match.groups()))
    joined = "\n".join(visible)
    checks = {
        "initial_text_correct": "Waiting for confirmation" in joined,
        "confirmation_correct": token in joined,
        "browser_page_hit": any(h.get("path") == "/" and h.get("browser") is True for h in hits),
        "browser_confirmation_hit": any(h.get("path") == "/confirmation" and h.get("browser") is True for h in hits),
        "harness_status_valid": status_valid,
    }
    return {"event": "native_browser_quality_score", **checks,
            "behavior_passed": all(checks[k] for k in checks if k != "harness_status_valid"),
            "success": all(checks.values()), "worker_independence_verified": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", type=pathlib.Path, required=True,
                        help="private local state file; never commit its random token")
    args = parser.parse_args()
    if not args.state.parent.is_dir() or args.state.exists():
        parser.error("state needs an existing parent and a new file path")
    with tempfile.TemporaryDirectory(prefix="harness-cold-browser-") as directory:
        workspace = pathlib.Path(directory)
        (workspace / "AGENTS.md").write_text(
            "Read-only browser QA. Do not edit files or run commands. Use the rendered "
            "page and actual button interaction to establish behavior.\n", encoding="utf-8")
        probe = BrowserProbe(args.state)
        print(json.dumps({"event": "probe_server_ready", "url": probe.url,
                          "workspace": str(workspace), "prompt": prompt_for(probe.url)}), flush=True)
        try:
            probe.server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            probe.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
