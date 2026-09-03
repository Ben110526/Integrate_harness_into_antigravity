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
| `IMPLEMENT` | Localized, low-risk changes | Inline fast path (≤ 10 lines) or `harness-implementer` + `harness-verifier` |
| `COMPLEX_IMPLEMENT` | Major features, public API changes, auth, migrations, concurrency, security | Researcher → Plan (AC IDs) → Implementer → Parallel Reviewer & Verifier |

> [!NOTE]
> **Code Review Routes:**
> - `REVIEW_ONLY`: Conceptual or static analysis with independent `harness-reviewer` (no behavioral execution claims).
> - `REVIEW_VERIFY`: Concrete bug diagnosis, runtime behavior, security audits, or modified-code reviews, pairing `harness-reviewer` with `harness-verifier`.

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
- 🔒 **DLP PreToolUse**: Blocks leaks of private keys, tokens, and sensitive `.env` files before tool calls.
- 🗺️ **Context PreInvocation**: Injects a compact, bounded architectural blueprint on the first turn.
- 🎨 **Auto-Format PostToolUse**: Automatically formats edited files when enabled (`HARNESS_AUTO_FORMAT=1`).
- 🚦 **Verification & Grounding Gate (Stop)**: Enforces post-write verification and validates cited file paths and line ranges.

### 5 Bundled MCP Servers
- 📚 `harness-context7`: Fetches version-matched documentation for standard libraries and frameworks.
- 🧠 `harness-serena`: Semantic code intelligence and symbol graphs for large codebases (`.serena/project.yml`).
- 🌐 `harness-playwright`: Automated browser testing and UI exploration (loopback restricted by default).
- 🐙 `harness-github`: Read-only access to Issues, Pull Requests, CI Actions, and security alerts.
- 🚨 `harness-sentry`: Real-time production error, issue, and telemetry data inspection.

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
