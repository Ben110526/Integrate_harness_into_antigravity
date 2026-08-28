# Automatic MCP for the coding harness

The plugin automatically registers MCP servers while the installer runs. The AI selects a server according to the missing evidence; users do not need to edit `mcp_config.json` or install individual profiles.

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

The AI still decides when to call Playwright. These options only change its network scope. Unrestricted mode retains isolation, headless mode, and MCP Ask permission. Rerun the installer without either option to restore the loopback-only default, and start a new `agy` session after changing modes.

## Other configuration

- [Selection, scope, authentication, and fallback rules](../plugin/codex-claude-harness/skills/harness-mcp-profile/references/profiles.md)
- The runtime configuration is located at `plugin/codex-claude-harness/mcp_config.json`.
- Files in `plugin/codex-claude-harness/skills/harness-mcp-profile/assets/` are disabled templates for inspection and rollback, not routine installation steps.
- `./install.sh --skip-mcp` or `.\install.ps1 -SkipMcp` installs the core-only version when MCP bootstrap is not yet wanted or possible; the installer also falls back to this mode automatically if the GitHub MCP runtime or network is unavailable.
- Initialize Serena for a large repository with `uvx --from serena-agent==1.7.0 serena project create .`, then review `.serena/project.yml` before committing it.
