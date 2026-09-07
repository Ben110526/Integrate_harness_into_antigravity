# One goal, multiple milestones

The harness now supplies an instruction-level workflow for authorized tasks that
span several independently verifiable outcomes. `harness-run` adds a brief,
task-scoped source context, milestone dispatch, and a native-first handoff/resume
contract. It does not add a daemon, model gateway, custom task-state engine, or
unconditional continuation hook.

## Use it

Ask normally, or use the optional skill:

```text
/harness-run Implement validated imports, persistence, and an end-to-end test.
Current behavior: malformed rows are accepted and errors are not reported.
Expected behavior: reject malformed input and preserve valid records.
Scope: the local import module, its tests, and operator documentation.
Constraints: keep the public API and existing user changes; no install/push/deploy.
Complete when the rejection, persistence, and end-to-end ACs have current evidence.
Plan and implement; continue across ready milestones without asking me to say next.
```

You do not need to specify internal agent names or divide the work into prompts.
The policy selects this workflow for multi-milestone implementation. A planning-
only request remains read-only; an eligible tiny change retains its existing
single-check fast path. Medium and large work retains the required research,
implementation, independent review, verification, and applicable specialist roles.

The coordinator discovers missing facts from source before asking a material
decision. It records the problem, current/desired behavior, scope, constraints, and
completion evidence. Stable `AC-*` IDs bind outcomes to checks and keep the reason
when the user supersedes a requirement. The task map traces behavior and invariants,
not every file in the repository; the existing 1 KiB startup hint is unchanged.

One milestone is active at a time. Independent parts may have separate workers
with explicit file ownership and standalone assignments. After a stable milestone
passes its relevant checks, the coordinator emits non-final progress and dispatches
the next ready work in the active turn. It must not call the whole task complete
while a required AC remains unverified, even if some other suite passed.

## What a checkpoint means

Prefer a supported native artifact. Only the coordinator maintains the task
handoff; independent reviewers receive requirements, source, and diff, not a
trusted "verified" label from an implementer. If the current runtime lacks a
supported persistent artifact, use a compact conversation handoff and disclose
that durable restoration has not been established.

Keep the task/workspace identity, brief revision, AC ledger and decisions,
milestones/dependencies, blockers, next action, source provenance, and evidence
references. Evidence records include the actual command, effective cwd, test
target, result, and source fingerprint before/after the check. Test count is known
only when the runner/integration actually establishes it; absence of a zero-test
message is not proof that tests ran.

A fingerprint covers the inspected source/test/config scope using relative paths,
content SHA-256, kind/mode, and explicit missing/deleted markers. Include relevant
uncommitted and new/untracked files and recheck dependencies; a Git HEAD alone
does not identify a working tree. Do not follow paths outside the workspace or
read secrets for a fingerprint. Missing, unsafe, incomplete, or mismatched
provenance leaves evidence stale rather than allowing a pass. These are workflow
requirements for recording observed evidence, not a new authenticated receipt
format or automated snapshot tool.

On resume, inspect the latest request, workspace, brief, git status, fingerprints,
and dependencies before modifying files. Preserve user edits. Revalidate affected
ACs when either source or requirements changed; reuse only evidence that still
matches. Invalid/corrupt artifacts are incomplete state, not success. Worker
messaging is a conditional optimization: verify the main's message tool and the
worker's live ID/ability to receive work, otherwise create a fresh worker from its
self-contained assignment.

Do not create `.harness/tasks/**` or pretend ordinary workspace files are native
artifacts to avoid the hook. A future custom checkpoint implementation must first
prove that metadata does not clear source debt or reset continuation limits,
while source/config edits still create debt. No blanket `.harness/**` or JSON
exemption is introduced.

## Native capabilities and verification status

The following distinguishes public documentation from host availability and live
compatibility. Documentation was checked on 2026-09-07; it does not establish that
your installed CLI, plan, or plugin combination supports every feature.

