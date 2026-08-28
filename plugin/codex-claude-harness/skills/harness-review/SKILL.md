---
name: harness-review
description: Review a diff, branch, PR, or code area for actionable correctness, security, regression, and test issues.
---

# Review workflow

1. Read repository instructions, the complete diff, and enough surrounding code/tests to understand contracts.
2. Trace changed inputs, outputs, state transitions, error paths, and compatibility boundaries.
3. Run safe focused checks when they materially validate a suspected issue.
4. Return findings first, ordered by severity. Each finding needs a tight path/line reference, failure scenario, impact, and concise fix direction.
5. Avoid speculative or style-only comments.
6. If no actionable issue is found, say so and summarize what was checked plus residual test gaps.

Remain read-only unless the user separately asks to fix the findings.
