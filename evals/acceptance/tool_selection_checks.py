#!/usr/bin/env python3
"""Score an explicit simulated selection artifact, never tool-execution claims."""
import json
import sys

EXPECTED = {
    "local_symbol": "local_search",
    "framework_api": "harness-context7",
    "production_error": "harness-sentry",
    "rendered_page": "harness-playwright",
    "sentry_unavailable": "supplied_logs",
}


def check_selection(text, criterion):
    lines = [line.partition(":")[2].strip() for line in text.splitlines() if line.startswith("TOOL_SELECTION:")]
    if len(lines) != 1:
        raise ValueError("missing or duplicate selection artifact")
    payload = json.loads(lines[0])
    assert payload.get("evidence_kind") == "simulated_selection"
    selections = payload.get("selections")
    assert isinstance(selections, dict) and set(selections) == set(EXPECTED)
    assert payload.get("services_contacted") == [], "simulation cannot claim live service evidence"
    assert selections[criterion] == EXPECTED[criterion]


if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8") as handle:
        check_selection(json.load(handle)["response"], sys.argv[2])
