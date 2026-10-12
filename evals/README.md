# Harness smoke evals

These opt-in evals exercise the installed harness through the first-party
Antigravity CLI. They are intentionally not part of regular CI because they
require an authenticated account, consume model quota, and are probabilistic.

Run them after installing the current plugin:

```bash
./evals/run-smoke.sh
```

The runner pins `gemini-3.8-flash-high` by default. Override it only when
comparing model profiles:

```bash
HARNESS_EVAL_MODEL=gemini-3.8-flash-medium ./evals/run-smoke.sh
```

Run one case while diagnosing an eval failure:

```bash
HARNESS_EVAL_CASE=debug-regression ./evals/run-smoke.sh
```

The manifest currently covers these language and routing surfaces:

| Case | Language | Expected route | Deterministic check |
| --- | --- | --- | --- |
| `debug-regression` | Python | `IMPLEMENT` | `python3 -m unittest -q` |
| `inline-fast-path-source` | Python | `IMPLEMENT` inline fast path | one named `unittest` method |
| `review-read-only` | Python | `REVIEW_VERIFY` | read-only response assertions |
| `local-lookup-existing-symbol` | Python | `LOCAL_LOOKUP` | exact positive symbol and location assertions |
| `review-only-conceptual` | Python | `REVIEW_ONLY` | conceptual response assertions without runtime claims |
| `nonexistent-symbol-read-only` | Python | `REVIEW_VERIFY` | required `NOT_FOUND` evidence and forbidden hallucination markers |
| `javascript-regression` | JavaScript | `IMPLEMENT` | `node --test` |
| `go-regression` | Go | `IMPLEMENT` | `go test ./...` |
| `rust-regression` | Rust | `IMPLEMENT` | `cargo test --quiet` |
| `complex-security-persistence` | JavaScript | `COMPLEX_IMPLEMENT` | `node --test` plus two required source changes |
| `multiturn-waiting-list` | Python | `IMPLEMENT` or `COMPLEX_IMPLEMENT` | 8 independent final behavior checks over 4 user turns |
| `mcp-adaptive-selection-simulated` | Python | `REVIEW_ONLY` | 5 simulated tool-selection decisions; no live MCP evidence |

Python 3 is required by the runner. Individual language cases declare their
runtime requirements; an unavailable runtime produces an explicit `[skip]`.
Selecting only unavailable cases is an error, so a partial run cannot be
mistaken for full coverage.

Each case runs in an ignored, isolated temporary git repository inside the
already-trusted source checkout, then cleanup removes it. The runner checks the
expected write behavior, the repository's deterministic verification command,
required changed paths, an explicit changed-file allowlist, required and forbidden response terms, and a `Harness:` status
line naming the expected route. Forbidden response checks are case-insensitive.
Legacy fixtures restrict agent terminal commands for headless permission
compatibility; the new waiting-list quality fixture permits focused local tests
and public-test updates. The runner also performs independent final checks. Because subagents are asynchronous, the runner resumes an incomplete
conversation up to three times.

The nonexistent-symbol case is a read-only hallucination trap. Its fixture does
not define `calculate_tax`; the response is constrained to two exact evidence
lines plus one exact `Harness:` line, so invented definitions, locations, file
changes, or extra prose fail the case.

The inline-fast-path case is a private one-file source correction with one
existing focused behavioral test. It must change only `normalize.py`, stay within
one hunk and 10 added/deleted lines, and report `mode: inline-fast-path` on the
normal `IMPLEMENT` route. The current CLI JSON envelope has no stable
subagent trace, so the case verifies scope, result, and narrow evidence while
the policy unit tests enforce that eligible tiny edits do not require subagents.

The complex case declares and runs three independently named acceptance checks:

1. `AC-1`: Only administrators can write audit entries.
2. `AC-2`: A denied write throws without mutating persistent state.
3. `AC-3`: An authorized write persists the entry.

The runner executes both the full fixture test suite and the targeted command for
each acceptance criterion. It also verifies the externally visible route marker
and required multi-file change. The policy requires independent final
review/verification, but the current CLI JSON envelope exposes no stable
subagent trace. This is therefore a behavioral proxy, not proof of exact
scheduling order. Treat one run as a smoke signal, not a stable benchmark;
compare multiple runs before changing policy.

## Output quality and requirement retention

