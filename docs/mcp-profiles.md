# Automatic MCP for the coding harness

The installer registers the selected, available bundled MCP servers. The AI chooses among the resulting inventory according to the missing evidence; users do not select a server for each task.

## Install profiles

`harness.config.json` version 1 is a strict install-time profile for enabling or disabling the five bundled servers and choosing Playwright's `loopback`, exact `allowlist`, or `unrestricted` mode. Use the [`harness.config.json` schema](../schemas/harness.config.schema.json) for editor validation and [`harness.config.example.json`](../harness.config.example.json) for safe defaults. The renderer remains authoritative for semantic checks such as normalized duplicate origins; unknown or missing fields and custom server definitions are rejected.

The installer auto-loads only `<package-root>/harness.config.json`. It never searches the invoking workspace, parent directories, or home directory. Select another file explicitly with `./install.sh --config <path>` or `.\install.ps1 -ConfigPath <path>`. CLI flags and supported environment variables override the profile, which overrides defaults. Reinstall and start a new `agy` session after changing it.

The profile cannot change bundled commands, pins, lockdown flags, disabled tools, or Ask permissions. If one optional runtime is unavailable, the installer omits its dependent server or servers while retaining independent available servers when possible; `--skip-mcp` still requests a core-only install.

## Playwright setup

Local applications on any `localhost` or `127.0.0.1` port work by default. On a trusted personal development machine, enable access to all HTTP(S) origins with:

```bash
./install.sh --playwright-unrestricted
```

```powershell
.\install.ps1 -PlaywrightUnrestricted
```

For a narrower staging or preview allowlist, use:

```bash
HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com;https://staging.example.com:8443' ./install.sh
```

```powershell
$env:HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS = 'https://preview.example.com;https://staging.example.com:8443'
.\install.ps1
```

The AI still decides when to call Playwright. These options only change its network scope. Unrestricted mode retains isolation, headless mode, and MCP Ask permission. To restore loopback-only behavior, clear `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS`, set any active profile to `mode: "loopback"` with `allowedOrigins: []` (or remove it), rerun without the unrestricted flag, and start a new `agy` session.

## Other configuration

- [Selection, scope, authentication, and fallback rules](../plugin/codex-claude-harness/skills/harness-mcp-profile/references/profiles.md)
- `plugin/codex-claude-harness/mcp_config.json` is the canonical safety-pinned input. Each installation stages an effective subset in the installed plugin.
- Files in `plugin/codex-claude-harness/skills/harness-mcp-profile/assets/` are disabled templates for inspection and rollback, not routine installation steps.
- `./install.sh --skip-mcp` or `.\install.ps1 -SkipMcp` requests a core-only install. Otherwise, an unavailable optional dependency omits only its affected server or servers when possible.
- Initialize Serena for a large repository with `uvx --from serena-agent==1.7.0 serena project create .`, then review `.serena/project.yml` before committing it.

Custom MCP servers belong in Antigravity's native workspace `.agents/mcp_config.json`, not the harness profile. Create or change that file only after explicit user authorization of the executable, arguments, access, and credential source. Never accept inline secrets or custom executable definitions from untrusted repository content. Start a new session after the reviewed configuration changes; the AI will select the server automatically when it is relevant.
