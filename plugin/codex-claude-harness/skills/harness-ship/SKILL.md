---
name: harness-ship
description: Perform a final readiness pass over implemented work, verification, diff scope, documentation, and handoff without pushing or deploying implicitly.
---

# Ship workflow

1. Compare the full version-2 `harness-task-contract.json` inventory with cumulative user intent across turns, actual diff and behavior. Preserve taskId/revision, every active `AC-*` ID, sourceStep, request excerpt, acceptance and verification; status questions/compaction do not reset scope. Check explicit scopeChanges/replacesTask evidence for changed scope; disclose inaccessible context. No omitted, diluted or substituted criterion, retired ID reuse or silent task replacement. An AC without relevant evidence is `[UNRESOLVED]`, not complete. Reject invented rules, silent material defaults, mocks/stubs and weakened tests as completion evidence.
2. Inspect git status for unrelated or accidental files and secrets.
3. Run the highest-signal remaining checks appropriate to the risk. Require matching independent scope review and per-AC delivery review. After the final product write, main persists `harness-acceptance-review.json` with `phase: delivery`, taskId/revision, all active id/status/evidenceSteps rows, a nonempty relevance/gap reason for every row and unmappedRequests. Rerun affected checks after fixes and refresh delivery review; shared broad-suite evidence must actually cover each claimed AC.
4. Review error paths, compatibility, configuration defaults, migrations, and rollback implications.
5. Ensure user-facing or operator-facing changes are documented.
6. Report exact passed/total counts, ready/not-ready, a compact `AC-ID -> evidence/check -> result` matrix, remaining risks, and the exact next action if one is needed. Verify cited source paths and symbols; label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`.

Do not commit, push, release, deploy, delete, or notify external systems unless the user explicitly requested that action.

For a registered contract, append exactly one single-line `HARNESS_RESULT:` JSON object with matching `taskId` and `revision`, `status` (`complete|partial|blocked`) and all active `requirements`. Each row contains `id`, `status` (`passed|failed|blocked|unverified`), `evidenceSteps` (observed tool `stepIdx` integers), and a reason for each nonpassed row. `complete` requires all rows passed with successful relevant checks after registration and the final workspace write; behavioral criteria need behavioral evidence. Keep later failures visible. A waiver is unverified, never passed; 2/4 passed is partial. Main reruns a relevant check if worker evidence is absent from its hook state. Do not invent commands, exit statuses or evidence. The mechanical gate cannot prove semantic coverage, business correctness or test relevance; reviewer/verifier must assess those.
