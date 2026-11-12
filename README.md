# Auto Harness for Antigravity

[![OS: Linux | macOS | Windows](https://img.shields.io/badge/OS-Linux%20%7C%20macOS%20%7C%20Windows-blue.svg)](#-quick-start)
[![Model: Gemini 3.8 Flash High](https://img.shields.io/badge/Model-Gemini%203.8%20Flash%20High-8E24AA.svg)](#-usage)
[![CLI: Antigravity (agy)](https://img.shields.io/badge/CLI-Antigravity%20(agy)-00ACC1.svg)](https://antigravity.google)

Turn the official Antigravity CLI (`agy`) into an autonomous engineering agent with a rigorous, production-grade workflow: project understanding, task planning, scoped implementation, independent verification, and quality review. Subagents, skills, and tools are orchestrated automatically based on risk—no manual skill invocation required.

---

## ⚡ Quick Start

### Prerequisites
- [Antigravity CLI](https://antigravity.google) (`agy`)
- Python 3.8+
- [Node.js 20.18.1+](https://nodejs.org/) (or use the `--skip-mcp` flag if Node.js is not installed yet)

### macOS / Linux
Install via one command:
```bash
git clone https://github.com/Ben110526/Integrate_harness_into_antigravity.git && cd Integrate_harness_into_antigravity && ./install.sh
```
*(On macOS, you can also double-click `install.command`)*

### Windows (PowerShell / Command Prompt)
Install on Windows:
```powershell
git clone https://github.com/Ben110526/Integrate_harness_into_antigravity.git; cd Integrate_harness_into_antigravity; .\install.cmd
```
*(Or run directly in PowerShell: `powershell -ExecutionPolicy Bypass -File .\install.ps1`)*

<details>
<summary><b>⚙️ Advanced Installation Options</b></summary>

- **Core-only install (skip MCP servers):**
  - macOS / Linux:
    ```bash
    ./install.sh --skip-mcp
    ```
  - Windows:
    ```powershell
    .\install.ps1 -SkipMcp
    ```

- **Full web access for Playwright MCP:**
  By default, Playwright MCP is restricted to loopback (`localhost` / `127.0.0.1`). To grant full Internet access on a trusted machine:
  - macOS / Linux:
    ```bash
    ./install.sh --playwright-unrestricted
    ```
  - Windows:
    ```powershell
    .\install.ps1 -PlaywrightUnrestricted
    ```

- **Custom allowlist origins for Playwright (`HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS`):**
  - macOS / Linux:
    ```bash
    HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com' ./install.sh
    ```
  - Windows:
    ```powershell
    $env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = 'https://preview.example.com'; .\install.ps1
    ```

- **Explicit config profile:**
  - macOS / Linux:
    ```bash
    ./install.sh --config <path>
    ```
  - Windows:
    ```powershell
    .\install.ps1 -ConfigPath <path>
    ```

</details>

---

## 💡 Usage

Open your terminal in any project workspace and launch `agy`:

```bash
agy
```

Describe your task in natural language:

```text
Inspect this project and fix the login bug.
Review the current changes, prioritizing security issues.
Add a user-management API and run the tests.
Explain why the build is failing.
```

> [!TIP]
> **Recommended Model: Gemini 3.8 Flash High**
> 1. Run `/model` inside `agy`.
> 2. Select `gemini-3.8-flash-high`.
>
> Your selection is persisted across sessions. Use `/usage` to monitor your quota.

### Automatic Routing

The harness automatically determines task complexity and selects the optimal execution path:

| Route | Best For | Automatic Workflow |
|---|---|---|
| `DIRECT` | Conceptual explanations, general questions without code edits | Direct immediate answer |
| `LOCAL_LOOKUP` | Single file or symbol lookup | Up to 2 file reads, no subagent overhead |
| `RESEARCH` | Multi-file architecture analysis, complex root-cause diagnosis | Activates independent `harness-researcher` |
| `IMPLEMENT` | Localized, low-risk changes | Inline fast path for eligible tiny edits. Otherwise the verifier reviews scope, each independent implementation unit gets its own author, and the verifier reviews the combined result. The coordinator can implement a single unit directly. |
| `COMPLEX_IMPLEMENT` | Major features, public API changes, auth, migrations, concurrency, security | Researcher → Plan (AC IDs) → Independent Scope Review → Implementer → Parallel Delivery Reviewer & Verifier |

> [!NOTE]
> **Code Review Routes:**
> - `REVIEW_ONLY`: Conceptual or static analysis with independent `harness-reviewer` (no behavioral execution claims).
> - `REVIEW_VERIFY`: Concrete bug diagnosis, runtime behavior, security audits, or modified-code reviews, pairing `harness-reviewer` with `harness-verifier`.

Implementation outside the inline fast path keeps a version-2 acceptance contract across user turns, with a stable task ID and sequential revisions. Follow-ups refine the active task; progress questions and compaction do not erase earlier requirements. An independent scope review checks the full request before writes, and a delivery review explains the relevant evidence for each acceptance criterion after the final change. Explicit user scope changes or task replacement are recorded, and unfinished requirements remain visible: 2/4 passed means partial. See the [task completion protocol](docs/task-completion.md) for formats and enforcement limits; review independence and test relevance still require human or agent judgment.

### Coordinating parallel work

An ordinary request for two or more independently implementable outcomes triggers one `harness-implementer` per outcome after scope review. Each worker needs a separate write scope and enough information to finish without waiting for another worker's output. A project with date and currency formatters could use this prompt.

> Add tests for date formatting at midnight UTC and currency rounding to two decimal places. Put each set of cases in its formatter's test file, then run `npm test` on the combined changes.

Each assignment identifies its owner, writable files, relevant acceptance criteria and focused checks. The coordinator dispatches the independent units before waiting for handoffs. Shared edits and downstream work are ordered by dependency. Once every owner has handed back their changes, the coordinator inspects the combined diff, runs the relevant suite, and sends that evidence to the independent verifier. The final report identifies each owner and their files, the combined test result and any blockers.

To use Google's native Swarm, prefix the same prompt with `/swarm` in a supported Antigravity App or CLI. The existing Swarm workers and verifier use its board for assignments, blockers, and results. In the CLI, open `/swarm board` to follow them. Google introduced the preview in CLI 1.5.5 for Google AI Pro and Ultra subscribers, and each worker uses quota. [Swarm guide](https://antigravity.google/docs/swarm) · [CLI 1.5.5 release](https://github.com/google-antigravity/antigravity-cli/releases/tag/1.5.5)

The harness marks a criterion as verified only when the coordinator has check evidence from the combined changes. If a native session exposes only worker reports for that criterion, it stays unverified. An ordinary `agy` session lets the coordinator run the final check directly.

### Resuming an interrupted worker

After a worker hits a quota limit or its request times out, resume the original coordinator conversation in its working directory. The harness reconciles recorded assignments and worker messages with the existing diff. It asks the original author for any missing handoff, then runs the combined checks and requests fresh independent review.

On POSIX, a scheduler can run `python3 /path/to/installed/plugin/scripts/resume_after_quota.py JOB.json` when the provider's reset is due. The job file is private (mode `0600`) and names a private results directory (mode `0700`). It takes the following form.

```json
{
  "version": 1,
  "workspace": "/absolute/path/to/original/workspace",
  "conversation": "<original-coordinator-uuid>",
  "agy": "/absolute/path/to/agy",
  "notBefore": "2026-11-19T07:00:36Z",
  "resultsDirectory": "/absolute/path/to/private/job/results"
}
```

Omit `mode` to use the CLI's configured execution mode. If the original session had an explicit mode, set the same value in the job. A call before `notBefore` returns `scheduled`. At or after the deadline, the runner records its submission before launching the native CLI. Inspect `status.json` in the results directory for the native status, process exit and any reported acceptance claim. If an attempt was interrupted, inspect the original conversation before scheduling another attempt. [Task completion and handoffs](docs/task-completion.md)

On failure, `diagnostics` identifies a message from the current coordinator step, stderr or the terminal result. A resumed CLI can repeat an old quota message in its result. The runner calculates `retryNotBefore` only from a new coordinator step that reports a reset time. If the only quota message is in the terminal result, check the active account’s `/usage` for its current limit.

Jobs default to a 1,800-second CLI deadline. Set the optional integer `printTimeoutSeconds` to a positive number of seconds for another deadline, or to `0` for a supervised run that waits until the CLI exits. When a completed parent response matches the acceptance claim, `claimStep` records its step for comparison with the verifier’s evidence.

<details>
<summary><b>⚡ Auto-Approving Allowed Commands (Terminal Permissions)</b></summary>

By default, Antigravity CLI may prompt for approval before executing certain terminal commands. You can configure `settings.json` with an allowlist so safe inspection tools and standard test runners execute automatically without manual confirmation prompts.

#### How to open `settings.json`:
- **macOS / Linux:**
  - Location: `~/.gemini/antigravity-cli/settings.json`
  - Open via VS Code: `code ~/.gemini/antigravity-cli/settings.json`
  - Or open in default text editor: `open -e ~/.gemini/antigravity-cli/settings.json` (macOS) or `nano ~/.gemini/antigravity-cli/settings.json`
- **Windows:**
  - Location: `%USERPROFILE%\.gemini\antigravity-cli\settings.json`
  - Open via VS Code: `code $HOME\.gemini\antigravity-cli\settings.json`
  - Or open in Notepad: `notepad $HOME\.gemini\antigravity-cli\settings.json` (or press Win+R and run `notepad %USERPROFILE%\.gemini\antigravity-cli\settings.json`)

#### Recommended Configuration:
Add the allowlist rules under `permissions.allow`:

The installer never modifies `settings.json`, so your existing permissions stay
untouched. Keep default Ask for Git mutations, external actions and MCP calls.

> [!WARNING]
> Only auto-approve test/build runners (`npm run build`, `pnpm test`, …) for
> repositories you trust: these commands execute whatever the repository's
> `package.json` scripts contain, without a confirmation prompt.

```json
{
  "permissions": {
    "allow": [
      "command(pwd)",
      "command(ls)",
      "command(find)",
      "command(cat)",
      "command(head)",
      "command(tail)",
      "command(wc)",
      "command(grep)",
      "command(rg)",
      "command(file)",
      "command(stat)",
      "command(which)",
      "command(where)",
      "command(diff)",

      "command(Get-Location)",
      "command(Get-ChildItem)",
      "command(Get-Content)",
      "command(Select-String)",
      "command(Get-Item)",
      "command(Get-Command)",
      "command(Compare-Object)",

      "command(git status)",
      "command(git diff)",
      "command(git log)",
      "command(git show)",
      "command(git rev-parse)",
      "command(git ls-files)",
      "command(git grep)",

      "command(pytest)",
      "command(python -m pytest)",
      "command(python3 -m pytest)",
      "command(python -m unittest)",
      "command(python3 -m unittest)",

      "command(npm test)",
      "command(npm run (test|lint|typecheck|check|build))",
      "command(pnpm (test|lint|typecheck|check|build))",
      "command(yarn (test|lint|typecheck|check|build))",
      "command(bun test)",
      "command(deno test)",

      "command(go test)",
      "command(go vet)",
      "command(cargo test)",
      "command(cargo check)",
      "command(dotnet test)",
      "command(mvn test)",
      "command(gradle test)"
    ]
  }
}
```

</details>

---

## ✨ Core Capabilities

### 7 Specialized Subagents
- 🔍 `harness-researcher`: Locates source code, analyzes architecture, and traces system behavior.
- 🛠️ `harness-implementer`: Implements code changes strictly within the assigned scope.
- 🧐 `harness-reviewer`: Evaluates code quality, identifying regressions and logic vulnerabilities.
- ✅ `harness-verifier`: Executes independent test suites, validating real-world behavior and fixes.
- 📝 `harness-documenter`: Authors and standardizes user guides, API references, and changelogs.
- 🛡️ `harness-security-auditor`: Audits against OWASP vulnerabilities and prevents sensitive data leaks.
- 🗄️ `harness-db-architect`: Reviews database schemas, indexes, locks, and safe zero-downtime migrations.

### 4 Lifecycle Hooks
- 🔒 **DLP PreToolUse**: Blocks leaks of private keys, tokens, and sensitive `.env` files before write, terminal, and MCP tool calls.
- 🗺️ **Context PreInvocation**: Injects a compact, bounded architectural blueprint on the first turn.
- 🎨 **Auto-Format PostToolUse**: Automatically formats edited files when enabled (`HARNESS_AUTO_FORMAT=1`).
- 🚦 **Verification & Grounding Gate (Stop)**: Checks post-write evidence, cumulative task/review consistency and cited file paths/line ranges. It cannot prove semantic coverage or test relevance.

### 5 Bundled MCP Servers
- 📚 `harness-context7`: Fetches version-matched documentation for standard libraries and frameworks.
- 🧠 `harness-serena`: Semantic code intelligence and symbol graphs for large codebases (`.serena/project.yml`).
- 🌐 `harness-playwright`: Automated browser testing and UI exploration (loopback restricted by default).
- 🐙 `harness-github`: Read-only access to Issues, Pull Requests, CI Actions, and security alerts.
- 🚨 `harness-sentry`: Real-time production error, issue, and telemetry data inspection. **Note:** this is the one bundled server that runs remotely — tool arguments (issue IDs, search terms) are sent to `mcp.sentry.dev`, so avoid passing secrets or sensitive code.

The AI selects from available authorized capabilities, chains or switches tools when evidence warrants it, and can batch bounded independent read-only queries. There is no fixed server/query quota or mandatory smoke-call ceremony. Local evidence and safe fallbacks remain available; task-time use does not install servers or bypass permissions. MCP/manual results alone are not automatically completion-gate check evidence. See [adaptive MCP routing](docs/mcp-profiles.md#adaptive-use-during-a-task).

---

## 🩺 Troubleshooting & Diagnostics

Run the automated diagnostic health check to verify your environment (`agy`, Python, MCP servers, quota):
- **macOS / Linux:** `./doctor.sh`
- **Windows:** `.\doctor.ps1`

<details>
<summary><b>Frequently Asked Questions & Common Issues</b></summary>

- **Node.js missing during MCP setup:** Install [Node.js 20.18+](https://nodejs.org/) or install with `--skip-mcp` (macOS/Linux: `./install.sh --skip-mcp`, Windows: `.\install.ps1 -SkipMcp`).
- **`agy: command not found`:** Add `$HOME/.local/bin` to your `PATH` environment variable or restart your terminal.
- **Playwright external Internet access:** By default, Playwright is restricted to loopback (`localhost`). To enable Internet access, run `./install.sh --playwright-unrestricted` (macOS/Linux) or `.\install.ps1 -PlaywrightUnrestricted` (Windows).
- **Updating the harness:** Run `git pull && ./install.sh` (on Windows: run `git pull`, then execute `.\install.cmd` or `.\install.ps1`).
- **Uninstalling the harness:** Run `./uninstall.sh` (macOS/Linux) or `.\uninstall.ps1` (Windows). It removes the plugin, restores your pre-install `GEMINI.md` from the automatic `.bak` backup, and removes the pinned GitHub MCP binary. Your `settings.json` is never touched.
- **Python missing or upgraded:** The lifecycle hooks require Python 3.8+. Without it, DLP falls back to forced review, but the verification gate fails open (stops are allowed) to avoid lockouts. `doctor.sh` / `doctor.ps1` detects a missing or invalid hook runtime; rerun the installer to repair it.

</details>

---

## 🧪 Documentation & Testing

Run deterministic repository checks without consuming model quota:
```bash
./tests/test-source.sh
```

### Deep-Dive Documentation
- [Detailed Architecture & Security Controls (docs/architecture.md)](docs/architecture.md)
- [MCP Configuration & Network Permissions (docs/mcp-profiles.md)](docs/mcp-profiles.md)
- [Eval Harness & Benchmark Methodology (evals/README.md)](evals/README.md)
