#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { afterEach, test } = require("node:test");

const ROOT = path.resolve(__dirname, "..");
const RENDERER = path.join(ROOT, "scripts", "render-mcp-config.js");
const CANONICAL = path.join(ROOT, "plugin", "codex-claude-harness", "mcp_config.json");
const temporaryDirectories = [];

afterEach(() => {
  while (temporaryDirectories.length > 0) {
    fs.rmSync(temporaryDirectories.pop(), { recursive: true, force: true });
  }
});

function makeDirectory() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "harness-mcp-render-"));
  temporaryDirectories.push(directory);
  return directory;
}

function baselineConfig() {
  return JSON.parse(fs.readFileSync(path.join(ROOT, "harness.config.example.json"), "utf8"));
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

test("published schema rejects out-of-range ports and documents normalized uniqueness", () => {
  const schema = JSON.parse(
    fs.readFileSync(path.join(ROOT, "schemas", "harness.config.schema.json"), "utf8"),
  );
  const origins = schema.$defs.playwright.properties.allowedOrigins;
  const originPattern = new RegExp(origins.items.pattern);
  assert.equal(originPattern.test("https://example.com:1"), true);
  assert.equal(originPattern.test("https://example.com:65535"), true);
  assert.equal(originPattern.test("https://example.com:0"), false);
  assert.equal(originPattern.test("https://example.com:65536"), false);
  assert.match(origins.description, /normalization/);
});

function runRenderer({ canonical = CANONICAL, config, output, extraArguments = [] }) {
  const args = [RENDERER, "--input", canonical, "--output", output];
  if (config) {
    args.push("--config", config);
  }
  args.push(...extraArguments);
  return spawnSync(process.execPath, args, { encoding: "utf8" });
}

test("no user config preserves the canonical MCP configuration", () => {
  const directory = makeDirectory();
  const output = path.join(directory, "rendered.json");
  const canonicalBefore = fs.readFileSync(CANONICAL, "utf8");
  const result = runRenderer({ output });

  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, "utf8")), JSON.parse(canonicalBefore));
  assert.equal(fs.readFileSync(CANONICAL, "utf8"), canonicalBefore);
  assert.match(result.stdout, /^mcp\.enabled=true$/m);
  assert.match(result.stdout, /^mcp\.servers=context7,serena,playwright,github,sentry$/m);
  assert.match(result.stdout, /^playwright\.mode=loopback$/m);
  assert.match(result.stdout, /^playwright\.allowedOriginCount=4$/m);
});

test("disabled servers are omitted and an exact Playwright allowlist is rendered", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "harness config.json");
  const output = path.join(directory, "rendered config.json");
  const config = baselineConfig();
  config.mcp.servers.serena.enabled = false;
  config.mcp.servers.github.enabled = false;
  config.mcp.servers.playwright.mode = "allowlist";
  config.mcp.servers.playwright.allowedOrigins = [
    "https://preview.example.com",
    "https://staging.example.com:8443",
  ];
  writeJson(configPath, config);

  const result = runRenderer({ config: configPath, output });
  assert.equal(result.status, 0, result.stderr);
  const rendered = JSON.parse(fs.readFileSync(output, "utf8"));
  assert.deepEqual(Object.keys(rendered.mcpServers), [
    "harness-context7",
    "harness-playwright",
    "harness-sentry",
  ]);
  const args = rendered.mcpServers["harness-playwright"].args;
  assert.ok(args.includes("--isolated"));
  assert.ok(args.includes("--headless"));
  assert.equal(
    args[args.indexOf("--allowed-origins") + 1],
    "https://preview.example.com;https://staging.example.com:8443",
  );
  assert.match(result.stdout, /^mcp\.servers=context7,playwright,sentry$/m);
  assert.match(result.stdout, /^github\.enabled=false$/m);
  assert.match(result.stdout, /^playwright\.allowedOriginCount=2$/m);
  assert.doesNotMatch(result.stdout, /example\.com/);
});

