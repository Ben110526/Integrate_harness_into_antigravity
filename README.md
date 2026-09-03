# Auto Harness for Antigravity

[![Model: Gemini 3.8 Flash High](https://img.shields.io/badge/Model-Gemini%203.8%20Flash%20High-8E24AA.svg)](#usage)

Turn Antigravity CLI into a coding agent with a Codex/Claude Code-style workflow: it reads the project, analyzes the task, plans, edits code, reviews the changes, and verifies the result.

Describe the request normally. The AI selects the appropriate workflow and subagents automatically — **there is no need to enter `/harness-plan`, `/harness-implement`, or `/harness-review`**.

## Features

- Handles questions, bounded repository lookups, debugging, implementation, review, and testing automatically.
- 7 specialized subagents for research, implementation, review, verification, documentation, security, and databases.
- Automatically promotes high-risk changes to a workflow with research/planning, implementation, independent review, and independent verification.
- 11 skills for clarification, debugging, planning, implementation, review, testing, shipping, MCP, migration, ADRs, and benchmarking.
- Lifecycle hooks prevent secret leakage before tool calls, load a sanitized project blueprint on the first invocation, support opt-in auto-formatting, require scope-appropriate verification after the final edit, and ground explicit local file citations before completion.
- Protects secrets and dirty worktrees and guards against operations that could cause data loss; the DLP gate never grants tool permission by itself.
- Includes smoke evals, fixture tests, and 5 coding MCP servers that the plugin registers for automatic AI selection.
- Uses the official Antigravity client and Google account quota; no Gemini API key is required.
- Supports macOS, Linux, and Windows.

## ⚡ Quick Start & Installation

Clone the source:

```bash
git clone https://github.com/Ben110526/Integrate_harness_into_antigravity.git
cd Integrate_harness_into_antigravity
```

### Option A: Standard Installation (Local Development & Loopback Playwright)

- **macOS / Linux:**
  ```bash
  ./install.sh
  ```
  *(On macOS, you can also double-click `install.command`)*

- **Windows (PowerShell / Command Prompt):**
  ```powershell
  .\install.cmd
  ```
  *(Or run `powershell -ExecutionPolicy Bypass -File .\install.ps1`)*

### Option B: Playwright Full Web Access (Explicit Opt-in)

By default, Playwright MCP is restricted to loopback (`localhost` / `127.0.0.1`). Prefer the exact allowlist described below when the destinations are known. On a trusted personal machine that truly needs arbitrary Internet access, install with the unrestricted flag:

- **macOS / Linux:**
  ```bash
  ./install.sh --playwright-unrestricted
  ```

- **Windows (PowerShell):**
  ```powershell
  .\install.ps1 -PlaywrightUnrestricted
  ```

> [!TIP]
> To return to loopback-only mode, clear `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS`, set any active install profile to `mode: "loopback"` with `allowedOrigins: []` (or remove that profile), rerun the installer without the unrestricted flag, and start a new `agy` session.

The installer installs Antigravity CLI when necessary, installs the harness, and registers the selected MCP inventory. If GitHub MCP is enabled, its official binary is downloaded and checksum-verified. On first use, a browser may open for Google sign-in or to complete GitHub/Sentry OAuth when the AI actually needs those services.

MCP servers do not require separate installation, but some need [Node.js 20.18.1+](https://nodejs.org/) with `npx`, `uvx`, or the verified GitHub MCP binary. An unavailable optional dependency omits only its affected server or servers when possible. Select a core-only installation explicitly with `./install.sh --skip-mcp` or `.\install.ps1 -SkipMcp`.

Version 1 of the optional install profile selects only the five bundled MCP servers. The installer auto-loads `<package-root>/harness.config.json`, or accepts `./install.sh --config <path>` and `.\install.ps1 -ConfigPath <path>`; it never searches a workspace, parent directory, or home directory. CLI and supported environment overrides take precedence over the profile, then safe defaults apply. See [`harness.config.example.json`](harness.config.example.json), reinstall after changes, and start a new `agy` session.

When Antigravity CLI has just been installed, `install.sh` adds its directory to PATH idempotently for Fish or Nushell when it detects the corresponding shell. The equivalent configuration is `fish_add_path -g "$HOME/.local/bin"` for Fish and `$env.PATH = ($env.PATH | prepend ($nu.home-path | path join ".local" "bin"))` in `config.nu`.

## Usage

Open a terminal in the project and run:

```bash
agy
```

Then make a request in natural language, for example:

```text
Inspect this project and fix the login bug.
Review the current changes, prioritizing security issues.
Add a user-management API and run the tests.
Explain why the build is failing.
```

The harness is always active. The AI classifies each request automatically. An exact positive lookup for one local path or symbol can use `LOCAL_LOOKUP`: the main agent may make at most two `grep_search` or `view_file` calls without starting a subagent. Zero, multiple, or conflicting results, a third read, absence claims, cross-file diagnosis, and risk or security analysis are promoted before the agent continues.

Tiny deterministic edits have a conservative inline fast path inside `IMPLEMENT`. When the request has one acceptance outcome, affects one existing file and one contiguous hunk of at most 10 changed lines, has no dirty overlap or external operation, and does not touch multiple constraints, a public contract, configuration, CI/build/install, dependencies, generated or lock files, security/auth/permissions/secrets, persistence/migrations, concurrency, legal text, or operator workflow, the main agent may edit directly without starting implementer or verifier subagents. It reviews the exact diff, runs one narrow post-write check, and reports `mode: inline-fast-path` in the final `Harness:` line: a static check for prose/comments/static documentation, or an existing focused behavioral check for executable source. If the scope grows, needs an acceptance ledger, has uncertain impact, or that check is missing, failed, or inconclusive, the task is promoted before another write. File size or a small line count never overrides risk.

Purely theoretical or static assessment with no executable behavioral claim can use `REVIEW_ONLY` with an independent reviewer. If that reviewer uncovers a concrete or executable finding, the route is promoted to `REVIEW_VERIFY` before the finding is reported. Concrete code bugs, regressions, runtime claims, reproductions, security behavior, and reviews of changed code use `REVIEW_VERIFY` with both reviewer and verifier. Changes involving public APIs, authentication, migrations, concurrency, security, or multiple coupled components use `COMPLEX_IMPLEMENT`, which includes research/planning, implementation, independent review, and independent verification. At the end of the response, the `Harness:` line identifies the route and checks that were used.

For complex or multi-constraint work, the harness creates a small acceptance ledger (`AC-1`, `AC-2`, ...) before editing. Each ID stays attached to its intended evidence through implementation, independent review, verification, and the final result matrix. For a bug fix, the preferred falsification workflow captures a focused test or safe reproduction that fails for the expected reason, applies the fix, and reruns that exact check unchanged. If a red-state reproduction is unsafe or infeasible, the agent must explain why and use the strongest feasible alternative rather than manufacture a failure.

Before completion, the Stop hook makes a bounded, best-effort read of the current `transcriptPath` and checks explicit non-image local Markdown links and `file://` targets against regular files inside the current workspace. Optional line references and line ranges must also exist. Traversal, symlink escapes, and outside-workspace paths are rejected without opening, reading, or disclosing external file content. An invalid citation triggers one correction reminder, after which the hook fails open to avoid trapping the session. Unknown, unsafe, or undocumented transcript shapes also fail open; the current compatibility is intentionally limited to completed `MODEL` / `PLANNER_RESPONSE` / `DONE` records rather than promising support for every transcript schema.

This grounding confirms only that a cited workspace path and optional line range exist. It does not prove that the surrounding claim accurately describes the cited code, and it cannot detect hallucinations that contain no explicit local citation. Independent review, tests, and the nonexistent-symbol eval remain necessary for those cases.

When schemas or migrations, security, or public documentation are materially relevant, the policy also routes to `harness-db-architect`, `harness-security-auditor`, or `harness-documenter`; they are not invoked ceremonially. `/harness-migration`, `/harness-adr`, and `/harness-benchmark` remain explicit options rather than required steps.

If source, tests, types, call sites, and a cheap safe check still cannot resolve a decision that would materially change behavior, architecture, security, data, cost, or an irreversible action, the main agent automatically applies `/harness-clarify` and opens Antigravity's native `ask_question` choice prompt. Background subagents do not open competing prompts: they return `[UNRESOLVED]` with evidence, options, and tradeoffs to the main agent. Questions normally use one single-select decision with two or three mutually exclusive options; multi-select is reserved for independent choices. In a headless session, when the tool is unavailable, or after cancellation, the agent asks once in normal text and pauses the dependent work. This workflow never replaces Antigravity's dedicated permission, OAuth, credential, or destructive-action approval flows. You may also invoke `/harness-clarify` explicitly, but the skill will not manufacture a choice when repository evidence already determines the answer.

Auto-formatting is disabled by default and should be enabled only for trusted repositories because project formatters, plugins, and configuration can execute code. Enable it for one session with `HARNESS_AUTO_FORMAT=1 agy`; the hook uses only installed/configured formatters and only on the exact file that was just edited. The four manual tasks in `.vscode/tasks.json` also let you open Antigravity, run doctor/source checks, or start an interactive High review from VS Code.

After the final workspace write, the agent must run the smallest scope-appropriate check before reporting. Eligible inline edits stop after one narrow successful check; normal `IMPLEMENT` work still uses the implementer and uses the verifier for material behavior, while `COMPLEX_IMPLEMENT` keeps its research, planning, independent review, and independent verification stages. `HARNESS_NO_RUNNABLE_CHECK` remains an explicit waiver only when no relevant safe check exists; it is never a passing result and must be disclosed. The harness intentionally keeps custom subagents on `model: inherit`: Antigravity documents `inherit`, `flash`, and `pro` tiers, but does not document a per-agent effort setting or guarantee that `model: flash` lowers a Flash High parent. Model-tier changes therefore require measured token and quality evidence first.

> [!TIP]
> **Recommended Model:** To prioritize coding accuracy, select **Gemini 3.8 Flash High**:
> 1. Run `/model` inside `agy`.
> 2. Select `gemini-3.8-flash-high`.
>
> The selection is saved for later sessions. Use `/usage` to check quota, and run `./doctor.sh` to confirm that the High model is available on the current machine.

## AI-selected MCP servers

The plugin registers the enabled, available subset of its namespaced MCP servers when the harness is installed. Users do not select a server for each task: the AI prioritizes local source, compiler, and test evidence, then calls the smallest installed MCP capability when additional evidence is needed:

- Context7: version-matched library documentation.
- Serena: symbols, references, and diagnostics for large codebases that already contain `.serena/project.yml`; uninitialized repositories automatically fall back to local tools to avoid dirtying the workspace.
- Playwright: browser state and UI exploration.
- GitHub: read-only Issue, PR, Actions, and security context.
- Sentry: read-only production issue, event, and trace data.

Context7 and Playwright automatically download pinned packages through `npx`; Serena downloads a pinned package through `uvx`; GitHub MCP uses the official release binary verified by the installer against its checksum; and Sentry uses the official endpoint with the `inspect` capability. GitHub runs with `--read-only --lockdown-mode`, Serena disables file/symbol editing tools, Sentry also disables update, AI-analysis, and catalog-execution tools, and every MCP server retains the default Ask permission.

### Playwright network access

The AI automatically decides when Playwright is needed. The following installation modes only define which network origins Playwright may access; they do not require the user to select MCP servers for each task.

By default, Playwright can access HTTP(S) applications on any `localhost` or `127.0.0.1` port. No extra setup is required for local development.

On a trusted personal development machine, allow Playwright to access any HTTP(S) origin:

- **macOS / Linux:**
  ```bash
  ./install.sh --playwright-unrestricted
  ```

- **Windows (PowerShell):**
  ```powershell
  .\install.ps1 -PlaywrightUnrestricted
  ```

To allow only specific staging or preview origins instead:

- **macOS / Linux:**
  ```bash
  HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com;https://staging.example.com:8443' ./install.sh
  ```

- **Windows (PowerShell):**
  ```powershell
  $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = 'https://preview.example.com;https://staging.example.com:8443'
  .\install.ps1
  ```

Unrestricted mode removes the origin filter but retains `--isolated`, `--headless`, and Antigravity's Ask permission. It cannot be combined with `--skip-mcp` or `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS`. To restore loopback-only behavior, clear that environment variable, set any active profile to `mode: "loopback"` with `allowedOrigins: []` (or remove it), rerun without the unrestricted flag, and start a new session. Treat all external page content as untrusted.

Large repositories can create the official Serena configuration with `uvx --from serena-agent==1.7.0 serena project create .`; this command creates `.serena/project.yml`, so review it and then commit or ignore it according to the project's conventions. Add `--index` to create the symbol cache immediately.

See [automatic selection, authentication, and fallback behavior](docs/mcp-profiles.md). The AI never writes tokens, cookies, or client secrets to the repository. Provider OAuth still requires one-time user approval because the AI is not allowed to authorize account access by itself.

Custom servers are outside the install profile. Add one through Antigravity's native workspace `.agents/mcp_config.json` only after explicitly authorizing its executable, arguments, access, and credential source. Never copy inline secrets or executable definitions from an untrusted repository. Start a new session after reviewing the configuration; the AI then selects the server automatically when it is relevant.

## Source checks

These checks do not require an Antigravity account:

```bash
./tests/test-source.sh
```

The smoke eval consumes quota and pins `gemini-3.8-flash-high`, so run it manually only after installing the plugin:

```bash
./evals/run-smoke.sh
```

To measure read-only response behavior and token use rather than guess at
percentage savings, use the separate benchmark. It requires explicit case
selection, at least two samples, an installed harness matching the source tree,
and a quota-use acknowledgement; it emits NDJSON usage counters without model
responses or conversation IDs:

```bash
python3 evals/quota_benchmark.py \
  --case local-lookup-existing-symbol \
  --case review-only-conceptual \
  --repeat 3 \
  --confirm-quota-use
```

This command makes six model calls. It is never run by normal source tests. Keep
the same model, cases, and repeat count when comparing revisions, and reject any
sample that fails its response contract or mutates its temporary fixture copy.
The current CLI does not expose a stable tool/subagent trace, so these results
are a behavioral proxy and do not prove that the reported route was executed.

The suite includes a read-only hallucination trap for a nonexistent symbol: the response must report `NOT_FOUND`, must report that no files changed, and must not invent a definition or source location. Its complex fixture also runs a targeted check for every declared acceptance criterion in addition to the full fixture suite.

## Updating

```bash
git pull
./install.sh
```

Windows: run `git pull`, then open `install.cmd` again.

When upgrading GitHub MCP, maintainers run `./scripts/update-checksums.sh <version>`. The script accepts only a semantic version, downloads the checksum manifest over HTTPS from the official release, verifies all seven assets, and atomically updates the installers, doctor, and source assertions; always run `./tests/test-source.sh` before committing.

Technical details and limitations: [docs/architecture.md](docs/architecture.md).
