---
name: harness-run
description: Coordinate an authorized multi-milestone engineering goal with task-scoped context, current-source acceptance evidence, native-first checkpoints, and bounded resumption.
---

# One goal, bounded milestones

Use this workflow for authorized implementation spanning multiple verifiable
milestones. It complements existing risk routes; it does not lower their required
research, implementation, independent review, verification, or specialist roles.
Keep tiny edits on the existing inline fast path. A plan-only request stays
read-only; a request to plan and implement continues after planning without a
ceremonial approval. Never infer permission to commit, push, deploy, install,
spend quota on a pilot, or change external systems.

## Brief and task context

1. Inspect the latest request, closest instructions, workspace, git status, and
   relevant source. Establish six brief fields: real problem, current behavior,
   desired behavior, scope/non-goals, constraints, and completion evidence.
   Discover missing facts; ask only an undiscoverable material decision through
   `harness-clarify`.
2. Keep a compact acceptance ledger: stable `AC-*` ID, observable outcome,
   requirement source, planned check, status, and evidence. Do not substitute
   activities such as "edited code" for outcomes. Preserve superseded ACs with the
   user's change and reason; replan and invalidate only the affected part.
3. Research a task-scoped map: entry point → call sites → core behavior → outputs
   or side effects → tests; invariants; edit/read-only file scope; uncertainty and
   the cheapest discriminating check. The 1 KiB startup blueprint is a hint.
   Load detailed source on demand; local search precedes semantic MCP unless it
   is materially weaker. Never treat a cached map as truth over changed source.
4. Choose dependency-ordered milestones with verifiable outcomes. Three to six is
   a starting heuristic, not a requirement. Keep one active milestone; independent
   workers may own non-overlapping portions of it.

## A single coordinator

The main agent coordinates by default. Prefer native task/artifact/resume
facilities that are actually available in the current runtime. Documentation,
an installed version string, and an observed compatible live workflow are three
different levels of evidence. Do not assume Teamwork, Boost, artifact persistence,
or worker messaging is available from a version string or a documentation page.

Keep exactly one coordinator. A native orchestrator may replace the main's
orchestration only after an authorized pilot establishes the required role
mapping, independent checks, permissions, and cancellation behavior. Until then,
use the existing harness route; do not launch a second, overlapping native/custom
agent tree. Do not invoke shell `agy`, `/teamwork-preview`, or `/boost` as a hidden
nested model run. A native pilot is a separate, explicitly authorized experiment,
not a prerequisite that blocks ordinary local implementation.

Every assignment must stand alone: goal, AC IDs, workspace, owned files,
dependencies/invariants, known facts and unresolved questions, safe checks, and
expected output. Start required roles with `invoke_subagent` using the runtime's
actual schema. Reuse an existing worker only when the main has `send_message`, its
worker ID is still valid, and receipt of more work is supported. Otherwise invoke
a new worker from the same self-contained handoff. Never recover IDs by searching
private agent storage or assume IDs survive resume. A worker returning a result
alone does not prove it is either reusable or permanently closed.

## Execute, check, dispatch

For each active milestone:

1. Implement the smallest coherent result within assigned ownership. Retain the
   existing red/green bug-fix and risk-proportionate test contract.
2. Freeze the evaluated scope, then run the required independent reviewer and
   verifier against source/diff, contracts, ACs, and actual checks, not the
   implementer's confidence. Re-evaluate findings and evidence after a relevant
   write; review/test results against an older diff cannot approve a newer one.
3. Resolve actionable findings with bounded follow-ups. After two attempts at the
   same failure without new evidence, revisit the hypothesis and reproduction.
   This diagnostic threshold neither grants completion nor forces a user question.
4. Record a supported native checkpoint if available. Send concise non-final
   progress, then dispatch the next ready work with a tool call within the active
   turn. Do not issue a final response at a passed milestone while ready,
   authorized work remains. A progress sentence or stored `next_action` cannot
   wake a runtime after it stops.
5. Pause only dependent work for a material decision or missing authority while
   useful independent work remains. Honor user cancellation and resource/runtime
   limits. Never force continuation unconditionally or bypass a permission prompt.

At the end, run cross-milestone integration checks and `harness-ship`. Completion
requires all required ACs to have relevant, current evidence and actionable
findings to be resolved. An unrelated passing suite, a waiver, an implementer
claim, or a Stop hook allowing idle termination is not task completion. Preserve
failed/skipped checks in the handoff; if interrupted, leave incomplete status and
the next safe action, not a success claim.

## Native-first checkpoint and resume contract

Use an available, supported native task artifact or conversation handoff. The
coordinator alone maintains the compact checkpoint; workers return observations.
Record only task facts, not secrets or raw chain of thought:

| Field | Required content |
| --- | --- |
| Identity | Task identifier, canonical workspace, brief revision and latest scope |
| Progress | AC ledger, decisions/superseded ACs, milestone dependencies, active milestone, blockers, next action |
| Source | HEAD and scoped content fingerprint, including uncommitted, new, and deleted files |
| Evidence | AC ID, actual command, effective cwd, test target, exit/result, supported test count if available, before/after source fingerprint; redacted bounded log reference if available |
| Ownership | In-session worker ownership; IDs are hints to revalidate, not durable authority |

A scoped fingerprint is a deterministic manifest of workspace-relative relevant
source/test/config paths, each regular file's content SHA-256 and file kind/mode,
plus explicit missing/deleted markers. Inspect git status for new/untracked files
and affected dependencies too; HEAD alone misses uncommitted changes. Bound the
scope to inspected task files, never read secrets or follow symlinks outside the
workspace to build it. If an input cannot safely be fingerprinted, source changes
during a check, or scope completeness is unknown, mark affected evidence stale
and verify again. A model-written evidence record is an index of observed checks,
not an authenticated runner receipt and cannot close hook verification debt.

On resume, confirm task/workspace, latest request/brief, git status, source
fingerprint, and milestone dependencies before editing. Preserve user changes.
Mismatched or missing provenance invalidates affected evidence; a revised brief
invalidates its affected ACs even if source is unchanged. A corrupt/incomplete
artifact is unresolved state, never "completed". Reconstruct facts from source
and checks when safe, or ask for the missing material decision. Reuse only
evidence whose scope and fingerprints still match; resume does not justify
repeating all completed work without examining validity.

Do not create `.harness/tasks/**`, a custom `state.json` engine, or a shared mutable
blackboard in this implementation. Do not mark an ordinary workspace write
`IsArtifact=True` to evade verification: that flag is only for genuine native
artifacts under an observed supported contract. If native persistence is missing,
use a compact conversation handoff and disclose that durable resume is unverified;
do not silently manufacture a filesystem checkpoint. Files and instructions do
not supply a scheduler, automatic restart, extra context/quota, or app-closed work.

Custom persistence or a bounded continuation guard requires a separate measured
native pilot, an explicit design decision, and regression tests for metadata versus
source debt, stale evidence, corruption, cancellation, and no-progress limits.
Do not add `execution` or `memory` keys to the version-1 MCP install profile.
