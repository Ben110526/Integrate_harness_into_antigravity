# Harness smoke evals

These opt-in evals exercise the installed harness through the first-party
Antigravity CLI. They are intentionally not part of regular CI because they
require an authenticated account, consume model quota, and are probabilistic.

Run them after installing the current plugin:

```bash
./evals/run-smoke.sh
```

The runner pins `gemini-3.7-flash-high` by default. Override it only when
comparing model profiles:

```bash
HARNESS_EVAL_MODEL=gemini-3.7-flash-medium ./evals/run-smoke.sh
```

Run one case while diagnosing an eval failure:

```bash
HARNESS_EVAL_CASE=debug-regression ./evals/run-smoke.sh
```

The manifest currently covers these language and routing surfaces:

| Case | Language | Expected route | Deterministic check |
| --- | --- | --- | --- |
| `debug-regression` | Python | `IMPLEMENT` | `python3 -m unittest -q` |
| `review-read-only` | Python | `REVIEW_VERIFY` | read-only response assertions |
| `local-lookup-existing-symbol` | Python | `LOCAL_LOOKUP` | exact positive symbol and location assertions |
| `review-only-conceptual` | Python | `REVIEW_ONLY` | conceptual response assertions without runtime claims |
| `nonexistent-symbol-read-only` | Python | `REVIEW_VERIFY` | required `NOT_FOUND` evidence and forbidden hallucination markers |
| `javascript-regression` | JavaScript | `IMPLEMENT` | `node --test` |
| `go-regression` | Go | `IMPLEMENT` | `go test ./...` |
| `rust-regression` | Rust | `IMPLEMENT` | `cargo test --quiet` |
| `complex-security-persistence` | JavaScript | `COMPLEX_IMPLEMENT` | `node --test` plus two required source changes |

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
Agent terminal commands are disabled in the fixtures so headless runs do not
require broad permission bypasses; the runner performs deterministic checks
itself. Because subagents are asynchronous, the runner resumes an incomplete
conversation up to three times.

The nonexistent-symbol case is a read-only hallucination trap. Its fixture does
not define `calculate_tax`; the response is constrained to two exact evidence
lines plus one exact `Harness:` line, so invented definitions, locations, file
changes, or extra prose fail the case.

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
  --model gemini-3.7-flash-high \
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
