# Selected Architecture

## Conclusion

There is no official path for using Google AI Pro quota or Antigravity OAuth as the model backend for Codex CLI or Claude Code. The implemented architecture is **harness-in-Antigravity**:

```text
User
   │
   ▼
official agy / Antigravity
   ├── Gemini 3.8 Flash High through Google AI Pro quota
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
- Smoke evals can pin `gemini-3.8-flash-high` to compare routing changes under the same model profile.

## Accuracy Pipeline

Localized, low-risk changes use the `IMPLEMENT` route. Its conservative inline fast path lets the main agent directly perform a single-acceptance, deterministic change to one existing file and one contiguous hunk of at most 10 changed lines, then review the exact diff and run one narrow check. It does not invoke implementer or verifier subagents. The fast path excludes multi-constraint work, dirty overlap, external operations, generated/vendor/lock files, and public API/CLI/schema/config/install/CI/build/dependency/auth/security/persistence/migration/concurrency/permissions/secrets/legal/operator-workflow impact. Static prose, comments, and documentation use a static check; executable source still requires an existing focused behavioral check. Any uncertainty, scope growth, excluded concern, or missing/failed/inconclusive check promotes the work before another write.

Other localized implementation starts an independent read-only verifier for scope review; implementation waits for that scope to pass. After the implementer and main's final focused check bundle, main resumes the same known verifier conversation for a fresh delivery assessment using the current revision, full active ACs, final diff and observed checks. A scope summary is never delivery proof; the verifier remains independent from implementation. Reuse uses `send_message` only with that existing conversation, never agent searches or inferred identities. New scope, relevant writes or failures require renewed checks/review. Changes involving breaking/consumer-facing public contracts, auth/permissions, persistence, migration, concurrency, security, dependency/platform migration, or multiple interdependent components retain the named reviewer and verifier and use `COMPLEX_IMPLEMENT`:

```text
research + plan
      ↓
independent full-request scope review
      ↓
implement
      ↓
independent per-AC delivery review + verification
      ↓
