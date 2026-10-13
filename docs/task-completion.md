# Task completion contract

The harness separates the user's requested outcomes from observed delivery. An agent that has verified two of four requirements must report **2/4, partial**. A successful test command alone does not establish that all requested behavior exists.

## Preserve the task across turns

Use the cumulative user intent for the active task, including earlier requirements, constraints, accepted clarifications and authorization. A follow-up adds or refines work unless it explicitly replaces or cancels it. Progress questions, incidental questions, compaction and a shortened transcript do not erase outstanding requirements or turn a partial result into complete. Answer a status question and continue the same task when authorized.

Keep a stable ASCII `taskId` and sequential positive `revision` numbers. Retrieve prior conversation evidence when available and carry unchanged criteria from hook state; disclose inaccessible context and unresolved scope instead of inventing missing requests. A later transcript tail may omit the source of an already registered, unchanged row. This does not require deleting or rewording that row.

A read-only status reply needs no new contract. If execution resumes or a fresh completion result is emitted after a new user record, acknowledge that record with the next cumulative revision and renew the reviews and evidence. This prevents an additive instruction from passing under a superseded inventory.

## Register acceptance before product edits

For implementation outside the strict inline fast path, main maps every explicit requirement and constraint to stable `AC-*` IDs. Each acceptance criterion describes observable behavior, including error paths or constraints when requested. Preserve requirements without omission or dilution; do not substitute a simpler feature. `verification` is `behavioral` for executable behavior and `static` for static acceptance.

Main uses Antigravity's `write_to_file` with `IsArtifact: true` to create an artifact named `harness-task-contract.json`. Its `CodeContent` is JSON:

```json
{
  "version": 2,
  "taskId": "signup-1",
  "revision": 1,
  "requirements": [
    {
      "id": "AC-1",
      "request": "validate the email",
      "acceptance": "Invalid email input is rejected with a visible validation error.",
      "verification": "behavioral",
      "sourceStep": 3
    }
  ]
}
```

`request` must be an exact substring of its originating accessible user record, identified by the observed integer `sourceStep`. It may quote an earlier turn of the same task. Use concise relevant excerpts and exclude credentials or private configuration. Never guess a source step or reconstruct an unavailable quote. The hook observes registration from the tool call; a file written only through an unobserved shell command does not register the contract.

For revisions of the same task, keep every unchanged row intact, increment `revision` by exactly one, and append newly discovered explicit requirements with fresh IDs. A missing criterion may be appended in the same user turn only before the first task product write; do not hide an omission by changing the ledger after implementation. Preserve the complete inventory through implementer, reviewer and verifier handoffs.

Revising or dropping an existing criterion requires an explicit instruction in a later user turn and a `scopeChanges` entry for each affected old ID, such as `{"id":"AC-2","request":"drop the confirmation email"}`. Its `request` is an exact quote from that latest user record. The revised criterion remains in `requirements`; a dropped criterion is absent from the active inventory. IDs of retired criteria are never reused. Unchanged IDs cannot be weakened silently, and an unrelated new prompt cannot clear outstanding criteria. Scope history is bounded to 128 entries; exceeding the bound requires a truthful partial result and an explicit user-authorized task replacement rather than silently evicting history.

An in-session version-1 upgrade also preserves all existing rows: add `sourceStep` equal to the legacy contract's `userStep`, assign a stable task ID, and start revision 1. The same explicit scope-change rules apply to alterations; upgrading cannot erase outstanding criteria or failed checks.

Switch tasks only when the user explicitly requests replacement. The first contract for the new `taskId` has `revision: 1` and `replacesTask: {"taskId":"signup-1","request":"stop signup work and fix the export instead"}`, quoting the latest user instruction exactly. Do not interpret a status question as a replacement. Version 1 contracts remain supported for legacy sessions; new work uses version 2 for task continuity and review reports.

## Independently review full coverage before writes

