#!/usr/bin/env node

"use strict";

const fs = require("node:fs");

const [configPath, mode, origins] = process.argv.slice(2);
if (!configPath || !mode) {
  throw new Error("usage: configure-playwright-mcp.js <config-path> <allowlist|unrestricted> [origins]");
}

const config = JSON.parse(fs.readFileSync(configPath, "utf8"));
const args = config?.mcpServers?.["harness-playwright"]?.args;
if (!Array.isArray(args)) {
  throw new Error("Playwright MCP arguments are missing from mcp_config.json");
}

const allowlistIndex = args.indexOf("--allowed-origins");
if (allowlistIndex < 0 || allowlistIndex + 1 >= args.length) {
  throw new Error("Playwright allowlist argument is missing from mcp_config.json");
}

if (mode === "unrestricted") {
  args.splice(allowlistIndex, 2);
} else if (mode === "allowlist") {
  if (!origins) {
    throw new Error("Playwright allowlist mode requires at least one origin");
  }
  args[allowlistIndex + 1] = origins;
} else {
  throw new Error(`Unsupported Playwright origin mode: ${mode}`);
}

fs.writeFileSync(configPath, `${JSON.stringify(config, null, 2)}\n`);