| Capability | Publicly documented behavior | Harness integration status |
| --- | --- | --- |
| Teamwork | `/teamwork-preview` is a paid-plan workflow with a brief approval phase, milestone coordination, artifacts, and independent verification. [Google Teamwork](https://antigravity.google/docs/teamwork) | Candidate for a separately authorized pilot; no automatic switch or second orchestrator is installed. |
| Boost | `/boost` uses multi-agent reasoning and verification for difficult engineering problems. [Google Boost](https://antigravity.google/docs/boost) | Optional native experiment, not needed for ordinary milestone work. |
| Resume | `/resume` chooses a conversation; `agy -c` starts from the last conversation associated with the workspace. [Google Resume](https://antigravity.google/docs/cli/commands/resume/) | Conversation restoration is not source/evidence validation; the workflow requires reinspection. |
| Worker reuse | An idle worker may receive a message and retain context; a killed worker cannot. [Google Subagents](https://antigravity.google/docs/subagents) | Reuse is conditional on observed tools/IDs; a new worker is the fallback. |

On the development Mac, `agy --version` reported `1.1.26` and `agy --help`
advertised `--continue`/`-c`, `--conversation`, `--effort high`, and print/JSON
options on 2026-09-07. Those non-model probes do not establish account entitlement
or Teamwork compatibility. An installed version or help output is only a host
capability observation. Neither that nor passing deterministic repository tests proves live milestone dispatch,
cancellation, artifact persistence, or interrupt/resume compatibility. Later
authorized CLI `1.1.27` smoke samples are recorded in
[the live verification report](live-verification-2026-09-07.md). These bounded
observations do not establish the full pilot protocol below.

To reopen work, use `/resume` in Antigravity's own CLI, or run `agy -c` from your
host terminal outside an active agent run. Confirm the workspace and chosen
conversation. Do not make an agent recursively launch `agy` to continue itself.
A stopped runtime, app shutdown, user cancel, or exhausted quota cannot be fixed
by a progress message or a `next_action` field. Permission approval remains a
separate security control, not a continuation prompt to optimize away.

## Gated native pilot

Run this only after explicit permission for model quota and the test workspace.
Ordinary local implementation need not wait for it.

1. Use an isolated fixture/worktree with known source revision and preserved
   pre-existing user edits. Record the source checkout and where results return;
   do not accept a native default directory as the intended target without checking.
2. Keep one orchestration owner. Compare the baseline harness coordinator with
   candidate native orchestration separately, on the same model, fixture, rights,
   and environment. Native must demonstrate equivalent required roles and
   independent checks before replacing the custom coordinator; do not stack both
   trees and count duplicate work as an improvement.
3. Exercise three dependent milestones, an interrupted second milestone, a user
   source edit before resume, a changed AC, missing worker messaging/stale worker
   ID, one failing required AC despite another passing suite, and explicit cancel.
   Keep tiny-edit and plan-only controls. Resume must retain the right goal,
   preserve user edits, and invalidate stale evidence without repeating valid work.
4. Record observed tool dispatch at milestone boundaries, completion of every AC,
   user `continue` prompts, actual decision questions, permission prompts separately,
   resume correctness, elapsed time, non-progress repair rounds, and token usage
   only if the runtime reports it. Missing trace means dispatch/reuse is unverified,
   not automatically passed. Fake CLI tests cannot establish model behavior.
5. Repeat at least three matched runs; report each failure plus median/range. The
   pilot target is no milestone `continue` prompts without lower AC success or
   higher false completion. Three runs are preliminary, not a reliability guarantee.

Only after a measured gap should the project consider a custom persistence
adapter or bounded lifecycle continuation guard. That requires tests for exact
metadata classification, corrupted state, workspace/path safety, stale evidence,
concurrent updates, cancellation, resource exhaustion, and a no-progress counter
that is not reset by a checkpoint. No version-1 MCP configuration keys or global
policy safety boundaries are relaxed to fit this feature.