Before implementation outside the inline fast path, invoke an independent reviewer with the cumulative user request, full contract and relevant source contracts. The reviewer checks every requested outcome, constraint and error path against the acceptance inventory, identifies omissions or dilution, and returns explicit coverage. For normal low-risk `IMPLEMENT`, the independent verifier owns this scope preflight and is resumed for a fresh delivery assessment. Main may implement directly after scope passes; delegate implementation when the user requests it or independent parallel ownership/context isolation materially helps. The verifier remains read-only and independent from the author, including main, and main cannot replace that assessment with self-review. Do not add a separate reviewer merely to satisfy the generic word "review". This does not change cumulative v2 registration, scope-before-write, current evidence, fresh delivery review, Ask permissions or inline exclusions. Complex work keeps the independent reviewer and verifier. This preflight is distinct from reviewing the implementation afterward. Main persists the reviewer report through `write_to_file` with `IsArtifact: true` as `harness-acceptance-review.json`:

```json
{
  "version": 1,
  "taskId": "signup-1",
  "revision": 1,
  "phase": "scope",
  "coveredIds": ["AC-1"],
  "unmappedRequests": []
}
```

`coveredIds` contains all active IDs exactly once. `unmappedRequests` contains requested outcomes not represented adequately; an empty list must be the independent review's conclusion. Resolve omissions and obtain a fresh matching scope report after a contract revision before product writes. Do not fabricate a report to satisfy the gate. The gate can validate report shape and identity; it cannot prove worker independence or that a natural-language request was mapped correctly.

Before applying a business rule, find its source in the user's instructions or repository contracts and behavior. Expose conflicts. A labeled assumption does not establish acceptance. If a missing rule materially changes behavior, main requests clarification and pauses dependent work while independent work can continue. Never silently invent a default.

The inline fast path remains exempt only when all existing eligibility conditions hold and the response declares `mode: inline-fast-path`. Routing and semantic eligibility remain policy controls; a marker cannot prove that the edit qualified.

## Record verification honestly

Run relevant checks after registration and the final workspace write. For every criterion, identify the command that actually exercises its acceptance. Behavioral criteria require a behavioral check; lint, types and a build alone do not establish behavior.

After the final product write, give an independent reviewer/verifier the cumulative request, final contract, exact diff, actual checks and observed evidence. Assess delivery for each AC: what behavior exists, which check tests it, and why the evidence is relevant. Main replaces `harness-acceptance-review.json` with the matching delivery report:

```json
{
  "version": 1,
  "taskId": "signup-1",
  "revision": 1,
  "phase": "delivery",
  "requirements": [
    {
      "id": "AC-1",
      "status": "passed",
      "evidenceSteps": [21],
      "reason": "The invalid-email check exercises rejection and the visible validation error."
    }
  ],
  "unmappedRequests": []
}
```

Include every active ID exactly once, `status` (`passed|failed|blocked|unverified`), observed integer `evidenceSteps`, and a nonempty `reason` explaining evidence relevance or the gap, including passed rows. Reusing the same broad-suite step for several ACs is valid only when the reviewer can establish that the suite exercises each acceptance. If a finding is fixed or any product write follows, rerun affected evidence on the resulting state and renew delivery review. Contract and review artifact writes are protocol bookkeeping, not product edits. The hook retains scope registration even though the delivery report replaces the artifact file.

Reference the observed `stepIdx` of successful check tool calls. Never invent a command execution, step ID, exit status or test result. Main must rerun a relevant check when subagent execution is not visible in its hook state. Preserve later failures even when earlier checks passed. Do not weaken assertions, skip failing tests, replace real integration with a mock, or present a placeholder/stub as delivered behavior.

