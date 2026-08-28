# Auto Harness for Antigravity

Turn Antigravity CLI into a coding agent with a Codex/Claude Code-style workflow: it reads the project, analyzes the task, plans, edits code, reviews the changes, and verifies the result.

Describe the request normally. The AI selects the appropriate workflow and subagents automatically — **there is no need to enter `/harness-plan`, `/harness-implement`, or `/harness-review`**.

## Features

- Handles questions, debugging, implementation, review, and testing automatically.
- 7 specialized subagents for research, implementation, review, verification, documentation, security, and databases.
- Automatically promotes high-risk changes to a workflow with research/planning, implementation, independent review, and independent verification.
- 10 skills for debugging, planning, implementation, review, testing, shipping, MCP, migration, ADRs, and benchmarking.
- Lifecycle hooks prevent secret leakage before tool calls, load stack context on the first invocation, support opt-in auto-formatting, and require verification after the final edit.
- Protects secrets and dirty worktrees and guards against operations that could cause data loss; the DLP gate never grants tool permission by itself.
- Includes smoke evals, fixture tests, and 5 coding MCP servers that the plugin registers for automatic AI selection.
- Uses the official Antigravity client and Google account quota; no Gemini API key is required.
- Supports macOS, Linux, and Windows.

## Installation

Clone the source:

```bash
git clone https://github.com/Ben110526/Integrate_harness_into_antigravity.git
cd Integrate_harness_into_antigravity
```

### macOS / Linux

```bash
./install.sh
```

On macOS, you can also double-click `install.command`.

### Windows

Double-click `install.cmd`, or run:

```powershell
.\install.cmd
```

The installer installs Antigravity CLI when necessary, installs the harness, downloads the official GitHub MCP with checksum verification, and registers the remaining MCP servers through the plugin. On first use, a browser may open for Google sign-in or to complete GitHub/Sentry OAuth when the AI actually needs those services.

MCP servers do not require separate installation, but the development machine must already have [Node.js 20.18.1+](https://nodejs.org/) (including `npx`) and [uv](https://docs.astral.sh/uv/) (including `uvx`). If a runtime, proxy, or GitHub Release is temporarily unavailable, the installer warns and installs a **core-only** version with no active MCP configuration; the policy, skills, subagents, and lifecycle hooks continue to work. Select this mode explicitly with `./install.sh --skip-mcp` or `.\install.ps1 -SkipMcp`, then rerun the installer normally to enable MCP.

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

The harness is always active. The AI classifies each request automatically; requests involving bugs, risks, regressions, or security trigger both review and verification. Changes involving public APIs, authentication, migrations, concurrency, security, or multiple coupled components use the `COMPLEX_IMPLEMENT` route, which includes research/planning, implementation, independent review, and independent verification. At the end of the response, the `Harness:` line identifies the route and checks that were used.

When schemas or migrations, security, or public documentation are materially relevant, the policy also routes to `harness-db-architect`, `harness-security-auditor`, or `harness-documenter`; they are not invoked ceremonially. The three new slash commands, `/harness-migration`, `/harness-adr`, and `/harness-benchmark`, remain explicit options rather than required steps.

Auto-formatting is disabled by default and should be enabled only for trusted repositories because project formatters, plugins, and configuration can execute code. Enable it for one session with `HARNESS_AUTO_FORMAT=1 agy`; the hook uses only installed/configured formatters and only on the exact file that was just edited. The four manual tasks in `.vscode/tasks.json` also let you open Antigravity, run doctor/source checks, or start an interactive High review from VS Code.

To prioritize coding accuracy, select **Gemini 3.7 Flash High** with `/model`; the selection is saved for later sessions. Use `/usage` to check quota, and run `./doctor.sh` to confirm that the High model is available on the current machine.

## AI-selected MCP servers

The plugin automatically registers namespaced MCP servers when the harness is installed. Users do not need to copy JSON, merge `.agents/mcp_config.json`, select a profile, or install individual servers. For each task, the AI prioritizes local source, compiler, and test evidence, then calls the smallest suitable MCP capability when additional evidence is needed:

- Context7: version-matched library documentation.
- Serena: symbols, references, and diagnostics for large codebases that already contain `.serena/project.yml`; uninitialized repositories automatically fall back to local tools to avoid dirtying the workspace.
- Playwright: browser state and UI exploration.
- GitHub: read-only Issue, PR, Actions, and security context.
- Sentry: read-only production issue, event, and trace data.

Context7 and Playwright automatically download pinned packages through `npx`; Serena downloads a pinned package through `uvx`; GitHub MCP uses the official release binary verified by the installer against its checksum; and Sentry uses the official endpoint with the `inspect` capability. GitHub runs with `--read-only --lockdown-mode`, Serena disables file/symbol editing tools, Sentry also disables update, AI-analysis, and catalog-execution tools, and every MCP server retains the default Ask permission.

To let Playwright access additional staging or preview environments, provide an exact allowlist during installation, for example `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com;https://staging.example.com:8443' ./install.sh`. The installer always retains the four default loopback origins and rejects wildcards, credentials, paths, queries, and fragments. In PowerShell: `$env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com'; .\install.ps1`.

Large repositories can create the official Serena configuration with `uvx --from serena-agent==1.7.0 serena project create .`; this command creates `.serena/project.yml`, so review it and then commit or ignore it according to the project's conventions. Add `--index` to create the symbol cache immediately.

See [automatic selection, authentication, and fallback behavior](docs/mcp-profiles.md). The AI never writes tokens, cookies, or client secrets to the repository. Provider OAuth still requires one-time user approval because the AI is not allowed to authorize account access by itself. Database, Docker, GitLab, and Bitbucket MCP servers remain opt-in until each environment has an endpoint and least-privilege access; see the [Phase 1 scope](docs/phase1-capabilities.md).

## Source checks

These checks do not require an Antigravity account:

```bash
./tests/test-source.sh
```

The smoke eval consumes quota and pins `gemini-3.7-flash-high`, so run it manually only after installing the plugin:

```bash
./evals/run-smoke.sh
```

## Updating

```bash
git pull
./install.sh
```

Windows: run `git pull`, then open `install.cmd` again.

When upgrading GitHub MCP, maintainers run `./scripts/update-checksums.sh <version>`. The script accepts only a semantic version, downloads the checksum manifest over HTTPS from the official release, verifies all seven assets, and atomically updates the installers, doctor, and source assertions; always run `./tests/test-source.sh` before committing.

Technical details and limitations: [docs/architecture.md](docs/architecture.md).
