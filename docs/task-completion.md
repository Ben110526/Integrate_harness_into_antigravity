# Task completion contract

The harness separates the user's requested outcomes from observed delivery. An agent that has verified two of four requirements must report **2/4, partial**. A successful test command alone does not establish that all requested behavior exists.

## Register acceptance before product edits

For implementation outside the strict inline fast path, main maps every explicit requirement and constraint to stable `AC-*` IDs. Each acceptance criterion describes observable behavior, including error paths or constraints when requested. Preserve requirements without omission or dilution; do not substitute a simpler feature. `verification` is `behavioral` for executable behavior and `static` for static acceptance.

Main uses Antigravity's `write_to_file` with `IsArtifact: true` to create an artifact named `harness-task-contract.json`. Its `CodeContent` is JSON:

```json
{
  "version": 1,
  "requirements": [
    {
      "id": "AC-1",
      "request": "validate the email",
      "acceptance": "Invalid email input is rejected with a visible validation error.",
      "verification": "behavioral"
    }
  ]
}
```

`request` must be an exact substring of the current user request. It anchors interpretation; the reviewer must still check that the whole request is covered. Use concise relevant excerpts and exclude credentials or private configuration. The hook observes registration from the tool call; a file written only through an unobserved shell command does not register the contract.

The ID inventory, request excerpts, acceptance and verification are immutable within the user turn. Do not delete a difficult criterion, replace it with a weaker version, or register a smaller inventory to make completion pass. Corrections require explicit new user scope. Preserve the complete contract through implementer, reviewer and verifier handoffs.

Before applying a business rule, find its source in the user's instructions or repository contracts and behavior. Expose conflicts. A labeled assumption does not establish acceptance. If a missing rule materially changes behavior, main requests clarification and pauses dependent work while independent work can continue. Never silently invent a default.

The inline fast path remains exempt only when all existing eligibility conditions hold and the response declares `mode: inline-fast-path`. Routing and semantic eligibility remain policy controls; a marker cannot prove that the edit qualified.

## Complex tasks: reviewed contract version 2

Complex implementation uses a bounded independent acceptance review **before**
registration and product edits. Main sends the full request, draft ACs, Behavior
Map and inspected business-rule sources to `harness-reviewer`. The reviewer
identifies omissions, diluted acceptance, unsupported rules and missing decisions;
main corrects the draft before making it immutable. Discovery/test planning on
stable inputs can overlap this review. Unresolved material rules pause dependent
work, while unrelated authorized work may proceed. This early review cannot
approve the final implementation.

Version 1 remains supported for existing clients and clear localized tasks.
Version 2 retains its requirement fields and adds cases and a review record:

```json
{
  "version": 2,
  "coverageReview": {
    "reviewer": "harness-reviewer",
    "reviewedIds": ["AC-1"],
    "unresolvedIds": []
  },
  "requirements": [{
    "id": "AC-1",
    "request": "validate the email",
    "acceptance": "Invalid email is rejected visibly without creating a signup.",
    "verification": "behavioral",
    "cases": [{
      "id": "TC-1", "kind": "failure",
      "scenario": "Submit an invalid email",
      "expected": "Validation error is shown; no signup is persisted",
      "basis": "User request: validate the email"
    }]
  }]
}
```

Every AC has 1–16 cases with globally unique `TC-*` IDs, specific inputs/actions,
expected observable outcomes and their source basis. Behavioral kinds are
`normal`, `boundary` and `failure`; static ACs use `static`. Select applicable cases
from the requested behavior and discovered contracts; do not invent business
rules, unnecessary cases or extra product scope. Include normal/error/boundary
probes when material, and explain an unavailable check rather than lowering the
expected outcome. Main reviews path/symbol references and conflicts in each basis.

`reviewedIds` includes every registered AC; `unresolvedIds` is a subset that cannot
pass. Cases and the review record are immutable within the user turn. A new user
clarification permits a new contract; editing the old review to remove a blocker
does not. Review identity and semantic coverage remain independently inspected
workflow obligations: a model-written record does not authenticate a reviewer.

The final verifier maps each case to actual test IDs, assertions/observed outcomes
and current tool steps. Build bounded independent challenge probes in an assigned
scratch directory when existing tests do not exercise required behavior; preserve
product tests and implementation ownership. A single suite may cover many ACs
when its real assertions prove all of them. Main includes this mapping on every
passed version-2 row:

```text
HARNESS_RESULT: {"status":"complete","requirements":[{"id":"AC-1","status":"passed","evidenceSteps":[21],"caseEvidence":[{"caseId":"TC-1","step":21,"test":"test_invalid_email_not_saved","assertion":"Validation error shown and signup count unchanged"}]}]}
```

