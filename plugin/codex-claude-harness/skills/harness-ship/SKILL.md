---
name: harness-ship
description: Perform a final readiness pass over implemented work, verification, diff scope, documentation, and handoff without pushing or deploying implicitly.
---

# Ship workflow

1. Confirm the requested acceptance criteria against the actual diff and behavior.
2. Inspect git status for unrelated or accidental files and secrets.
3. Run the highest-signal remaining checks appropriate to the risk.
4. Review error paths, compatibility, configuration defaults, migrations, and rollback implications.
5. Ensure user-facing or operator-facing changes are documented.
6. Report ready/not-ready, checks and results, remaining risks, and the exact next action if one is needed.

Do not commit, push, release, deploy, delete, or notify external systems unless the user explicitly requested that action.