test("unrestricted Playwright removes only the origin filter", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "config.json");
  const output = path.join(directory, "rendered.json");
  const config = baselineConfig();
  config.mcp.servers.playwright.mode = "unrestricted";
  writeJson(configPath, config);

  const result = runRenderer({ config: configPath, output });
  assert.equal(result.status, 0, result.stderr);
  const args = JSON.parse(fs.readFileSync(output, "utf8")).mcpServers["harness-playwright"].args;
  assert.ok(args.includes("--isolated"));
  assert.ok(args.includes("--headless"));
  assert.ok(!args.includes("--allowed-origins"));
  assert.match(result.stdout, /^playwright\.mode=unrestricted$/m);
});

test("all disabled servers render an empty inventory and a disabled summary", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "config.json");
  const output = path.join(directory, "rendered.json");
  const config = baselineConfig();
  for (const server of Object.values(config.mcp.servers)) {
    server.enabled = false;
  }
  writeJson(configPath, config);

  const result = runRenderer({ config: configPath, output });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, "utf8")), { mcpServers: {} });
  assert.match(result.stdout, /^mcp\.enabled=false$/m);
  assert.match(result.stdout, /^mcp\.servers=$/m);
  assert.match(result.stdout, /^playwright\.mode=disabled$/m);
});

test("installer overrides disable servers and replace Playwright settings", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "config.json");
  const output = path.join(directory, "rendered.json");
  const config = baselineConfig();
  config.mcp.servers.playwright.mode = "allowlist";
  config.mcp.servers.playwright.allowedOrigins = ["https://from-config.example.com"];
  writeJson(configPath, config);

  const result = runRenderer({
    config: configPath,
    output,
    extraArguments: [
      "--disable-server", "github",
      "--disable-server", "sentry",
      "--playwright-mode", "allowlist",
      "--playwright-origins", "https://cli.example.com;https://cli.example.com:8443",
    ],
  });
  assert.equal(result.status, 0, result.stderr);
  const rendered = JSON.parse(fs.readFileSync(output, "utf8"));
  assert.ok(!Object.hasOwn(rendered.mcpServers, "harness-github"));
  assert.ok(!Object.hasOwn(rendered.mcpServers, "harness-sentry"));
  const args = rendered.mcpServers["harness-playwright"].args;
  assert.equal(
    args[args.indexOf("--allowed-origins") + 1],
    "https://cli.example.com;https://cli.example.com:8443",
  );
  assert.match(result.stdout, /^mcp\.servers=context7,serena,playwright$/m);
  assert.match(result.stdout, /^playwright\.allowedOriginCount=2$/m);
  assert.doesNotMatch(result.stdout, /cli\.example/);
});

test("a mode override clears obsolete configured origins", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "config.json");
  const output = path.join(directory, "rendered.json");
  const config = baselineConfig();
  config.mcp.servers.playwright.mode = "allowlist";
  config.mcp.servers.playwright.allowedOrigins = ["https://from-config.example.com"];
  writeJson(configPath, config);

  const result = runRenderer({
    config: configPath,
    output,
    extraArguments: ["--playwright-mode", "unrestricted"],
  });
  assert.equal(result.status, 0, result.stderr);
  const args = JSON.parse(fs.readFileSync(output, "utf8")).mcpServers["harness-playwright"].args;
  assert.ok(!args.includes("--allowed-origins"));
  assert.match(result.stdout, /^playwright\.mode=unrestricted$/m);
  assert.match(result.stdout, /^playwright\.allowedOriginCount=0$/m);
});

