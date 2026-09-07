---
name: harness-ship
description: Perform a final readiness pass over implemented work, verification, diff scope, documentation, and handoff without pushing or deploying implicitly.
---

# Ship workflow

1. Confirm every required `AC-*` against the latest brief, actual diff, and behavior; preserve its ID and record concrete evidence/check and result. Retain superseded criteria with their change reason. An acceptance criterion without evidence is `[UNRESOLVED]`, not complete. For multi-milestone work, apply [harness-run](../harness-run/SKILL.md): compare workspace, brief revision, HEAD, and the scoped content fingerprint including uncommitted/new/deleted files. Missing or mismatched provenance means stale evidence, not a pass.
2. Inspect git status for unrelated or accidental files and secrets.
3. Run the highest-signal remaining checks appropriate to the risk, including integration across the completed milestones. A passing unrelated suite does not satisfy a failing or unverified AC; skipped checks and waivers remain visible.
4. Review error paths, compatibility, configuration defaults, migrations, and rollback implications.
5. Ensure user-facing or operator-facing changes are documented.
6. If required work remains ready and authorized, return to the coordinator for the next tool dispatch rather than a milestone-final response. Report ready only when all required ACs have current relevant evidence, actionable findings are resolved, and integration checks pass. If blocked, cancelled, or resource-limited, report not-ready with incomplete ACs, a compact `AC-ID -> evidence/check -> result` matrix, remaining risks, and the exact next action. Runtime Stop permission is not task completion. Verify cited source paths and symbols; label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`.

Do not commit, push, release, deploy, delete, or notify external systems unless the user explicitly requested that action.
