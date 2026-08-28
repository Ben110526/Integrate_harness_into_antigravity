---
name: harness-plan
description: Build an evidence-based implementation plan for complex, cross-file, risky, or ambiguous engineering work.
---

# Plan workflow

1. Read repository instructions, git status, and the relevant code paths.
2. Clarify the requested outcome, constraints, non-goals, and observable acceptance checks. Resolve evidence in this order: the user's explicit request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; labeled assumptions.
3. Delegate independent read-only discovery when it will materially improve speed or coverage.
4. Identify current behavior, root problem, affected interfaces/data, migration risk, and test surface.
5. Produce a short ordered plan with concrete files/components and verification for each stage.
6. Mark assumptions and genuine decision points. Do not invent requirements.

If the user requested both planning and implementation, continue into implementation after the plan unless a missing decision would materially change the result. If the request is plan-only, remain read-only.