test("legacy extra-origin override retains all canonical loopback origins", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "config.json");
  const output = path.join(directory, "rendered.json");
  const config = baselineConfig();
  config.mcp.servers.playwright.mode = "unrestricted";
  writeJson(configPath, config);

  const result = runRenderer({
    config: configPath,
    output,
    extraArguments: [
      "--playwright-extra-origins",
      "https://preview.example.com;https://staging.example.com:8443",
    ],
  });
  assert.equal(result.status, 0, result.stderr);
  const args = JSON.parse(fs.readFileSync(output, "utf8")).mcpServers["harness-playwright"].args;
  assert.equal(
    args[args.indexOf("--allowed-origins") + 1],
    [
      "http://localhost:*",
      "http://127.0.0.1:*",
      "https://localhost:*",
      "https://127.0.0.1:*",
      "https://preview.example.com",
      "https://staging.example.com:8443",
    ].join(";"),
  );
  assert.match(result.stdout, /^playwright\.mode=loopback-plus-allowlist$/m);
  assert.match(result.stdout, /^playwright\.allowedOriginCount=6$/m);
  assert.doesNotMatch(result.stdout, /example\.com/);
});

test("duplicate and conflicting installer overrides are rejected", () => {
  const cases = [
    ["duplicate disable", ["--disable-server", "github", "--disable-server", "github"]],
    ["unknown server", ["--disable-server", "custom"]],
    ["duplicate mode", ["--playwright-mode", "loopback", "--playwright-mode", "unrestricted"]],
    ["invalid mode", ["--playwright-mode", "remote"]],
    ["origins without allowlist", ["--playwright-origins", "https://example.com"]],
    ["unrestricted with origins", ["--playwright-mode", "unrestricted", "--playwright-origins", "https://example.com"]],
    ["disabled Playwright mode", ["--disable-server", "playwright", "--playwright-mode", "loopback"]],
    ["disabled Playwright extras", ["--disable-server", "playwright", "--playwright-extra-origins", "https://example.com"]],
    ["empty origin", ["--playwright-mode", "allowlist", "--playwright-origins", "https://one.example.com;;https://two.example.com"]],
    ["extra origins plus mode", ["--playwright-extra-origins", "https://example.com", "--playwright-mode", "loopback"]],
    ["extra origins plus exact origins", ["--playwright-extra-origins", "https://example.com", "--playwright-origins", "https://other.example.com"]],
    ["wildcard extra origin", ["--playwright-extra-origins", "https://*.example.com"]],
    ["duplicate extra origins", ["--playwright-extra-origins", "https://example.com;https://example.com:443"]],
  ];
  for (const [label, extraArguments] of cases) {
    const directory = makeDirectory();
    const output = path.join(directory, "rendered.json");
    const result = runRenderer({ output, extraArguments });
    assert.equal(result.status, 2, `${label}: ${result.stderr}`);
    assert.ok(!fs.existsSync(output), label);
  }
});

test("unknown, custom-command, secret, and prototype keys are rejected", () => {
  const mutations = [
    ["unknown top-level key", (config) => { config.extra = true; }],
    ["custom server", (config) => { config.mcp.servers.custom = { enabled: true }; }],
    ["custom command", (config) => { config.mcp.servers.github.command = "npx"; }],
    ["literal secret", (config) => { config.mcp.servers.sentry.token = "secret"; }],
    ["constructor key", (config) => { config.mcp.servers.context7.constructor = {}; }],
  ];

  for (const [label, mutate] of mutations) {
    const directory = makeDirectory();
    const configPath = path.join(directory, "config.json");
    const output = path.join(directory, "rendered.json");
    const config = baselineConfig();
    mutate(config);
    writeJson(configPath, config);
    const result = runRenderer({ config: configPath, output });
    assert.equal(result.status, 2, `${label}: ${result.stderr}`);
    assert.ok(!fs.existsSync(output), label);
  }

  const directory = makeDirectory();
  const configPath = path.join(directory, "prototype.json");
  const output = path.join(directory, "rendered.json");
  fs.writeFileSync(
    configPath,
    '{"version":1,"mcp":{"servers":{"context7":{"enabled":true,"__proto__":{}},"serena":{"enabled":true},"playwright":{"enabled":true,"mode":"loopback","allowedOrigins":[]},"github":{"enabled":true},"sentry":{"enabled":true}}}}',
    "utf8",
  );
  const result = runRenderer({ config: configPath, output });
  assert.equal(result.status, 2, result.stderr);
  assert.match(result.stderr, /forbidden key/);
});