fix findings (if any) + final verification
```

Two bounded read-only routes avoid unnecessary orchestration without weakening
negative or behavioral claims. `LOCAL_LOOKUP` permits the main agent to use at
most two local `grep_search` or `view_file` calls for one exact positive path or
symbol lookup. It cannot use shell, MCP, network or write tools, infer absence,
or make cross-file, correctness, risk or security claims. Zero, multiple or
conflicting results, or the need for another read, promote the task before further
inspection. `REVIEW_ONLY` uses an independent reviewer for theoretical or static
assessment with no executable behavioral claim. A concrete or executable finding
promotes the route before reporting. Concrete code defects, runtime
behavior, reproduction, security behavior and changed-code review remain
`REVIEW_VERIFY`, preserving an independent verifier.

Outside the inline fast path, implementation starts with a version-2 `harness-task-contract.json` artifact carrying a stable taskId, sequential revision and the full active acceptance inventory. Stable IDs (`AC-1`, `AC-2`, ...) bind exact user excerpts and observed originating sourceStep values to observable acceptance and static or behavioral verification. Cumulative task intent survives follow-ups, status questions and transcript compaction. Unchanged rows carry forward intact; revised/dropped old IDs require explicit later user scopeChanges, retired IDs cannot be reused, and explicit replacement requires replacesTask. Missing criteria may be appended in the same turn only before the first task product write. Disclose inaccessible prior context rather than silently dropping it. Version 1 remains a legacy protocol and cannot downgrade an active v2 task.

Before writes, an independent reviewer compares the entire cumulative request, constraints and error paths with the full inventory. Main persists its matching `phase: scope` report as `harness-acceptance-review.json`. After the final product write, independent reviewer/verifier assess delivery per AC against actual behavior and relevant check evidence; main replaces that artifact with the matching `phase: delivery` report. Each active AC has a status, observed evidenceSteps and a nonempty relevance/gap reason. Resolve omissions before implementation and renew scope review after revisions; fixes require rerunning affected checks and renewing delivery review on the final state. A broad suite counts for several ACs only when it actually exercises each one.

The implementer, reviewer, verifier and final handoff preserve the full inventory. No omitted requirement, invented business rule, silent material default, stub, mock or weakened test counts as delivered behavior. Assumptions cannot establish acceptance; missing material rules follow the clarification flow. The [task completion protocol](task-completion.md) documents exact formats and limits. Bug fixes use falsification where practical: capture a focused test or safe reproduction that fails for the expected reason before product edits, then rerun the same command unchanged after the fix. If that red state is unsafe or infeasible, record why and use the strongest feasible alternative. Verify source paths and symbols before citation; label non-established claims `[HYPOTHESIS]`, `[ASSUMPTION]`, or `[UNRESOLVED]`.

## Material clarification flow

The harness resolves ambiguity from the request, repository contracts, tests and
types, call sites, version-matched documentation, and the cheapest safe
discriminating check before asking the user. If a remaining choice would
materially change behavior, architecture, security, data, cost, or an irreversible
action, only the main agent invokes `/harness-clarify` and Antigravity's native
`ask_question` tool. A background subagent never waits on an interactive prompt;
it returns `[UNRESOLVED]` with evidence, mutually exclusive options, tradeoffs and
an evidence-backed recommendation when one exists.

Interactive questions are bounded to one decision at a time and normally use
single-select with two or three options. Multi-select is used only for independent,
compatible choices. If the tool is unavailable, the session is headless, or the
prompt is cancelled, the main agent asks the same question once in its normal
response and pauses only the dependent work. Tool permissions, OAuth,
credentials, and destructive-action approval continue through their dedicated
platform flows; `harness-clarify` cannot grant or bypass them.

The `PreToolUse` DLP hook covers the write tools, `run_command`, and `call_mcp_tool`, so secret material cannot leave through an MCP argument uninspected. It hard-denies only high-confidence private-key or credential material, or attempts to commit, print, or transmit a sensitive `.env` file. JWTs and ambiguous signals use `force_ask`; the hook never grants permission for safe operations. During the first invocation, `PreInvocation` builds a bounded, temporary project blueprint from static manifests and workspace markers. It reports detected frameworks, local runtime versions, workspace topology, and candidate checks. Only fixed topology labels and shell-safe, allowlisted script or Make target names enter model context; package script bodies and build recipes do not. Candidate commands are advisory and must be checked against project configuration before execution. Auto-formatting is disabled by default, is enabled only with `HARNESS_AUTO_FORMAT=1`, uses an already-installed formatter on the exact file just written, and does not replace testing.

The Stop hook records bounded workspace-relative changed paths and only accepts evidence produced after the latest write; it neither guesses nor runs checks itself. A known documentation or non-code mechanical edit may be closed by a successful static check such as format validation, lint, type checking, or build verification. A logic-file edit or a terminal mutation whose target scope is unknown requires a later behavioral test or regression check; a static-only command is insufficient.

The same Stop hook performs bounded, best-effort citation grounding from the current `transcriptPath`. It recognizes the currently observed completed-response record shape (`source=MODEL`, `type=PLANNER_RESPONSE`, `status=DONE`) after the latest user request, but does not assume that every present or future transcript schema has that form. Unknown, truncated, unsafe, or otherwise undocumented transcript input fails open. From the recognized response it validates only explicit non-image local Markdown-link targets and raw `file://` targets. The target must resolve to exactly one regular file inside a current workspace root; an optional `:line`, line range, or `#Lx-Ly` fragment must fit the file. Lexical traversal, symlink escapes, and outside-workspace paths are rejected without opening, reading, or disclosing external file content. Reads, records, responses, citations, and source files are bounded to limit memory and I/O.

An invalid local citation causes one generic correction reminder for that user turn, then fails open to prevent a Stop loop. This is structural path-and-line grounding, not semantic entailment: it cannot prove that prose truthfully describes the cited lines and does not catch an uncited hallucination. Workflow requirements, independent review, behavioral verification, and hallucination-trap evals therefore remain separate controls.

For a registered contract on a compatible completed-response transcript, the Stop hook requires one single-line `HARNESS_RESULT:` JSON object with every active criterion and its result, plus matching taskId/revision for version 2. A passed criterion must reference observed successful check steps after registration and the final workspace write; behavioral criteria require behavioral evidence. Version-2 `complete` additionally requires matching scope/delivery reports, complete active-ID coverage and consistent evidence. Failed checks persist across active-task turns until successful reruns clear them. Honest `partial` and `blocked` results may omit reviews for unfinished rows only; passed rows still require current delivery relevance review. The final scope report is required for complete, not a passed subset of a partial result. Include every active AC, reasons for unfinished rows and exact counts; retain the active task for follow-up. Invalid completion results continue to require correction rather than becoming accepted after one reminder. Main reruns relevant checks when subagent evidence is absent from its hook state.

