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