The `multiturn-waiting-list` case starts with a natural-language feature request,
adds cancellation and serving behavior, replaces the duplicate-matching rule,
and finally adds atomic bulk registration. The user prompts do not prescribe an
acceptance ledger, workflow, subagents, test names, or implementation. The runner
sends the initial `prompt` and each optional `turns` message in the same
conversation; a changed conversation ID is an error. It scores the final
implementation against all eight final requirements, including requirements
introduced before the last turn and the replacement of the original matching rule.

The waiting-list fixture supplies ordinary tracked public tests for the initial
request, including its original case-insensitive duplicate rule. The agent may
run focused local tests and update `test_waiting_list.py` as requirements change.
The runner also executes that public suite and reports `public_verification`
separately; stale public tests must be updated, and weakened tests cannot override
the independent acceptance judges.
The allowed routes are `IMPLEMENT` and `COMPLEX_IMPLEMENT`; the score records the
reported route. Legacy cases retain their fixed expected route.

Runner-owned checks live in `evals/acceptance/`, outside the model's editable
fixture and changed-file allowlist. They exercise the public interface with
normal, boundary, and failure cases. Every criterion runs even after another
fails. Responses mentioning a requirement or claiming success cannot pass a
behavior check. Cases marked `quality_eval` run through `output_quality.py`; the
smoke runner dispatches them automatically. Legacy single-turn cases retain
their existing contracts.

Run the new case directly only after authorizing model quota use:

```bash
python3 evals/output_quality.py --case multiturn-waiting-list --confirm-quota-use
```

That case makes four model calls, one for each user message, without automatic
continuation calls. The direct quality runner refuses execution without
`--confirm-quota-use`. Running the existing opt-in smoke command also includes
these cases unless `HARNESS_EVAL_CASE` selects another case.

Each quality result is a JSON `quality_score` event with actual `passed`, `total`,
`coverage`, and a status for every criterion. Coverage here means passed/total
acceptance criteria, not source-code coverage. When the final response includes
`HARNESS_RESULT`, the runner separately reports its claimed status and
passed/total count. A `complete` claim with any independently failing criterion
sets `false_complete` and fails the case. Missing claims remain `null` for
backwards compatibility; they never become passing behavioral evidence.
These counts measure distinct things: the runner's fixed behavior criteria and
the model's self-selected requirement inventory need not have the same IDs or
grouping. The runner does not validate the model's cited tool-step evidence.

Independent scores remain available when the final response violates the
response contract (for example, a missing `Harness:` line); `success` remains
false and `response_contract_error` explains the structural failure. An invalid
completion claim is similarly reported as `completion_claim_error`. `route`
records the observed documented route, or `null` when absent. Each
`turn_summaries` entry contains its one-based turn index, CLI status, observed
route, elapsed seconds, and documented usage counters when valid. These
summaries exclude raw responses, CLI diagnostics and conversation IDs; they do
not establish tool invocation or intermediate behavioral correctness.

For multi-turn latency measurements, opt into one warmed CLI process:

```bash
python3 evals/output_quality.py --case multiturn-waiting-list \
  --session-mode stream --confirm-quota-use
```

