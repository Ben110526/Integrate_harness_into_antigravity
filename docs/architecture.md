# Selected Architecture

## Conclusion

There is no official path for using Google AI Pro quota or Antigravity OAuth as the model backend for Codex CLI or Claude Code. The implemented architecture is **harness-in-Antigravity**:

```text
User
   │
   ▼
official agy / Antigravity
   ├── Gemini 3.7 Flash High through Google AI Pro quota
   ├── AGENTS.md + rules
   ├── skills/workflows
   ├── 7 subagents routed by risk
   ├── DLP/context/format/verification hooks
   └── tools and MCP servers routed by the AI under Antigravity's sandbox and permissions
```

There is no OAuth relay, session-cookie extraction, traffic interception, private endpoint, PTY automation from another agent, or OpenAI/Anthropic-compatible gateway.

## Why FCC/proxy Is Not Used

Google explicitly states that using third-party software—including Claude Code, OpenClaw, and OpenCode by name—with an Antigravity login violates its terms and may result in account suspension or termination. To use a third-party agent, Google requires a Vertex or AI Studio API key:

- [Antigravity FAQ](https://antigravity.google/docs/faq/)
- [Antigravity Additional Terms, section 6](https://antigravity.google/terms/)

Beyond the terms issue, the harnesses do not use the same wire protocol:

- Codex custom providers currently accept only the OpenAI Responses API. See the [Codex configuration reference](https://developers.openai.com/codex/config-reference).
- Anthropic does not support routing Claude Code to a non-Claude model through a gateway. See [Claude Code LLM gateway](https://code.claude.com/docs/en/llm-gateway).
- `ANTHROPIC_BASE_URL`, `HTTP_PROXY`, and `HTTPS_PROXY` only change the endpoint or network proxy; they do not convert a Gemini subscription into the Anthropic Messages API.

## Feasibility Matrix

| Option | AI Pro quota | Official | Conclusion |
|---|---:|---:|---|
| FCC/OAuth proxy → Codex/Claude | Yes | No | Not implemented; account-suspension risk |
| `agy` + plugins/skills/subagents | Yes | Yes | Selected and implemented |
| Headless `agy` for scripts/CI | Yes | Yes | Supported, provided the entrypoint remains `agy` |
| Antigravity SDK/Agent API | No | Yes | Requires an API key or Vertex; billed separately |
| Codex/Claude + Gemini API adapter | No | Possibly | Requires API access and a protocol-adapter layer |

## Harness Capabilities That Were Ported

- Hierarchical policy through `AGENTS.md`.
- Planning and workflows through skills.
- Research, implementation, review, and verification through context-isolated subagents; the documenter, security auditor, and DB architect are added only when the scope requires that specialization.
- Dirty-worktree protection, minimum-diff discipline, and destructive-action safety.
- Targeted tests first, followed by broader validation.
- Headless JSON/stream-json for CI and automation, as documented by Google.
- Smoke evals can pin `gemini-3.7-flash-high` to compare routing changes under the same model profile.

## Accuracy Pipeline

Localized, low-risk changes use the `IMPLEMENT` route: implementer, then verifier. Changes involving a public contract, auth/permissions, persistence, migration, concurrency, security, dependency/platform migration, or multiple interdependent components use `COMPLEX_IMPLEMENT`:

```text
research + plan
      ↓
implement
      ↓
independent review + verification
      ↓
fix findings (if any) + final verification
```

Complex or multi-constraint work starts with a compact acceptance ledger. Stable IDs (`AC-1`, `AC-2`, ...) bind each observable requirement to intended evidence and a verification check; the implementer, reviewer, verifier, and final handoff preserve those IDs. Bug fixes use falsification where practical: capture a focused test or safe reproduction that fails for the expected reason before product edits, then rerun the same command unchanged after the fix. If that red state is unsafe or infeasible, the agent records the reason and uses the strongest feasible alternative. Source paths and symbols must be verified before citation, and non-established claims are labeled `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`.

The `PreToolUse` DLP hook hard-denies only high-confidence private-key or credential material, or attempts to commit, print, or transmit a sensitive `.env` file. JWTs and ambiguous signals use `force_ask`; the hook never grants permission for safe operations. During the first invocation, `PreInvocation` builds a bounded, temporary project blueprint from static manifests and workspace markers. It reports detected frameworks, local runtime versions, workspace topology, and candidate checks. Only fixed topology labels and shell-safe, allowlisted script or Make target names enter model context; package script bodies and build recipes do not. Candidate commands are advisory and must be checked against project configuration before execution. Auto-formatting is disabled by default, is enabled only with `HARNESS_AUTO_FORMAT=1`, uses an already-installed formatter on the exact file just written, and does not replace testing.

The Stop hook records bounded workspace-relative changed paths and only accepts evidence produced after the latest write; it neither guesses nor runs checks itself. A known documentation or non-code mechanical edit may be closed by a successful static check such as format validation, lint, type checking, or build verification. A logic-file edit or a terminal mutation whose target scope is unknown requires a later behavioral test or regression check; a static-only command is insufficient.

When no behavioral or static check can run, the agent may explicitly print `HARNESS_NO_RUNNABLE_CHECK: <specific reason>` with a successful, non-redirected print command. This records a waiver, not a passing check, and the limitation must be reported in the final response. Without current evidence or a valid waiver, the gate requests verification once and then allows the next normal idle stop to prevent an infinite loop. Internal hook/state failures likewise fail open after at most one recovery reminder rather than locking the session. The hooks require Python 3.8+; when the runtime is unavailable, DLP falls back to `force_ask`, while context, formatting, and verification retain their documented safe fallback behavior.

Smoke evals exercise both sides of the evidence contract. A read-only nonexistent-symbol case requires an exact `NOT_FOUND` result and forbids claims of a definition, location, or file mutation. The complex fixture declares independently named acceptance criteria and runs each targeted check as well as the full suite. These are behavioral signals; the headless JSON envelope still cannot prove exact subagent scheduling order.

Context7, Serena, Playwright, GitHub, and Sentry are registered through `plugin/codex-claude-harness/mcp_config.json`, so Antigravity loads them with the plugin at the start of a session and the model decides which server is worth calling. Server names use the `harness-` prefix to prevent collisions with global or workspace configuration. The `disabled` templates in the skill are reference and rollback copies only; they are no longer a manual installation step.

Context7 and Playwright use packages pinned through `npx`; Serena uses a package pinned through `uvx`; GitHub uses a release binary pinned by version and verified by OS/architecture-specific checksums; and Sentry uses its official remote endpoint with the `skills=inspect` capability allowlist. GitHub exposes only read-only/lockdown mode; Serena disables mutation tools; and Sentry additionally disables `update_issue`, Seer analysis, and the catalog executor as defense in depth so catalog mutations cannot bypass the wrapper. MCP permissions remain set to Ask. The harness adds no wildcard allow rule, embeds no credentials, and leaves the user to complete the provider's standard OAuth flow when required.

The installer registers the five MCP servers only when all required runtimes and the GitHub MCP binary are ready. `--skip-mcp`, or a recoverable bootstrap failure, produces a core-only plugin without a root `mcp_config.json`, preventing a missing server command from breaking the session. Playwright remains loopback-only by default. Exact staging origins are added only to the installed plugin when the user supplies `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS`; wildcards, paths, and credentials are all rejected. On a trusted personal development machine, `--playwright-unrestricted` (or PowerShell `-PlaywrightUnrestricted`) removes the origin filter from the temporary installation copy while retaining isolated/headless operation and Antigravity's Ask permission.

Relevant Antigravity documentation:

- [Headless mode](https://antigravity.google/docs/cli/headless/)
- [Plugins & skills](https://antigravity.google/docs/cli/plugins/)
- [Subagents](https://antigravity.google/docs/subagents)
- [Plans and Google AI Pro quota](https://antigravity.google/docs/plans/)

## If the Codex or Claude UI Is Required Later

Once a valid API key is available, build a separate gateway with golden tests for streaming, tool calls, tool results, cancellation, retries, and long context. For Codex, the gateway must expose the Responses API; for Claude Code, the supported upstream must still be Claude. A consumer subscription does not replace API entitlement.