When no behavioral or static check can run, the agent may explicitly print `HARNESS_NO_RUNNABLE_CHECK: <specific reason>` with a successful, non-redirected print command. This records a waiver, not a passing check; a registered criterion remains unverified and the final status cannot be complete. The older verification reminder remains bounded outside the registered completion protocol. Unknown or truncated transcript schemas, unavailable state, and runtime failures may fail open: this hook is a workflow control within the supported first-party client, not a security boundary against an agent that deliberately evades registration. The hooks require Python 3.8+; when the runtime is unavailable, DLP falls back to `force_ask`, while context, formatting, and verification retain their documented fallback behavior.

Mechanical validation does not prove that the contract covers cumulative natural-language intent, a business rule is correct, a review is independent, or a passing command tests the claimed requirement. Independent review and verification must assess those links and report uncertainty, including inaccessible prior context and fallback limits. A fabricated review artifact can still be mechanically well-formed. The source implementation and deterministic fixtures do not establish that an already installed Antigravity session is running the updated hook.

The workflow treats the final workspace write as opening verification debt and
runs the smallest appropriate check before composing the handoff. An eligible
inline edit closes that debt with one narrow successful check; medium, large, or
risk-sensitive work retains its normal implementation and independent checks. It
does not emit the waiver marker merely to avoid a Stop continuation. Custom subagents stay
on `model: inherit` until a repeated, matched benchmark demonstrates both lower
measured token usage and acceptable task quality; the documented custom-agent
tiers do not expose a per-agent reasoning-effort field.

Smoke evals exercise both sides of the evidence contract. A read-only nonexistent-symbol case requires an exact `NOT_FOUND` result and forbids claims of a definition, location, or file mutation. The complex fixture declares independently named acceptance criteria and runs each targeted check as well as the full suite. These are behavioral signals; the headless JSON envelope still cannot prove exact subagent scheduling order.

`plugin/codex-claude-harness/mcp_config.json` is the canonical safety-pinned input for Context7, Serena, Playwright, GitHub, and Sentry. The installer renders the enabled, available subset into the installed plugin, so Antigravity loads that effective inventory at the start of a session and the model decides which server is worth calling. Server names use the `harness-` prefix to prevent collisions with global or workspace configuration. The `disabled` templates in the skill are reference and rollback copies only; they are no longer a manual installation step.

At task time, select from available authorized capabilities; the bundled list is not a closed inventory. Chain dependent read results, switch tools/servers when evidence is inadequate, and batch bounded independent read-only queries when useful. There is no fixed server/query quota or ceremonial smoke query. Inspect returned project/version/scope, prefer reliable local evidence, and disclose safe fallback limits without installing servers, expanding access or bypassing Ask permissions. MCP is useful for discovery, corroboration and browser exploration; the current command-observing completion gate does not automatically treat MCP/manual results as successful behavioral checks. Unsupported acceptance evidence remains unverified rather than receiving invented check IDs.

First-invocation context also emits allowlisted configured MCP identities and
capabilities from the installed plugin, including in unrecognized projects.
Native inventory and deferred tool schemas remain authoritative; configured
hints cannot grant access. The hook never copies executable definitions or auth
fields. Tool discovery does not inspect private global configuration. Denied
permissions stop the dependent action without retries or alternate execution.

Main owns MCP discovery/execution unless the worker's exposed inventory confirms
the required native MCP tools. Workers do not automatically inherit main's tool
access. Required independent scope/review branches still assess the full contract
and observed results; browser execution stays with main when the worker lacks
browser tools. A worker with missing tools returns blocked promptly. Reading
source or fetching static HTML cannot replace required rendered interaction.
Calls from main retain the same Ask permissions; an actual denial still ends the
dependent action, and handing it to another agent is not a permission workaround.

