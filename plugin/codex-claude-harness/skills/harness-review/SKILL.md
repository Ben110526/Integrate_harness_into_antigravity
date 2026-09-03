---
name: harness-review
description: Review a diff, branch, PR, or code area for actionable correctness, security, regression, and test issues.
---

# Review workflow

1. Read repository instructions, the complete diff, and enough surrounding code/tests to understand contracts.
2. If acceptance IDs were provided, review every `AC-*` against the diff and its claimed evidence; report any uncovered criterion or missing proof without renumbering the ledger.
3. Trace changed inputs, outputs, state transitions, error paths, and compatibility boundaries.
4. Run safe focused checks when they materially validate a suspected issue.
5. Return findings first, ordered by severity. Each finding needs a verified path/line or symbol reference, failure scenario, impact, and concise fix direction. Label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`; missing evidence is a gap, not a verified finding.
6. Avoid speculative or style-only comments.
7. If no actionable issue is found, say so and summarize acceptance coverage, what was checked, and residual test gaps.

Remain read-only unless the user separately asks to fix the findings.
