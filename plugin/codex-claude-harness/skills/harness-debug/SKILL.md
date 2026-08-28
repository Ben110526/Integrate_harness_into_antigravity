---
name: harness-debug
description: Diagnose or fix a defect using reproduction, evidence collection, hypothesis testing, root-cause analysis, and regression verification.
---

# Debug workflow

1. Capture the observed behavior, expected behavior, environment, and smallest reproduction available.
2. Inspect logs and trace the relevant path from boundary to failure; do not guess from the final error alone.
3. Keep competing hypotheses and run the cheapest discriminating check first.
4. State the evidence-backed root cause.
5. If the user requested a fix, implement the minimum durable correction and add a regression test when feasible. If they requested diagnosis only, remain read-only.
6. Re-run the reproduction and relevant surrounding checks.
7. Report root cause, fix (if authorized), verification, and remaining uncertainty.