test("invalid versions, types, Playwright modes, and origins fail closed", () => {
  const mutations = [
    (config) => { config.version = 2; },
    (config) => { config.mcp.servers.github.enabled = "true"; },
    (config) => { config.mcp.servers.playwright.mode = "remote"; },
    (config) => { config.mcp.servers.playwright.allowedOrigins = ["https://example.com"]; },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = [];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://*.example.com"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://user@example.com"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://example.com/path"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://example.com?query=yes"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://example.com:0"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://example.com:65536"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://EXAMPLE.com", "https://example.COM"];
    },
    (config) => {
      config.mcp.servers.playwright.mode = "allowlist";
      config.mcp.servers.playwright.allowedOrigins = ["https://example.com", "https://example.com:443"];
    },
  ];

  for (const mutate of mutations) {
    const directory = makeDirectory();
    const configPath = path.join(directory, "config.json");
    const output = path.join(directory, "rendered.json");
    const config = baselineConfig();
    mutate(config);
    writeJson(configPath, config);
    const result = runRenderer({ config: configPath, output });
    assert.equal(result.status, 2, result.stderr);
    assert.ok(!fs.existsSync(output));
  }
});

test("UTF-8 BOM and CRLF config files are accepted on Windows-compatible paths", () => {
  const directory = makeDirectory();
  const configPath = path.join(directory, "harness config.json");
  const output = path.join(directory, "rendered config.json");
  const serialized = JSON.stringify(baselineConfig(), null, 2).replace(/\n/g, "\r\n");
  fs.writeFileSync(configPath, `\ufeff${serialized}\r\n`, "utf8");

  const result = runRenderer({ config: configPath, output });
  assert.equal(result.status, 0, result.stderr);
  assert.deepEqual(JSON.parse(fs.readFileSync(output, "utf8")), JSON.parse(fs.readFileSync(CANONICAL, "utf8")));
});

test("a damaged canonical safety invariant is rejected without creating output", () => {
  const directory = makeDirectory();
  const canonicalPath = path.join(directory, "canonical.json");
  const output = path.join(directory, "rendered.json");
  const canonical = JSON.parse(fs.readFileSync(CANONICAL, "utf8"));
  canonical.mcpServers["harness-github"].args = ["stdio"];
  writeJson(canonicalPath, canonical);

  const result = runRenderer({ canonical: canonicalPath, output });
  assert.equal(result.status, 2, result.stderr);
  assert.ok(!fs.existsSync(output));
  assert.deepEqual(fs.readdirSync(directory), ["canonical.json"]);
});

test("an existing output is rejected and never replaced", () => {
  const directory = makeDirectory();
  const output = path.join(directory, "rendered.json");
  fs.writeFileSync(output, "sentinel\n", "utf8");

  const result = runRenderer({ output });
  assert.equal(result.status, 2, result.stderr);
  assert.match(result.stderr, /already exists/);
  assert.equal(fs.readFileSync(output, "utf8"), "sentinel\n");
});

test("the renderer requires explicit distinct paths and rejects unknown CLI options", () => {
  const directory = makeDirectory();
  const output = path.join(directory, "rendered.json");
  let result = spawnSync(process.execPath, [RENDERER, "--input", CANONICAL], { encoding: "utf8" });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /missing required option --output/);

  result = runRenderer({ output, extraArguments: ["--surprise", "value"] });
  assert.equal(result.status, 2);
  assert.ok(!fs.existsSync(output));

  result = spawnSync(
    process.execPath,
    [RENDERER, "--input", CANONICAL, "--output", CANONICAL],
    { encoding: "utf8" },
  );
  assert.equal(result.status, 2);
  assert.match(result.stderr, /must not overwrite/);
});
