# Automatic MCP for the coding harness

The plugin automatically registers MCP servers while the installer runs. The AI selects a server according to the missing evidence; users do not need to edit `mcp_config.json` or install individual profiles.

- [Selection, scope, authentication, and fallback rules](../plugin/codex-claude-harness/skills/harness-mcp-profile/references/profiles.md)
- The runtime configuration is located at `plugin/codex-claude-harness/mcp_config.json`.
- Files in `plugin/codex-claude-harness/skills/harness-mcp-profile/assets/` are disabled templates for inspection and rollback, not routine installation steps.
- `./install.sh --skip-mcp` or `.\install.ps1 -SkipMcp` installs the core-only version when MCP bootstrap is not yet wanted or possible; the installer also falls back to this mode automatically if the GitHub MCP runtime or network is unavailable.
- `HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS` adds exact staging HTTP(S) origins during installation; the default loopback origins are always retained, and wildcards are rejected.
- Initialize Serena for a large repository with `uvx --from serena-agent==1.7.0 serena project create .`, then review `.serena/project.yml` before committing it.