`PreInvocation` can supply a separate ephemeral observed-ID advisory on each supported invocation. It derives the current user step from the bounded validated transcript, never from `initialNumSteps`, and includes only numeric current-user/evidence-floor/check IDs. It omits the advisory when user evidence is missing, truncated, duplicated, out of order or otherwise unsafe. An earlier request's contract/check state cannot supply candidate IDs for the current request. Current check candidates share Stop's freshness, later-failure and verified ordered-chain filters; Stop additionally requires evidence to precede the response being validated. Each advisory is at most 1,024 bytes and includes no request or command content, paths or credentials; it neither creates nor changes state.

The advisory is for main's contract registration/reporting only when that workflow is already required. It does not require a contract for read-only work or the eligible inline fast path. Candidates still need AC relevance and a current matching independent delivery review; no success, permission or scope is established by receiving an ID hint. MCP/stack/runtime discovery remains limited to the first invocation. Source support for `ephemeralMessage` does not prove that a particular live session received the hint or that it reduced latency. Ask permissions and completion enforcement are unchanged. If the hint is unavailable, use observed artifact evidence or disclose the gap; never guess IDs.

If tool step numbers are not shown in the client, read the conversation artifact `.codex-claude-harness-verification.json` using `view_file`. Its bounded `checkEvents` list supplies observed `step`, `success` and `behavioral` values. The `command` field is SHA-256 of the exact `CommandLine`, a NUL character, and `Cwd`; it identifies a rerun without storing command text or output. Match your executed commands to these entries; never guess step numbers. Only the latest 128 check events are retained, so rerun any required evidence that has aged out. Outstanding failed checks persist across turns of the active task and require a successful rerun of the same command before `complete`, even if other files were edited meanwhile. A progress question or follow-up does not clear this failure debt. Failed mixed formatting/check chains also remain outstanding.

`HARNESS_NO_RUNNABLE_CHECK: <specific reason>` is a disclosed waiver after command discovery, never a passing result. The affected criterion remains `unverified`. Environment failures and missing material decisions remain visible as failed, blocked or unverified outcomes, according to the evidence.

## Final result and exact counts

Include a concise human-readable count and result for every criterion. Append exactly one single-line `HARNESS_RESULT:` outside Markdown code fences, followed by JSON with:

- For version 2, `taskId` and `revision` matching the active contract.
- `status`: `complete`, `partial` or `blocked`.
- `requirements`: every registered ID exactly once, without additions or omissions.
- Each requirement: `id`, `status` (`passed`, `failed`, `blocked` or `unverified`), `evidenceSteps` (observed integer step IDs), and a `reason` for every nonpassed row.

`complete` requires every criterion to be passed with current successful evidence and, for version 2, matching scope and delivery reports. Partial/blocked results may omit reviews for unfinished rows only; every passed row still requires current delivery relevance review. The final scope report is required for complete, not for a passed subset of a partial result. Always list every active criterion honestly with reasons for unfinished rows. An active version-2 task cannot be downgraded by registering a version-1 contract. Use `partial` or `blocked` when anything remains outstanding; a truthful incomplete result can finish without pretending the request is fulfilled. Report the actual passed/total count, not the number of files edited, commands run or tasks attempted.

For example, the request is: "validate the email, prevent duplicate submissions, save the signup, and send a confirmation email." The registered inventory contains four corresponding criteria. If only email validation and duplicate protection are verified, the response states **2/4 passed; partial** and identifies the missing persistence and confirmation behavior:

```text
HARNESS_RESULT: {"taskId":"signup-1","revision":1,"status":"partial","requirements":[{"id":"AC-1","status":"passed","evidenceSteps":[21]},{"id":"AC-2","status":"passed","evidenceSteps":[22]},{"id":"AC-3","status":"unverified","evidenceSteps":[],"reason":"Persistence acceptance has not been verified."},{"id":"AC-4","status":"blocked","evidenceSteps":[],"reason":"The required email delivery configuration is unavailable."}]}
```

