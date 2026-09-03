# Phase 1: coding capabilities without external credentials

Phase 1 adds local, bounded support for documentation, security, database design,
architecture work, migrations, benchmarking, lifecycle safety and IDE entrypoints.
It does not add a credential-bearing service, production access or autonomous CI.

## Specialized agents

- `harness-documenter` updates relevant README/API documentation and the
  `[Unreleased]` section of `CHANGELOG.md` only when its parent assigns ownership
  of those files. It preserves generated API files and existing project
  conventions; it does not add docstrings mechanically to every function.
  Changelog entries follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
- `harness-security-auditor` performs read-only threat-boundary, OWASP, secret and
  dependency review. A missing scanner is reported as skipped, never as a pass;
  the agent does not install tools or remediate findings unless explicitly asked.
- `harness-db-architect` reviews schemas, indexes and migrations for correctness,
  locking, rollback and data-loss risk. It must not connect to production or apply
  a migration; read-only local/development inspection requires an explicitly
  assigned scope.

The routing policy invokes an agent only when its specialty materially helps the
request. Their output remains advisory unless the user requested implementation.

## Skills and slash commands

- `/harness-migration` inventories compatibility and breaking changes, then
  proposes independently reviewable migration slices. It does not create or push
  pull requests by itself.
- `/harness-adr` records context, considered options, decision and consequences in
  the repository's existing ADR convention, defaulting to `docs/adr/` only when no
  convention exists.
- `/harness-benchmark` requires a reproducible baseline and candidate measurement
  with warm-up, repetitions and environment metadata; it distinguishes measured
  results from estimates.

## Lifecycle protections

The PreToolUse DLP gate inspects file-write and terminal payloads for high-confidence
private keys and credentials before execution. High-confidence exposure and an
explicit attempt to commit, print or transmit a sensitive `.env` file are denied.
JWTs, generic secret assignments and operations that cannot be inspected safely
require human review. The reason is redacted and never prints the matched value.
For a clean matched tool call, the hook returns `ask`, which respects an existing
permission grant but never grants one itself. This also means review is interactive:
headless mode cannot answer a new permission prompt safely.
This gate is a guardrail, not a substitute for a secret manager, least-privilege
credentials or repository secret scanning.
Broad PII pattern matching is intentionally excluded because source code and test
fixtures create too many false positives; sensitive-data review remains routed to
the security auditor when the task crosses a real data boundary.

On the first invocation, bounded `PreInvocation` auto-context reads known, size-
limited manifests and workspace markers, identifies supported frameworks, and
probes runtime versions with short timeouts. It also reports recognized workspace
topology and candidate test/build/check commands. Only fixed topology labels and
shell-safe, allowlisted package-script or Make-target names are included; script
bodies and build recipes are not copied into model context. The resulting summary
is advisory, ephemeral, and no larger than 1 KiB. It does not execute the candidate
checks, run installers, contact external services, or read secret files.
Antigravity's supported hook events and decision contract are documented in
[Hooks](https://www.antigravity.google/docs/hooks/).

Auto-format is disabled by default. Set `HARNESS_AUTO_FORMAT=1` before starting a
new `agy` session only for a trusted repository: project formatter binaries,
plugins and configuration can execute code. For one successfully edited file,
the hook may use configured project-local Prettier, configured `ruff`/`black` from
`PATH`, or `gofmt`. It uses a per-file lock and five-second formatter timeout, never
downloads packages, and fails open; formatting is not evidence that verification
passed.

The Stop hook applies verification by changed scope. Logic-file writes and terminal
mutations with unknown target scope require a later behavioral test or regression
check. Documentation and known non-code mechanical edits may use a successful
static check. If no relevant check can run, the agent must print
`HARNESS_NO_RUNNABLE_CHECK: <specific reason>` with a successful, non-redirected
print command and disclose the waiver in its final response. A waiver is not a
pass. To avoid trapping a session, the hook issues at most one reminder before it
fails open; it never executes a project command itself.

For complex or multi-constraint changes, workflow skills maintain an acceptance
ledger with stable `AC-*` IDs and carry each ID through implementation, review,
verification, and handoff. Bug fixes prefer a focused red-state reproduction before
product edits and the exact same check after the fix; unsafe or infeasible red-state
execution must be explained and replaced with the strongest feasible falsification
evidence. The smoke suite also includes a read-only nonexistent-symbol case that
requires `NOT_FOUND` and rejects invented definitions, locations, or file changes.

## VS Code tasks

Run **Terminal → Run Task** to select:

- `Harness: Antigravity (interactive)`;
- `Harness: Doctor`;
- `Harness: Deterministic source checks`;
- `Harness: Interactive read-only review`.

All tasks are manual and run in the workspace. The review task starts an interactive
sandboxed plan-mode session so the user can answer permission prompts; it never
passes `--dangerously-skip-permissions`. Doctor requires Bash; on Windows, install
Git for Windows and ensure `bash.exe` is on `PATH`. The deterministic-check task
uses Windows PowerShell plus `python` and runs both unit and installer fixtures.
See [VS Code Tasks](https://code.visualstudio.com/docs/debugtest/tasks) and
[Antigravity CLI](https://antigravity.google/docs/cli/).

Keybindings are user-scoped, so this repository does not install one. Add a rule
like this to the user `keybindings.json`, choosing an unused key for the machine:

```jsonc
{
  "key": "ctrl+alt+a",
  "command": "workbench.action.tasks.runTask",
  "args": "Harness: Antigravity (interactive)"
}
```

See [VS Code keybindings](https://code.visualstudio.com/docs/configure/keybindings).

## Explicitly deferred

- Database, GitLab and Bitbucket MCP profiles remain opt-in until an operator
  supplies a least-privilege development endpoint and credentials outside Git.
- Docker MCP is deferred because access to the Docker socket is a privileged
  control surface; local Docker diagnosis remains CLI-first.
- AI review in CI is deferred until a trusted-trigger, restricted-token design is
  implemented. No workflow in Phase 1 consumes an Antigravity credential.
