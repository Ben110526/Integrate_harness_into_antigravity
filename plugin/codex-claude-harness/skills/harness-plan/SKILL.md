---
name: harness-plan
description: Build an evidence-based implementation plan for complex, cross-file, risky, or ambiguous engineering work.
---

# Plan workflow

1. Read repository instructions, git status, and the relevant code paths.
2. Clarify the requested outcome, constraints, non-goals, and observable acceptance checks. Resolve evidence in this order: the user's explicit request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; labeled assumptions.
3. For complex or multi-constraint work, create a compact acceptance ledger with stable IDs (`AC-1`, `AC-2`, ...), each criterion's intended evidence, and its planned verification. Carry these IDs unchanged into implementation, review, verification, and final handoff.
4. Delegate independent read-only discovery when it will materially improve speed or coverage.
5. Identify current behavior, root problem, affected interfaces/data, migration risk, and test surface.
6. Produce a short ordered plan with concrete files/components and verification for each stage.
7. Verify cited source paths and symbols before treating them as facts. Label only non-established claims as `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`; do not present missing evidence as established. Do not invent requirements.

If an undiscoverable decision would materially change product behavior, architecture, security, data, cost, or an irreversible action after the evidence and cheapest safe check are exhausted, use `harness-clarify` for one bounded user choice. Do not use clarification as a substitute for repository discovery.

If the user requested both planning and implementation, continue into implementation after the plan unless a missing decision would materially change the result. If the request is plan-only, remain read-only.
