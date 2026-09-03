---
name: harness-debug
description: Diagnose or fix a defect using reproduction, evidence collection, hypothesis testing, root-cause analysis, and regression verification.
---

# Debug workflow

1. Capture the observed behavior, expected behavior, environment, and smallest reproduction available.
2. Inspect logs and trace the relevant path from boundary to failure; do not guess from the final error alone.
3. Label competing hypotheses `[HYPOTHESIS]` and run the cheapest discriminating check first. Verify cited paths and symbols; mark claims without evidence `[UNRESOLVED]` and material assumptions `[ASSUMPTION]`.
4. Before editing product code, capture a focused failing test or safe reproduction that fails for the expected reason (red). When this is unsafe or infeasible, record why and use the strongest feasible falsification check.
5. State the evidence-backed root cause.
6. If the user requested a fix, implement the minimum durable correction and add a regression test when feasible. If they requested diagnosis only, remain read-only.
7. Re-run the exact red-state check unchanged and require it to pass (green), then run relevant surrounding checks.
8. Report root cause, fix (if authorized), red/green evidence, and remaining uncertainty.
