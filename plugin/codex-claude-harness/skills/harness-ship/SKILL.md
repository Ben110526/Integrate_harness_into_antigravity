---
name: harness-ship
description: Perform a final readiness pass over implemented work, verification, diff scope, documentation, and handoff without pushing or deploying implicitly.
---

# Ship workflow

1. Compare the full registered `harness-task-contract.json` inventory with the original user request, actual diff and behavior. Preserve every `AC-*` ID, request excerpt, acceptance and verification; no omitted, diluted or substituted criterion. An acceptance criterion without relevant evidence is `[UNRESOLVED]`, not complete. Reject invented business rules, silent material defaults, mocks/stubs and weakened tests as completion evidence. Retain superseded criteria with their explicit user scope-change reason in task history. For multi-milestone work, apply [harness-run](../harness-run/SKILL.md): compare workspace, brief revision, HEAD, and the scoped content fingerprint including uncommitted/new/deleted files. Missing or mismatched provenance means stale evidence, not a pass.
2. Inspect git status for unrelated or accidental files and secrets.
3. Run the highest-signal remaining checks appropriate to the risk, including integration across the completed milestones. A passing unrelated suite does not satisfy a failing or unverified AC; skipped checks and waivers remain visible.
4. Review error paths, compatibility, configuration defaults, migrations, and rollback implications.
5. Ensure user-facing or operator-facing changes are documented.
6. If required work remains ready and authorized, return to the coordinator for the next tool dispatch rather than a milestone-final response. Report ready only when all required ACs have current relevant evidence, actionable findings are resolved, and integration checks pass. If blocked, cancelled, or resource-limited, report exact passed/total counts and not-ready with incomplete ACs, a compact `AC-ID -> evidence/check -> result` matrix, remaining risks, and the exact next action. For ready handoff, report exact passed/total counts and the acceptance matrix too. Runtime Stop permission is not task completion. Verify cited source paths and symbols; label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`.

Do not commit, push, release, deploy, delete, or notify external systems unless the user explicitly requested that action.

For a registered contract, append exactly one single-line `HARNESS_RESULT:` JSON object with `status` (`complete|partial|blocked`) and all `requirements`. Each row contains `id`, `status` (`passed|failed|blocked|unverified`), `evidenceSteps` (observed tool `stepIdx` integers), and a reason for each nonpassed row. `complete` requires all rows passed with successful relevant checks after registration and the final workspace write; behavioral criteria need behavioral evidence. Keep later failures visible. A waiver is unverified, never passed; 2/4 passed is partial. Main reruns a relevant check if worker evidence is absent from its hook state. Do not invent commands, exit statuses or evidence. The mechanical gate cannot prove semantic coverage, business correctness or test relevance; reviewer/verifier must assess those.