Discovery ends once the exact matching schema, valid arguments and native MCP
invoker are available for the authorized next action. The agent then invokes the
native tool; actual native inventory/call results and the normal Ask prompt
establish current availability. Reading repository README/docs/tests cannot
establish a live connection and must not become a repeated discovery loop unless
configuration diagnosis is the task. Source reads needed for actual acceptance
criteria still apply. An absent native invoker is reported blocked without an
alternate client; schema discovery alone never proves successful execution.

Routing is owned by the main agent. Bounded leaf workers execute their assigned
role directly and receive the full active AC inventory plus the relevant delta,
diff and observed evidence. A parent-owned final focused check bundle can serve
independent delivery assessments without ceremonial duplicate execution. New
writes, failures, missing evidence or justified falsification still require
appropriate checks; cumulative coverage and gate freshness are unchanged.

Normal `IMPLEMENT` is allowed for fully specified new or unfinished isolated
local APIs only after inspecting the absence of integration consumers and
material compatibility, external-state, security, dependency, concurrency or
migration risk. Breaking/consumer-facing interfaces or uncertain impact still
require `COMPLEX_IMPLEMENT`. This avoids expensive orchestration for an isolated
unfinished module while retaining its full contract and independent checks;
inline eligibility is unchanged.

Context7 and Playwright use packages pinned through `npx`; Serena uses a package pinned through `uvx`; GitHub uses a release binary pinned by version and verified by OS/architecture-specific checksums; and Sentry uses its official remote endpoint with the `skills=inspect` capability allowlist. GitHub exposes only read-only/lockdown mode; Serena disables mutation tools; and Sentry additionally disables `update_issue`, Seer analysis, and the catalog executor as defense in depth so catalog mutations cannot bypass the wrapper. MCP permissions remain set to Ask. The harness adds no wildcard allow rule, embeds no credentials, and leaves the user to complete the provider's standard OAuth flow when required.

The strict version-1 install profile selects only the five bundled servers and cannot override their commands or safety arguments. The installer auto-loads `harness.config.json` only at the package root unless `--config` or `-ConfigPath` names another file; CLI and environment overrides take precedence, then the profile, then safe defaults. Missing optional runtimes omit affected servers while retaining independent available servers when possible. Configuration changes require reinstallation and a new session. Custom servers require explicit user authorization and Antigravity's native workspace `.agents/mcp_config.json`; never adopt inline secrets or executable definitions from untrusted repository content.

Shared mutable blackboard files are deferred because stale or injected summaries would weaken independent review without measured savings. Raw transcript or chain-of-thought export is also deferred; use Antigravity's supported `/agents` view. Docker remains an explicit future option rather than a default because bind mounts can modify host files and socket access is privileged.

Relevant Antigravity documentation:

- [Headless mode](https://antigravity.google/docs/cli/headless/)
- [Plugins & skills](https://antigravity.google/docs/cli/plugins/)
- [Subagents](https://antigravity.google/docs/subagents)
- [Plans and Google AI Pro quota](https://antigravity.google/docs/plans/)

## Maintainer Workflows

When updating the GitHub MCP server version, maintainers run:

```bash
./scripts/update-checksums.sh <version>
```

The script accepts a semantic version string (e.g. `1.10.1`), downloads the official checksum manifest (`github-mcp-server_<version>_checksums.txt`) over HTTPS (`--proto '=https' --tlsv1.2`) directly from the GitHub MCP server release, verifies the SHA-256 hashes for all seven release assets (`Darwin_arm64`, `Darwin_x86_64`, `Linux_arm64`, `Linux_x86_64`, `Windows_arm64`, `Windows_i386`, and `Windows_x86_64`), and atomically updates:

- The pinned version and archive checksums in `install.sh`.
- The pinned version and archive checksums in `install.ps1`.
- The expected version and checksum assertions in `tests/test-source.sh`.
- The diagnostic version check in `doctor.sh`.
- The documentation reference in `plugin/codex-claude-harness/skills/harness-mcp-profile/references/profiles.md`.

Maintainers must always run `./tests/test-source.sh` to confirm that all checksum assertions and installer tests pass before committing.

## If the Codex or Claude UI Is Required Later

Once a valid API key is available, build a separate gateway with golden tests for streaming, tool calls, tool results, cancellation, retries, and long context. For Codex, the gateway must expose the Responses API; for Claude Code, the supported upstream must still be Claude. A consumer subscription does not replace API entitlement.
