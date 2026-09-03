#!/usr/bin/env node

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const SERVER_NAMES = ["context7", "serena", "playwright", "github", "sentry"];
const RUNTIME_NAMES = Object.fromEntries(SERVER_NAMES.map((name) => [name, `harness-${name}`]));
const DANGEROUS_KEYS = new Set(["__proto__", "prototype", "constructor"]);
const FORBIDDEN_CANONICAL_KEYS = new Set(["env", "headers", "oauth"]);
const EXACT_ORIGIN = /^https?:\/\/[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?(?::([0-9]{1,5}))?$/;
const VALUE_OPTIONS = new Set([
  "--input",
  "--output",
  "--config",
  "--disable-server",
  "--playwright-mode",
  "--playwright-origins",
  "--playwright-extra-origins",
]);

function fail(message) {
  const error = new Error(message);
  error.name = "HarnessConfigError";
  throw error;
}

function isRecord(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertRecord(value, location) {
  if (!isRecord(value)) {
    fail(`${location} must be an object`);
  }
}

function assertExactKeys(value, allowed, required, location) {
  assertRecord(value, location);
  for (const key of Object.keys(value)) {
    if (!allowed.includes(key)) {
      fail(`${location} contains unknown key ${JSON.stringify(key)}`);
    }
  }
  for (const key of required) {
    if (!Object.prototype.hasOwnProperty.call(value, key)) {
      fail(`${location} is missing required key ${JSON.stringify(key)}`);
    }
  }
}

function parseJsonFile(filePath, label) {
  let contents;
  try {
    contents = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    fail(`could not read ${label} at ${filePath}: ${error.message}`);
  }

  try {
    if (contents.charCodeAt(0) === 0xfeff) {
      contents = contents.slice(1);
    }
    return JSON.parse(contents, (key, value) => {
      if (DANGEROUS_KEYS.has(key)) {
        fail(`${label} contains forbidden key ${JSON.stringify(key)}`);
      }
      return value;
    });
  } catch (error) {
    if (error.name === "HarnessConfigError") {
      throw error;
    }
    fail(`${label} at ${filePath} is not valid JSON: ${error.message}`);
  }
}

function validateOrigin(origin, location) {
  if (typeof origin !== "string" || !EXACT_ORIGIN.test(origin)) {
    fail(`${location} must be an exact HTTP(S) origin without a wildcard, path, query, fragment, or credentials`);
  }
  const portMatch = origin.match(EXACT_ORIGIN);
  if (portMatch[1]) {
    const port = Number(portMatch[1]);
    if (port < 1 || port > 65535) {
      fail(`${location} contains an invalid port`);
    }
  }
}

function defaultUserConfig() {
  return {
    version: 1,
    mcp: {
      servers: {
        context7: { enabled: true },
        serena: { enabled: true },
        playwright: { enabled: true, mode: "loopback", allowedOrigins: [] },
        github: { enabled: true },
        sentry: { enabled: true },
      },
    },
  };
}

function validateUserConfig(config) {
  assertExactKeys(config, ["version", "mcp"], ["version", "mcp"], "configuration");
  if (config.version !== 1) {
    fail("configuration.version must be exactly 1");
  }
  assertExactKeys(config.mcp, ["servers"], ["servers"], "configuration.mcp");
  assertExactKeys(
    config.mcp.servers,
    SERVER_NAMES,
    SERVER_NAMES,
    "configuration.mcp.servers",
  );

  for (const name of SERVER_NAMES) {
    const server = config.mcp.servers[name];
    const allowedKeys = name === "playwright" ? ["enabled", "mode", "allowedOrigins"] : ["enabled"];
    assertExactKeys(server, allowedKeys, allowedKeys, `configuration.mcp.servers.${name}`);
    if (typeof server.enabled !== "boolean") {
      fail(`configuration.mcp.servers.${name}.enabled must be a boolean`);
    }
  }

  const playwright = config.mcp.servers.playwright;
  if (!["loopback", "allowlist", "unrestricted"].includes(playwright.mode)) {
    fail("configuration.mcp.servers.playwright.mode must be loopback, allowlist, or unrestricted");
  }
  if (!Array.isArray(playwright.allowedOrigins)) {
    fail("configuration.mcp.servers.playwright.allowedOrigins must be an array");
  }
  if (playwright.mode === "allowlist" && playwright.allowedOrigins.length === 0) {
    fail("Playwright allowlist mode requires at least one allowed origin");
  }
  if (playwright.mode !== "allowlist" && playwright.allowedOrigins.length !== 0) {
    fail(`Playwright ${playwright.mode} mode requires an empty allowedOrigins array`);
  }

  const seenOrigins = new Set();
  playwright.allowedOrigins.forEach((origin, index) => {
    validateOrigin(origin, `configuration.mcp.servers.playwright.allowedOrigins[${index}]`);
    const identity = new URL(origin).origin.toLowerCase();
    if (seenOrigins.has(identity)) {
      fail("configuration.mcp.servers.playwright.allowedOrigins must not contain duplicates");
    }
    seenOrigins.add(identity);
  });

  return config;
}

function assertArrayIncludes(array, expected, location) {
  if (!Array.isArray(array)) {
    fail(`${location} must be an array`);
  }
  for (const value of expected) {
    if (!array.includes(value)) {
      fail(`${location} is missing required safety value ${JSON.stringify(value)}`);
    }
  }
}

function assertArrayEquals(array, expected, location) {
  if (!Array.isArray(array) ||
      array.length !== expected.length ||
      array.some((value, index) => value !== expected[index])) {
    fail(`${location} must exactly match the pinned safety configuration`);
  }
}

function rejectCanonicalSecrets(value, location = "canonical MCP configuration") {
  if (Array.isArray(value)) {
    value.forEach((entry, index) => rejectCanonicalSecrets(entry, `${location}[${index}]`));
    return;
  }
  if (!isRecord(value)) {
    return;
  }
  for (const [key, entry] of Object.entries(value)) {
    if (FORBIDDEN_CANONICAL_KEYS.has(key)) {
      fail(`${location} must not contain ${JSON.stringify(key)}`);
    }
    rejectCanonicalSecrets(entry, `${location}.${key}`);
  }
}

function validateCanonicalConfig(config) {
  assertExactKeys(config, ["mcpServers"], ["mcpServers"], "canonical MCP configuration");
  const expectedNames = SERVER_NAMES.map((name) => RUNTIME_NAMES[name]);
  assertExactKeys(config.mcpServers, expectedNames, expectedNames, "canonical MCP configuration.mcpServers");
  rejectCanonicalSecrets(config);

  for (const runtimeName of expectedNames) {
    const server = config.mcpServers[runtimeName];
    assertRecord(server, `canonical MCP configuration.mcpServers.${runtimeName}`);
    if (server.disabled !== false) {
      fail(`canonical MCP server ${runtimeName} must be enabled before rendering`);
    }
    const transports = ["command", "serverUrl"].filter((key) => Object.prototype.hasOwnProperty.call(server, key));
    if (transports.length !== 1) {
      fail(`canonical MCP server ${runtimeName} must define exactly one transport`);
    }
  }

  const context7 = config.mcpServers[RUNTIME_NAMES.context7];
  assertExactKeys(context7, ["command", "args", "disabled"], ["command", "args", "disabled"], "canonical Context7 MCP");
  if (context7.command !== "npx") {
    fail("canonical Context7 MCP must use npx");
  }
  assertArrayEquals(context7.args, ["-y", "@upstash/context7-mcp@4.0.3"], "canonical Context7 MCP args");

  const serena = config.mcpServers[RUNTIME_NAMES.serena];
  assertExactKeys(serena, ["command", "args", "disabledTools", "disabled"], ["command", "args", "disabledTools", "disabled"], "canonical Serena MCP");
  if (serena.command !== "uvx") {
    fail("canonical Serena MCP must use uvx");
  }
  assertArrayEquals(
    serena.args,
    [
      "--from",
      "serena-agent==1.7.0",
      "serena",
      "start-mcp-server",
      "--context=antigravity",
      "--enable-web-dashboard=false",
      "--enable-gui-log-window=false",
      "--open-web-dashboard=false",
    ],
    "canonical Serena MCP args",
  );
  assertArrayIncludes(
    serena.disabledTools,
    [
      "insert_after_symbol",
      "insert_before_symbol",
      "rename_symbol",
      "replace_symbol_body",
      "safe_delete_symbol",
      "execute_shell_command",
      "create_text_file",
      "delete_lines",
      "insert_at_line",
      "replace_content",
      "replace_in_files",
      "replace_lines",
      "remove_project",
      "open_dashboard",
      "delete_memory",
      "edit_memory",
      "rename_memory",
      "write_memory",
      "onboarding",
    ],
    "canonical Serena MCP disabledTools",
  );

  const playwright = config.mcpServers[RUNTIME_NAMES.playwright];
  assertExactKeys(playwright, ["command", "args", "disabled"], ["command", "args", "disabled"], "canonical Playwright MCP");
  if (playwright.command !== "npx") {
    fail("canonical Playwright MCP must use npx");
  }
  assertArrayEquals(
    playwright.args,
    [
      "-y",
      "@playwright/mcp@0.0.79",
      "--isolated",
      "--headless",
      "--allowed-origins",
      "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*",
    ],
    "canonical Playwright MCP args",
  );
  const allowlistIndexes = playwright.args
    .map((argument, index) => (argument === "--allowed-origins" ? index : -1))
    .filter((index) => index >= 0);
  if (allowlistIndexes.length !== 1 || allowlistIndexes[0] + 1 >= playwright.args.length) {
    fail("canonical Playwright MCP must contain one complete origin allowlist pair");
  }

  const github = config.mcpServers[RUNTIME_NAMES.github];
  assertExactKeys(github, ["command", "args", "disabled"], ["command", "args", "disabled"], "canonical GitHub MCP");
  if (github.command !== "codex-harness-github-mcp-server") {
    fail("canonical GitHub MCP must use the checksum-verified harness binary");
  }
  assertArrayEquals(
    github.args,
    [
      "stdio",
      "--read-only",
      "--lockdown-mode",
      "--oauth-scopes=repo,read:org",
      "--toolsets=context,repos,issues,pull_requests,actions,code_security,secret_protection",
    ],
    "canonical GitHub MCP args",
  );

  const sentry = config.mcpServers[RUNTIME_NAMES.sentry];
  assertExactKeys(sentry, ["serverUrl", "disabledTools", "disabled"], ["serverUrl", "disabledTools", "disabled"], "canonical Sentry MCP");
  if (sentry.serverUrl !== "https://mcp.sentry.dev/mcp?skills=inspect") {
    fail("canonical Sentry MCP must use its inspect-only endpoint");
  }
  assertArrayIncludes(
    sentry.disabledTools,
    ["update_issue", "analyze_issue_with_seer", "execute_sentry_tool"],
    "canonical Sentry MCP disabledTools",
  );
}

function renderConfig(canonical, userConfig, legacyPlaywrightExtras) {
  const rendered = JSON.parse(JSON.stringify(canonical));
  for (const name of SERVER_NAMES) {
    if (!userConfig.mcp.servers[name].enabled) {
      delete rendered.mcpServers[RUNTIME_NAMES[name]];
    }
  }

  const playwrightSettings = userConfig.mcp.servers.playwright;
  if (playwrightSettings.enabled) {
    const args = rendered.mcpServers[RUNTIME_NAMES.playwright].args;
    const allowlistIndex = args.indexOf("--allowed-origins");
    if (legacyPlaywrightExtras !== null) {
      args[allowlistIndex + 1] = `${args[allowlistIndex + 1]};${legacyPlaywrightExtras.join(";")}`;
    } else if (playwrightSettings.mode === "unrestricted") {
      args.splice(allowlistIndex, 2);
    } else if (playwrightSettings.mode === "allowlist") {
      args[allowlistIndex + 1] = playwrightSettings.allowedOrigins.join(";");
    }
  }
  return rendered;
}

function atomicWriteJson(outputPath, value) {
  if (fs.existsSync(outputPath)) {
    fail(`--output path already exists: ${outputPath}`);
  }
  const directory = path.dirname(outputPath);
  const temporaryPath = path.join(
    directory,
    `.${path.basename(outputPath)}.${process.pid}.${Date.now()}.tmp`,
  );
  try {
    fs.writeFileSync(temporaryPath, `${JSON.stringify(value, null, 2)}\n`, {
      encoding: "utf8",
      flag: "wx",
      mode: 0o600,
    });
    // A same-directory hard link atomically publishes the complete file and,
    // unlike rename on POSIX, cannot replace a destination created by a race.
    // It also avoids Windows rename-over-existing behavior because output is
    // contractually required to be absent.
    fs.linkSync(temporaryPath, outputPath);
    fs.unlinkSync(temporaryPath);
  } catch (error) {
    try {
      fs.unlinkSync(temporaryPath);
    } catch (cleanupError) {
      if (cleanupError.code !== "ENOENT") {
        error.message += `; temporary-file cleanup failed: ${cleanupError.message}`;
      }
    }
    fail(`could not atomically write rendered MCP configuration to ${outputPath}: ${error.message}`);
  }
}

function printSummary(userConfig, legacyPlaywrightExtras) {
  const enabledServers = SERVER_NAMES.filter((name) => userConfig.mcp.servers[name].enabled);
  process.stdout.write(`mcp.enabled=${enabledServers.length > 0}\n`);
  process.stdout.write(`mcp.servers=${enabledServers.join(",")}\n`);
  for (const name of SERVER_NAMES) {
    process.stdout.write(`${name}.enabled=${userConfig.mcp.servers[name].enabled}\n`);
  }
  const playwright = userConfig.mcp.servers.playwright;
  const effectiveMode = !playwright.enabled
    ? "disabled"
    : legacyPlaywrightExtras !== null
      ? "loopback-plus-allowlist"
      : playwright.mode;
  process.stdout.write(`playwright.mode=${effectiveMode}\n`);
  const allowedOriginCount = !playwright.enabled || playwright.mode === "unrestricted"
    ? 0
    : legacyPlaywrightExtras !== null
      ? 4 + legacyPlaywrightExtras.length
      : playwright.mode === "loopback"
      ? 4
      : playwright.allowedOrigins.length;
  process.stdout.write(
    `playwright.allowedOriginCount=${allowedOriginCount}\n`,
  );
}

function parseArguments(argv) {
  const options = { "--disable-server": [] };
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!VALUE_OPTIONS.has(argument)) {
      fail(`unknown option ${JSON.stringify(argument)}`);
    }
    if (argument !== "--disable-server" && Object.prototype.hasOwnProperty.call(options, argument)) {
      fail(`option ${argument} may be specified only once`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      fail(`option ${argument} requires a value`);
    }
    if (argument === "--disable-server") {
      if (!SERVER_NAMES.includes(value)) {
        fail(`--disable-server must name one of: ${SERVER_NAMES.join(", ")}`);
      }
      if (options[argument].includes(value)) {
        fail(`--disable-server may name ${value} only once`);
      }
      options[argument].push(value);
    } else {
      options[argument] = value;
    }
    index += 1;
  }
  for (const required of ["--input", "--output"]) {
    if (!options[required]) {
      fail(`missing required option ${required}`);
    }
  }
  if (path.resolve(options["--input"]) === path.resolve(options["--output"])) {
    fail("--output must not overwrite the canonical --input file");
  }
  if (fs.existsSync(options["--output"])) {
    fail(`--output path already exists: ${options["--output"]}`);
  }
  return options;
}

function applyOverrides(config, options) {
  const effective = JSON.parse(JSON.stringify(config));
  for (const name of options["--disable-server"]) {
    effective.mcp.servers[name].enabled = false;
  }

  const modeOverride = options["--playwright-mode"];
  const originsOverride = options["--playwright-origins"];
  const extraOriginsOverride = options["--playwright-extra-origins"];
  if (extraOriginsOverride && (modeOverride || originsOverride)) {
    fail("--playwright-extra-origins cannot be combined with --playwright-mode or --playwright-origins");
  }
  if (modeOverride && !["loopback", "allowlist", "unrestricted"].includes(modeOverride)) {
    fail("--playwright-mode must be loopback, allowlist, or unrestricted");
  }
  if (!effective.mcp.servers.playwright.enabled && (modeOverride || originsOverride || extraOriginsOverride)) {
    fail("Playwright overrides cannot be combined with a disabled Playwright server");
  }
  if (modeOverride) {
    effective.mcp.servers.playwright.mode = modeOverride;
    if (modeOverride !== "allowlist") {
      effective.mcp.servers.playwright.allowedOrigins = [];
    }
  }
  if (originsOverride) {
    if (effective.mcp.servers.playwright.mode !== "allowlist") {
      fail("--playwright-origins is valid only when the effective Playwright mode is allowlist");
    }
    if (originsOverride.startsWith(";") || originsOverride.endsWith(";") || originsOverride.includes(";;")) {
      fail("--playwright-origins must not contain an empty origin");
    }
    effective.mcp.servers.playwright.allowedOrigins = originsOverride.split(";");
  }
  let legacyPlaywrightExtras = null;
  if (extraOriginsOverride) {
    if (extraOriginsOverride.startsWith(";") ||
        extraOriginsOverride.endsWith(";") ||
        extraOriginsOverride.includes(";;")) {
      fail("--playwright-extra-origins must not contain an empty origin");
    }
    legacyPlaywrightExtras = extraOriginsOverride.split(";");
    const seenOrigins = new Set();
    legacyPlaywrightExtras.forEach((origin, index) => {
      validateOrigin(origin, `--playwright-extra-origins[${index}]`);
      const identity = new URL(origin).origin.toLowerCase();
      if (seenOrigins.has(identity)) {
        fail("--playwright-extra-origins must not contain duplicates");
      }
      seenOrigins.add(identity);
    });
    effective.mcp.servers.playwright.mode = "loopback";
    effective.mcp.servers.playwright.allowedOrigins = [];
  }
  return {
    userConfig: validateUserConfig(effective),
    legacyPlaywrightExtras,
  };
}

function main() {
  const options = parseArguments(process.argv.slice(2));
  const canonical = parseJsonFile(options["--input"], "canonical MCP configuration");
  validateCanonicalConfig(canonical);
  const baseUserConfig = options["--config"]
    ? validateUserConfig(parseJsonFile(options["--config"], "harness configuration"))
    : defaultUserConfig();
  const { userConfig, legacyPlaywrightExtras } = applyOverrides(baseUserConfig, options);
  const rendered = renderConfig(canonical, userConfig, legacyPlaywrightExtras);
  atomicWriteJson(options["--output"], rendered);
  printSummary(userConfig, legacyPlaywrightExtras);
}

try {
  main();
} catch (error) {
  process.stderr.write(`Error: ${error.message}\n`);
  process.exitCode = 2;
}