Only main emits the final result envelope; workers return their evidence without a `HARNESS_RESULT` marker. Reconcile the active contract, reviews and observed check IDs before emitting it. If Stop requests a correction, the new response replaces the earlier response: do not quote or concatenate earlier envelopes, restart valid scope reviews, or repeat adequate checks merely to repair report fields. The gate supplies bounded observed current-user/evidence-floor/check IDs for repair, without command text, paths or request content. Eligible check IDs are candidates only; they still need relevant AC coverage and a current matching independent delivery review. Missing, stale or failed checks still need correction.

The public CLI can aggregate a response before a Stop continuation with the replacement response in its terminal result. The gate checks only the latest compatible completed planner response. A consumer of CLI output must distinguish final response steps from the terminal aggregate; it must still reject multiple result envelopes within that final response. Do not simply choose the last marker from an aggregate or retrospectively rescore historical failures without retained response-step evidence.

The numbers are illustrative. Actual results must reference tool steps observed in that conversation. An independent verifier must establish that each command covers the claimed criterion. Four rows or one passing broad suite do not by themselves prove four requirements were delivered.

## Enforcement and limits

The Stop hook uses the registered contract, observed tool events and a bounded compatible transcript response. For version 2, `complete` additionally requires matching scope and delivery reviews, full active-ID coverage and consistent current successful evidence. It rejects missing/duplicate IDs, unsupported success claims, stale evidence and inconsistent completion. A recognized invalid completion result does not become valid after one correction reminder; correct the result or report an honest incomplete status. A partial result may finish with outstanding rows while retaining the active task and its requirements for follow-up. This differs from the older bounded verification and citation reminders.

Main MCP handoffs include one plain `Harness: <ROUTE>; passed: ...; failed/skipped: ...` line; interactive browser QA uses `REVIEW_VERIFY`. Explicit user exact-output formats and leaf assignments are exempt. The permission-neutral `PostToolUse` observer records only the last native `call_mcp_tool` step, including failed attempts, without arguments, result text, server names or check evidence. When that step falls strictly between a compatible current user record and completed main response, Stop can request one format repair per user turn. It never appends a pass, reruns tools, grants permissions, or turns MCP output into acceptance evidence. A second missing line is allowed with a limitation warning to avoid loops; missing/truncated/ambiguous provenance and abnormal stops fail open. `parentConversationId` identifies leaf calls; unknown non-string identity metadata is exempt. Native compatibility evidence is the public Antigravity 1.3.3 binary (SHA-256 `96dd362d5583c60485f5277fa64e43dd64c3ff02a2bf109fd683b99777da370d`), whose `HookArgsCommon` exposes `GetParentConversationId` and whose `PostToolHookArgs` exposes `GetToolCall`/`GetStepIdx`; this does not promise every future schema.

This is mechanical consistency checking. It cannot establish semantic coverage of cumulative natural-language requests, business correctness, whether a test exercises the claimed behavior, worker independence, or the truth of prose merely because a cited file and line exist. Independent review and verification remain necessary. A fabricated review report or irrelevant passing test may be mechanically recognizable while providing no meaningful acceptance evidence.

Unknown, truncated or unavailable transcript schemas, inaccessible state and unavailable runtime may fail open. Disclose these limits and any inaccessible task context in the handoff; do not claim continuity or delivery that could not be checked. Registration, explicit task-change interpretation and inline-route selection also depend on policy compliance. This is not a security boundary against deliberate hook avoidance, and it cannot guarantee that an agent never fabricates a claim.

Unresolved failures survive user turns and evidence-history eviction in a separate bounded active-task summary. If more than 128 distinct unresolved commands exhaust that summary during the task, `complete` is refused conservatively even after later reruns because some failure identities could not be retained. Report partial; recovery requires an explicit user-authorized task replacement and fresh verification, not an incidental new prompt or same-task revision.

Repository tests verify the source behavior. They do not prove that an existing installed client session has loaded it. Installing or updating the harness and starting a new supported Antigravity session is a separate operator step; never recursively run installers or launch `agy` inside an active Antigravity session merely to claim deployment verification.
