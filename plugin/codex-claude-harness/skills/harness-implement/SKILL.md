---
name: harness-implement
description: Implement a requested code or configuration change with scoped edits, proactive delegation, and risk-proportionate verification.
---

# Implementation workflow

1. Load repository instructions and inspect current git state.
2. Define observable acceptance criteria before editing. For complex or multi-constraint work, assign stable IDs (`AC-1`, `AC-2`, ...) and record the intended evidence and check for each; preserve those IDs through review, verification, and handoff. Resolve evidence in this order: the user's explicit request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; labeled assumptions. Surface any conflict that materially changes the result.
3. Classify the change by risk, not file count. Keep localized, well-understood, low-blast-radius edits lean. Treat public interfaces, auth/permissions, persistence/schema/migrations, concurrency, security-sensitive behavior, dependency/platform migrations, coupled components, high blast radius, or uncertain acceptance criteria as complex.
4. For a bug or regression, before editing product code capture a focused test or safe reproduction that fails for the expected reason (red). If that is unsafe or infeasible, state the reason and use the strongest feasible falsification check; do not manufacture failure for documentation-only, mechanical, or configuration work. After the fix, rerun the same check unchanged and require it to pass (green), then run relevant surrounding checks. For new or changed behavior, add or update the narrowest useful test before product code when the repository supports it.
5. For complex work, invoke a researcher and form a short evidence-based plan before implementation. Assign non-overlapping ownership to independent tasks.
6. Apply the smallest coherent change that solves the requested behavior and root cause. Update operator documentation when workflow or configuration behavior changes.
7. Run the narrowest decisive checks, then broader checks when their signal justifies the cost.
8. After a complex implementation, invoke an independent reviewer and verifier in parallel: provide the reviewer the exact diff and relevant contracts, and provide the verifier the acceptance criteria and runnable checks. Resolve actionable findings with a bounded implementation follow-up, then run final verification on the resulting state.
9. Review the final diff for unrelated changes, exposed secrets, incomplete branches, and compatibility regressions.
10. Report the outcome, exact commands and results, residual untested risk, and an `AC-ID -> evidence/check -> result` matrix when an acceptance ledger exists. Verify source-path and symbol claims before citing them; label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`, and never turn missing evidence into a fact. Never commit or push unless explicitly requested.
