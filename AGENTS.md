# Shared engineering harness policy

This repository uses Antigravity as the first-party model client. Apply this policy to every task unless a more specific `AGENTS.md` closer to the edited file overrides it.

## Operating loop

1. Read the request, repository instructions, current git state, and the smallest set of relevant files before proposing changes.
2. For multi-file or ambiguous work, keep a short plan with one active step. For a simple edit, work directly.
3. Delegate independent, bounded research, implementation, review, or verification work to subagents when it materially reduces latency or protects the main context.
4. Make the smallest coherent change that solves the root problem. Preserve unrelated user changes and established project conventions.
5. Verify in proportion to risk: start with targeted checks, then broader tests, lint, type checks, or builds when useful.
6. Report the outcome, verification performed, and any real residual risk. Do not claim success when a required check failed or was not run.

When the user explicitly requests delegation, or the active plan contains an independent bounded branch, you must start the worker with `invoke_subagent(TypeName=..., Role=..., Workspace="inherit", Prompt=...)` before doing that delegated work yourself. `send_message` is only for a subagent conversation that already exists; never search `~/.gemini` to discover an installed agent.

## Communication

- Lead with the result or current finding, not a diary of tool calls.
- During long work, send concise progress updates at meaningful milestones.
- State assumptions that affect behavior, scope, data, cost, or external systems.
- Ask only when a missing decision would materially change the result and cannot be discovered safely.

## Search and editing

- Prefer `rg` and `rg --files` for repository search when available.
- Read enough surrounding code to understand contracts and call sites before editing.
- Keep diffs focused. Do not reformat unrelated code or overwrite a whole file for a small change.
- Reuse project tooling and existing abstractions before adding dependencies or parallel implementations.
- Add comments only where they explain a non-obvious constraint or decision.

## Git and filesystem safety

- Treat a dirty worktree as user-owned. Never discard, reset, or rewrite unrelated changes.
- Do not run destructive commands, broad recursive deletion, force pushes, or history rewrites unless the user explicitly requests the exact operation.
- Resolve exact targets with read-only checks before any destructive or difficult-to-recover action.
- Never expose credentials, OAuth artifacts, cookies, tokens, or private configuration in output, logs, commits, or tests.
- Do not extract or relay Antigravity OAuth credentials, call private Antigravity endpoints, or route an Antigravity consumer login through third-party agent clients.

## Implementation quality

- Fix causes rather than masking symptoms.
- Preserve public interfaces unless the requested change requires a migration.
- Handle errors at the boundary where useful context is available.
- Avoid speculative fallbacks that make failures look successful.
- Update tests or documentation when behavior, configuration, or operator workflow changes.

## Review standard

- Review findings are ordered by severity and include concrete file/line evidence.
- Prioritize correctness, security, data loss, regressions, race conditions, and missing tests over stylistic preferences.
- If no actionable finding exists, say so and name the main checks performed.

## Completion standard

A change is complete only when the requested behavior exists, relevant checks pass, and the final handoff distinguishes verified facts from assumptions or untested areas.
