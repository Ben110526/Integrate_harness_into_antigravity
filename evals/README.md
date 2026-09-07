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
| `long-workflow-intake` (separate quota opt-in) | Python | `COMPLEX_IMPLEMENT` | three dependent milestones, three named AC checks, protected dirty user file |

Python 3 is required by the runner. Individual language cases declare their
runtime requirements; an unavailable runtime produces an explicit `[skip]`.
Selecting only unavailable cases is an error, so a partial run cannot be
mistaken for full coverage.

Each case runs in an ignored, isolated temporary git repository inside the
already-trusted source checkout, then cleanup removes it. The runner checks the
expected write behavior, the repository's deterministic verification command,
required changed paths, an explicit changed-file allowlist that protects tests
and manifests, required and forbidden response terms, and a `Harness:` status
line naming the expected route. Forbidden response checks are case-insensitive.
Most fixtures disable agent terminal commands; the inline-fast-path and long
workflow fixtures explicitly request their existing focused checks, subject to
normal permission review. The runner also verifies outcomes independently; it
does not grant command permissions or bypass the sandbox. The runner resumes an
incomplete conversation up to three times. These are **runner-supplied prompts**,
not evidence that the model continued autonomously.

Each `[metrics]` record reports `runner_continuations`, independent per-AC
outcomes (all are attempted even if one fails), preserved preexisting changes,
and `unassisted_completion`. A passing suite cannot hide a missing or failed AC.
Only a passing case with zero runner continuations counts as unassisted. This
does not prove native milestone scheduling, absence of human interventions, or
resume correctness. Unavailable trace fields (permission prompts, user nudges,
decision questions, repair rounds, native resume, and usage) are `null`, not zero.
Set `HARNESS_EVAL_METRICS_PATH` to append these response-free records as NDJSON.
Use `HARNESS_EVAL_MAX_CONTINUATIONS=0` to measure a single initial prompt strictly;
the supported range is 0–3. Early CLI/envelope failures are recorded as failures.
Non-`SUCCESS` terminal statuses are never automatically continued, including
error or cancellation statuses; this is not proof of native cancellation handling.

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

## Long-workflow pilot (bounded smoke; full protocol pending)

See the [2026-09-07 live verification report](../docs/live-verification-2026-09-07.md)
for observed successes, the initial strict-contract failure, and limitations.
These samples do not replace the matched repeated/native-resume protocol below.

`long-workflow-intake` implements validated parsing → atomic inventory persistence
→ an integrated report. Each milestone has an exact named `unittest` AC check.
The runner adds a known user edit to `operator_notes.md` **after** the fixture's
baseline commit, then checks byte-for-byte preservation independently of the
changed-file allowlist. Tests, manifests, and instructions remain protected.
This is a compact behavioral proxy for a longer task, not a context-window or
native interruption benchmark. Source-test runs use a fake CLI and consume no
model quota.

The long case is skipped in a default smoke run. Explicit quota authorization is
required, and installed policy/agents/skills plus hook/adapter code must match
the source revision:

```bash
HARNESS_EVAL_CASE=long-workflow-intake \
HARNESS_EVAL_CONFIRM_QUOTA_USE=1 \
HARNESS_EVAL_MAX_CONTINUATIONS=0 \
HARNESS_EVAL_MODEL=gemini-3.8-flash-high \
HARNESS_EVAL_METRICS_PATH=/absolute/path/candidate.ndjson \
./evals/run-smoke.sh
```

Do not run this until the user authorizes real model quota and any required
installation. A baseline/candidate pilot should use the **same eval runner,
fixture, brief, model at High, CLI version, platform, permission grants, and MCP
profile**, changing only the installed harness under comparison. Keep the eval
files identical on both checkouts if the baseline predates this case, and record
the exact source revisions and reported behavior digest, which includes
policy/agent/skill files, hook definitions, and hook/adapter code. Install
each revision only with authorization; do not install automatically in a loop.
Run at least three fresh samples per revision (six initial calls total with
continuations disabled). Report every failure and median/range of duration, AC
pass counts, all-AC completion rate, and unassisted-completion rate. If assisted
retries are measured separately, keep the same cap and include their extra quota
and counts. Three repeats are a pilot, not a reliability guarantee.

Native interruption/resume, task cancellation, mid-task requirement changes,
and user source edits remain a **manual integration protocol**:

1. In an isolated fixture copy, record the brief, all AC, current diff, model,
   permissions, and native workflow availability. Do not alter the original repo.
2. Interrupt during M2 using the supported native UI; verify cancellation stops
   execution. Record the observed milestone/artifact before resuming.
3. Preserve an added user source edit, resume through the native client, and check
   that evidence affected by that edit is invalidated and refreshed. In a separate
   trial change one AC explicitly and check that superseded requirements remain
   traceable rather than silently deleted.
4. Re-run each still-required named AC independently and inspect the final diff;
   record human nudges and permission prompts separately. A final marker or a
   passing unrelated suite is insufficient. Repeat the same protocol on both
   revisions; mark unavailable telemetry/checks as untested.

The smoke runner's `--conversation` retry is not this protocol and does not prove
native `/resume`, worker reuse, `/teamwork-preview`, or continuation after app
closure. No autonomous scheduler, automatic installer, or quota-spending pilot
is enabled by this repository update.

## Opt-in quota benchmark

`quota_benchmark.py` compares repeated runs of read-only, benchmark-enabled
cases. It is separate from the source tests and smoke runner. It refuses to call
the model unless the installed harness policy, agents, skills, hook definitions,
and hook/adapter code match this
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

The runner validates observable response contracts and usage, but the current
CLI exposes no stable tool/subagent trace. Results are therefore a behavioral
proxy: a reported route is not proof that the corresponding reads or subagent
were actually invoked. Do not use this benchmark alone to change agent model
tiers; add trace validation if the CLI exposes it in a future stable contract.

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