The default `--session-mode process-events` launches one process per user turn.
`--session-mode process` retains the legacy aggregate-only JSON observer.
Stream mode sends the same prompts sequentially using the public
[Antigravity stream-input protocol](https://antigravity.google/docs/cli/headless/),
checks conversation/turn continuity, bounds each wait and closes the child on
failure. `session_mode` labels the transport. Per-turn durations are measured
with a monotonic clock; CLI usage counters are cumulative, so use the final
turn's counters instead of summing them. Compare unchanged prompts, criteria,
model and permissions; changing transport and harness together measures their
combined effect, not an isolated policy improvement.

The default `--session-mode process-events` provides final
handoff parsing and workflow diagnostics. It still starts one `-p` process per
user turn, resumes the same conversation, and consumes public NDJSON output.
It assembles `ACTIVE`/`DONE` deltas by response step and validates the last
completed handoff against the end of the terminal aggregate. Earlier Stop-hook
responses remain counted in diagnostics; duplicate claims within the final
handoff still fail. The waiting-list case also rejects a missing completion
claim. This changes the response observation method, so retain the mode when
comparing runs and never rescore older aggregate-only results silently.
The parser retains native `ERROR` steps as failures, accepts the observed
`tool` to `subagent` promotion and metadata-only completed-step refreshes, and
requires a later `DONE` response after an errored response. New nonempty text in
a repeated completed response, conflicting step types, and an action after the
final handoff remain errors.

Diagnostics retain tool call/error counts, output byte counts, durations,
initialization time, native invoker advertisement and identical-command counts.
They omit tool output, arguments, conversation IDs and command fingerprints.
An identical command can be justified after a write; its count alone does not
prove wasted work. Command categories are lexical heuristics for acceptance
metadata, tests, Git and source reads; they do not establish a command's purpose.
Only category counts are retained. Native print timeout follows the caller's
per-turn deadline.

The adaptive-MCP case supplies an artificial tool inventory, including an
unavailable tool and a later Sentry outage. It scores the structured recommended
choices, including a supplied-log fallback, and requires the artifact to identify
itself as `simulated_selection` with no contacted services. This measures tool
selection decisions under supplied conditions. It does **not** demonstrate that
an MCP was called, a tool trace was observed, or an external service worked.

CI uses deterministic fake `agy` launchers and candidate implementations to prove
that the runner preserves conversation identity, passes a complete solution,
reports 7/8 when atomic batch behavior is omitted despite an 8/8 completion claim
—even if the agent weakens the editable public tests—and rejects wrong or
invented-live selections. These tests consume no real model
quota. The [2026-10-12 live evaluation report](../docs/live-eval-2026-10-12.md)
records a real four-turn behavioral pass and separates simulated MCP selection,
server health and permission-limited model execution. One successful run is not
a stable quality or performance benchmark, and no previous-harness baseline was
measured.

The [optimization comparison](../docs/live-eval-2026-10-12-optimized.md) and
[filtered results](results/2026-10-12-optimized.json) retain the later run's
8/8 behavioral score **and overall completion-contract failure**. That sample
was slower and used more total tokens; simulated tool selection passed, while
autonomous browser execution was not demonstrated. A separate public Stop-hook
probe confirmed that CLI terminal responses can aggregate earlier and corrected
answers. It does not establish the cause of the historical duplicate claim or
change its score. The subsequent gate parser fix is identified separately from
the runtime used for the four-turn run.

The [repaired comparison](../docs/live-eval-2026-10-12-repaired.md) and
[filtered results](results/2026-10-12-repaired.json) record the final installed
build's four-turn 8/8 pass, completion-contract pass, and measured time/token
reduction. Native browser execution passed with individual Ask approvals and
zero model tool hints after operator startup-readiness inspection; its missing
Harness status line and startup confound remain explicit. Failed and interrupted
intermediate attempts remain unscored.

## Opt-in quota benchmark

`quota_benchmark.py` compares repeated runs of read-only, benchmark-enabled
cases. It is separate from the source tests and smoke runner. It refuses to call
the model unless the installed harness policy, agents, and skills match this
source tree and every invocation supplies both explicit case IDs and
`--confirm-quota-use`. Rerun the installer after changing revisions:

```bash
python3 evals/quota_benchmark.py \
  --case local-lookup-existing-symbol \
  --case review-only-conceptual \
  --repeat 3 \
  --model gemini-3.8-flash-high \
  --confirm-quota-use > benchmark.ndjson
```

That example makes six billable/quota-consuming model calls: three fresh runs
for each selected route. Use at least two repeats, keep the same model and
repeat count when comparing revisions, and inspect distributions rather than
treating one sample as proof.

This quota runner validates observable response contracts and usage, but does
not retain tool/subagent events. Its results are therefore a behavioral
proxy: a reported route is not proof that the corresponding reads or subagent
were actually invoked. Do not use this benchmark alone to change agent model
tiers. The separate output-quality runner uses public step events for bounded
workflow diagnostics; it still does not measure worker-internal costs.

Each run receives a temporary copy of its fixture in plan mode and rejects the
sample if that copy changes. The runner never modifies source fixtures, enables
permission bypasses, or inspects credential files. Its own output does not
persist or emit model responses, conversation IDs, or CLI diagnostics;
Antigravity may still retain its normal local conversation history according to
the client configuration. Standard output is NDJSON containing only case/route
metadata, status, duration, the source-harness digest, and documented `usage`
counters (`input_tokens`, `output_tokens`, `thinking_tokens`,
`cache_read_tokens`, and `total_tokens`). Both official `json` and `stream-json`
envelopes are supported:

```bash
python3 evals/quota_benchmark.py \
  --case local-lookup-existing-symbol \
  --repeat 3 \
  --output-format stream-json \
  --confirm-quota-use
```

The terminal `result.usage` field is the source of truth; intermediate stream
events are deliberately discarded. See the official
[Antigravity headless-mode contract](https://antigravity.google/docs/cli/headless/)
for field definitions. A failed or timed-out sample is reported by error type
without relaying CLI diagnostics that might contain private environment data.