The hook checks case coverage, unique known IDs, nonempty test/assertion fields,
resolved AC status and that case steps belong to the AC's observed fresh successful
checks. Failed/blocked/unverified rows need reasons but no fabricated mapping.
The hook still cannot read an assertion's meaning, prove test relevance or that the
independent review truly happened. One green test with invented case descriptions
is not meaningful acceptance; verifier inspection and outcome evals remain required.

## Record verification honestly

Run relevant checks after registration and the final workspace write. For every criterion, identify the command that actually exercises its acceptance. Behavioral criteria require a behavioral check; lint, types and a build alone do not establish behavior.

Reference the observed `stepIdx` of successful check tool calls. Never invent a command execution, step ID, exit status or test result. Main must rerun a relevant check when subagent execution is not visible in its hook state. Preserve later failures even when earlier checks passed. Do not weaken assertions, skip failing tests, replace real integration with a mock, or present a placeholder/stub as delivered behavior.

If tool step numbers are not shown in the client, read the conversation artifact `.codex-claude-harness-verification.json` using `view_file`. Its bounded `checkEvents` list supplies observed `step`, `success` and `behavioral` values. The `command` field is SHA-256 of the exact `CommandLine`, a NUL character, and `Cwd`; it identifies a rerun without storing command text or output. Match your executed commands to these entries; never guess step numbers. Only the latest 128 check events are retained, so rerun any required evidence that has aged out. Outstanding failed checks in the current user turn require a successful rerun of the same command before `complete`, even if other files were edited meanwhile. Failed mixed formatting/check chains also remain outstanding.

`HARNESS_NO_RUNNABLE_CHECK: <specific reason>` is a disclosed waiver after command discovery, never a passing result. The affected criterion remains `unverified`. Environment failures and missing material decisions remain visible as failed, blocked or unverified outcomes, according to the evidence.

## Final result and exact counts

Include a concise human-readable count and result for every criterion. Append exactly one single-line `HARNESS_RESULT:` outside Markdown code fences, followed by JSON with:

- `status`: `complete`, `partial` or `blocked`.
- `requirements`: every registered ID exactly once, without additions or omissions.
- Each requirement: `id`, `status` (`passed`, `failed`, `blocked` or `unverified`), `evidenceSteps` (observed integer step IDs), and a `reason` for every nonpassed row.

`complete` requires every criterion to be passed with current successful evidence. Use `partial` or `blocked` when anything remains outstanding; a truthful incomplete result can finish without pretending the request is fulfilled. Report the actual passed/total count, not the number of files edited, commands run or tasks attempted.

For example, the request is: "validate the email, prevent duplicate submissions, save the signup, and send a confirmation email." The registered inventory contains four corresponding criteria. If only email validation and duplicate protection are verified, the response states **2/4 passed; partial** and identifies the missing persistence and confirmation behavior:

```text
HARNESS_RESULT: {"status":"partial","requirements":[{"id":"AC-1","status":"passed","evidenceSteps":[21]},{"id":"AC-2","status":"passed","evidenceSteps":[22]},{"id":"AC-3","status":"unverified","evidenceSteps":[],"reason":"Persistence acceptance has not been verified."},{"id":"AC-4","status":"blocked","evidenceSteps":[],"reason":"The required email delivery configuration is unavailable."}]}
```

The numbers are illustrative. Actual results must reference tool steps observed in that conversation. An independent verifier must establish that each command covers the claimed criterion. Four rows or one passing broad suite do not by themselves prove four requirements were delivered.

## Enforcement and limits

The Stop hook uses the registered contract, observed tool events and a bounded compatible transcript response. It rejects missing/duplicate IDs, unsupported success claims, stale evidence and inconsistent completion. A recognized invalid completion result does not become valid after one correction reminder; the agent must correct the result or report an honest incomplete status. This differs from the older bounded verification and citation reminders.

This is mechanical consistency checking. It cannot establish semantic coverage of the original natural-language request, business correctness, whether a test exercises the claimed behavior, or the truth of prose merely because a cited file and line exist. Independent review and verification remain necessary. A mock or irrelevant passing test may be mechanically recognizable while providing no meaningful acceptance evidence.

Unknown, truncated or unavailable transcript schemas, inaccessible state and unavailable runtime may fail open. Registration and inline-route selection also depend on policy compliance. This is not a security boundary against deliberate hook avoidance, and it cannot guarantee that an agent never fabricates a claim.

Unresolved failures survive evidence-history eviction in a separate bounded summary. If more than 128 distinct unresolved commands exhaust that summary in one turn, `complete` is refused conservatively; report partial and obtain a new explicit verification scope.

Repository tests verify the source behavior. They do not prove that an existing installed client session has loaded it. Installing or updating the harness and starting a new supported Antigravity session is a separate operator step; never recursively run installers or launch `agy` inside an active Antigravity session merely to claim deployment verification.
