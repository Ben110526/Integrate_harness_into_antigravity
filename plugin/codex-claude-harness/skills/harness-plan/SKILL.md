---
name: harness-plan
description: Build an evidence-based implementation plan for complex, cross-file, risky, or ambiguous engineering work.
---

# Plan workflow

1. Read repository instructions, git status, and the relevant code paths.
2. Form a compact brief: real problem, current behavior, desired behavior, scope/non-goals, constraints, and observable completion evidence. Discover answers locally before asking. Resolve evidence in this order: the user's explicit request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; labeled assumptions.
3. For complex or multi-constraint work, create a compact acceptance ledger with stable IDs (`AC-1`, `AC-2`, ...), each observable outcome's requirement source, intended evidence, and planned verification. Carry these IDs unchanged into implementation, review, verification, and final handoff. If the user changes a requirement, retain the superseded AC and reason; replan only affected work and invalidate affected evidence. Editing files, invoking agents, or running a suite alone is not a product acceptance criterion.
4. Delegate independent read-only discovery when it will materially improve speed or coverage.
5. Trace entry point → call sites → core behavior → outputs/side effects → tests. Record invariants, affected interfaces/data, competing hypotheses, the cheapest discriminating check, and edit versus read-only file scope. Treat the startup blueprint as a hint, not proof of project semantics.
6. Produce a short ordered plan with concrete files/components and verification for each stage. For a multi-milestone goal, use [harness-run](../harness-run/SKILL.md): dependency-ordered, independently verifiable outcomes, one active milestone, one coordinator, and self-contained worker assignments. Three to six milestones is a starting heuristic, not a quota; do not split a tiny task to fit it.
7. Verify cited source paths and symbols before treating them as facts. Label only non-established claims as `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`; do not present missing evidence as established. Do not invent requirements.

If an undiscoverable decision would materially change product behavior, architecture, security, data, cost, or an irreversible action after the evidence and cheapest safe check are exhausted, use `harness-clarify` for one bounded user choice. Do not use clarification as a substitute for repository discovery.

If the user requested both planning and implementation, continue into implementation after the plan unless a missing decision would materially change the result. If the request is plan-only, remain read-only.
