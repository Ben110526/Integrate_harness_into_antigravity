---
name: harness-plan
description: Build an evidence-based implementation plan for complex, cross-file, risky, or ambiguous engineering work.
---

# Plan workflow

1. Read repository instructions, git status, and the relevant code paths.
2. Form a compact brief: real problem, current behavior, desired behavior, scope/non-goals, constraints, and observable completion evidence. Discover answers locally before asking. Resolve evidence in this order: the user's explicit request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; labeled assumptions.
3. Delegate independent read-only discovery when it will materially improve speed or coverage.
4. Build a **Behavior Map** before writing any AC. Trace: entry point → call sites → core behavior → outputs/side effects → tests. For each node record: the file path and symbol, the data it consumes and produces, and any invariant or contract it enforces. Identify which nodes are mutated by the planned change and which are left unchanged. Record competing hypotheses and the cheapest discriminating check for each. Emit the map as a compact table or numbered list — it must be present in the plan output and explicitly referenced when forming ACs. Treat the startup blueprint as a hint, not proof of project semantics.
5. Map every explicit user requirement and constraint to stable IDs (`AC-1`, `AC-2`, ...) with observable acceptance and a relevant check. Do not omit, merge away, dilute, or invent requirements. Before product edits outside the inline fast path, main registers `harness-task-contract.json` through `write_to_file` with `IsArtifact: true` and `CodeContent` JSON: `{"version":1,"requirements":[{"id":"AC-1","request":"exact substring of current user request","acceptance":"observable expected behavior","verification":"behavioral"}]}`. Use `static` for static acceptance only. The ID inventory, request excerpts, acceptance and verification remain immutable for the current user turn; corrections require explicit new user scope. Carry the entire contract into implementation, review, verification, and final handoff. Never put credentials or private configuration in the artifact. If the user explicitly changes scope in a new turn, retain superseded ACs and the reason in the task history; replan and invalidate affected evidence without weakening the active turn's registered contract. Editing files, invoking agents, or running a suite alone is not a product acceptance criterion.
Before registering a complex task's immutable contract, invoke independent
`harness-reviewer` on the draft, full original request, Behavior Map and business-rule
sources. Require every requirement, constraint, condition and negative instruction
to be accounted for; report omissions, diluted acceptance and unsupported rules.
Resolve discovered source conflicts and revise the draft before locking it. If an
undiscoverable material rule remains unresolved, record its AC as unresolved and
pause only dependent work. This is a bounded early assignment to the existing
reviewer, not final approval or a substitute for final independent checks.

For `COMPLEX_IMPLEMENT`, register contract **version 2**. Retain the version-1
requirement fields and add `cases` to each AC, plus root `coverageReview`:

```json
{"version":2,"requirements":[{"id":"AC-1","request":"validate the email","acceptance":"Invalid email is rejected visibly","verification":"behavioral","cases":[{"id":"TC-1","kind":"failure","scenario":"Submit an invalid email","expected":"Validation error; signup not saved","basis":"User request: validate the email"}]}],"coverageReview":{"reviewer":"harness-reviewer","reviewedIds":["AC-1"],"unresolvedIds":[]}}
```

Use unique `TC-*` IDs, 1–16 cases per AC. Behavioral case kinds are `normal`,
`boundary` or `failure`; static ACs use `static`. Each scenario, expected outcome
and basis must be specific and grounded in the request or inspected repository
contract (path/symbol where relevant). Do not invent expected values to fill fields.
Choose normal/error/boundary cases proportionally to the requested behavior; do
not add ceremonial cases or treat examples as extra scope. `reviewedIds` covers
all ACs and `unresolvedIds` identifies rules or coverage gaps still blocking them.
Cases and the review inventory stay immutable for this user turn. A review record
is coordinator bookkeeping, not proof an independent agent ran or that semantics
are correct. Tiny/clear localized work keeps its existing route and version 1.

6. Produce a short ordered plan with concrete files/components and verification for each stage. For a multi-milestone goal, use [harness-run](../harness-run/SKILL.md): dependency-ordered, independently verifiable outcomes, one active milestone, one coordinator, and self-contained worker assignments. Three to six milestones is a starting heuristic, not a quota; do not split a tiny task to fit it. Within the active milestone, define dependency-scoped work items with explicit read/write ownership; default to 3 concurrent workers within runtime capacity. Launch independent ready discovery/specialist branches before waiting and plan parallel implementers only after their interfaces are settled. Preserve the frozen-source barrier for final independent review and verification.
7. Verify cited source paths and symbols before treating them as facts. Label only non-established claims as `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`; do not present missing evidence as established. Do not invent requirements or business rules. Expose conflicts between sources. A labeled assumption cannot establish acceptance; a missing material rule requires main-owned clarification before dependent implementation.

If an undiscoverable decision would materially change product behavior, architecture, security, data, cost, or an irreversible action after the evidence and cheapest safe check are exhausted, use `harness-clarify` for one bounded user choice. Do not use clarification as a substitute for repository discovery.

If the user requested both planning and implementation, continue into implementation after the plan unless a missing decision would materially change the result. If the request is plan-only, remain read-only.
