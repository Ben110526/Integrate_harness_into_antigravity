#!/usr/bin/env node

"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { spawnSync } = require("node:child_process");
const { afterEach, test } = require("node:test");

const ROOT = path.resolve(__dirname, "..");
const RENDERER = path.join(ROOT, "scripts", "render-agent-config.js");
const CANONICAL_AGENTS_DIR = path.join(ROOT, "plugin", "codex-claude-harness", "agents");
const AGENT_NAMES = [
  "harness-researcher",
  "harness-implementer",
  "harness-reviewer",
  "harness-verifier",
  "harness-documenter",
  "harness-security-auditor",
  "harness-db-architect",
];

const temporaryDirectories = [];

afterEach(() => {
  while (temporaryDirectories.length > 0) {
    fs.rmSync(temporaryDirectories.pop(), { recursive: true, force: true });
  }
});

function makeDirectory() {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "harness-agent-render-"));
  temporaryDirectories.push(directory);
  return directory;
}

function createFixtureAgents(directory) {
  const agentsDir = path.join(directory, "agents");
  fs.mkdirSync(agentsDir, { recursive: true });
  for (const agent of AGENT_NAMES) {
    const sourcePath = path.join(CANONICAL_AGENTS_DIR, `${agent}.md`);
    const targetPath = path.join(agentsDir, `${agent}.md`);
    fs.copyFileSync(sourcePath, targetPath);
  }
  return agentsDir;
}

function writeJson(filePath, value) {
  fs.writeFileSync(filePath, `${JSON.stringify(value, null, 2)}\n`, "utf8");
}

function runRenderer({ agentsDir, config, extraArguments = [] }) {
  const args = [RENDERER];
  if (agentsDir) {
    args.push("--agents-dir", agentsDir);
  }
  if (config) {
    args.push("--config", config);
  }
  args.push(...extraArguments);
  return spawnSync(process.execPath, args, { encoding: "utf8" });
}

function readFrontmatter(filePath) {
  const content = fs.readFileSync(filePath, "utf8");
  const match = content.match(/^---(\r?\n)([\s\S]*?\r?\n)---(\r?\n?)([\s\S]*)$/);
  assert.ok(match, `File ${filePath} must have valid frontmatter`);
  return {
    openNl: match[1],
    frontmatter: match[2],
    closeNl: match[3],
    body: match[4],
    raw: content,
  };
}

test("(1) renders specific models per subagent when configured in models map", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const configPath = path.join(directory, "harness.config.json");

  const customModels = {
    "harness-researcher": "gemini-3.7-flash-high",
    "harness-implementer": "gemini-3.8-flash-high",
    "harness-reviewer": "gemini-3.8-flash-high",
    "harness-verifier": "gemini-3.7-flash-high",
    "harness-documenter": "gemini-3.7-flash-medium",
    "harness-security-auditor": "gemini-3.8-flash-high",
    "harness-db-architect": "pro",
  };

  writeJson(configPath, {
    agents: {
      models: customModels,
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 0, result.stderr);

  for (const [agentName, expectedModel] of Object.entries(customModels)) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const { frontmatter } = readFrontmatter(filePath);
    const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
    assert.ok(matches);
    assert.equal(matches.length, 1);
    assert.equal(matches[0], `model: ${expectedModel}`);
    assert.match(result.stdout, new RegExp(`^agent\\.${agentName}=${expectedModel}$`, "m"));
  }
});

test("(2) renders fallback to defaultModel when subagent is not in models map", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const configPath = path.join(directory, "harness.config.json");

  writeJson(configPath, {
    agents: {
      defaultModel: "gemini-3.7-flash-high",
      models: {
        "harness-implementer": "gemini-3.8-flash-high",
        "harness-reviewer": "gemini-3.8-flash-high",
      },
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 0, result.stderr);

  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const { frontmatter } = readFrontmatter(filePath);
    const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
    assert.ok(matches);
    assert.equal(matches.length, 1);

    if (agentName === "harness-implementer" || agentName === "harness-reviewer") {
      assert.equal(matches[0], "model: gemini-3.8-flash-high");
    } else {
      assert.equal(matches[0], "model: gemini-3.7-flash-high");
    }
  }
});

test("(3) preserves model: inherit when --config is omitted or config has no agents block", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);

  // Subcase A: Omit --config
  let result = runRenderer({ agentsDir });
  assert.equal(result.status, 0, result.stderr);
  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const { frontmatter } = readFrontmatter(filePath);
    const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
    assert.ok(matches);
    assert.equal(matches.length, 1);
    assert.equal(matches[0], "model: inherit");
  }

  // Subcase B: Config without agents block
  const noAgentsConfig = path.join(directory, "no-agents.json");
  writeJson(noAgentsConfig, { version: 1, mcp: { servers: {} } });
  result = runRenderer({ agentsDir, config: noAgentsConfig });
  assert.equal(result.status, 0, result.stderr);
  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const { frontmatter } = readFrontmatter(filePath);
    const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
    assert.ok(matches);
    assert.equal(matches.length, 1);
    assert.equal(matches[0], "model: inherit");
  }

  // Subcase C: Config with empty agents object
  const emptyAgentsConfig = path.join(directory, "empty-agents.json");
  writeJson(emptyAgentsConfig, { agents: {} });
  result = runRenderer({ agentsDir, config: emptyAgentsConfig });
  assert.equal(result.status, 0, result.stderr);
  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const { frontmatter } = readFrontmatter(filePath);
    const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
    assert.ok(matches);
    assert.equal(matches.length, 1);
    assert.equal(matches[0], "model: inherit");
  }
});

test("(4) fails closed when an agent file is missing model: declaration", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const targetFile = path.join(agentsDir, "harness-verifier.md");

  // Remove the model line from harness-verifier.md
  const content = fs.readFileSync(targetFile, "utf8");
  const stripped = content.replace(/^model:[ \t]*\S+.*$/m, "");
  fs.writeFileSync(targetFile, stripped, "utf8");

  const result = runRenderer({ agentsDir });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /is missing required 'model:' field/);
});

test("(5) fails closed when an agent file contains duplicate model: lines in frontmatter", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const targetFile = path.join(agentsDir, "harness-verifier.md");

  // Duplicate the model line in frontmatter
  const content = fs.readFileSync(targetFile, "utf8");
  const duplicated = content.replace(
    /^model:[ \t]*\S+.*$/m,
    "model: inherit\nmodel: gemini-2.5-pro",
  );
  fs.writeFileSync(targetFile, duplicated, "utf8");

  const result = runRenderer({ agentsDir });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /contains multiple \(2\) 'model:' declarations/);
});

test("(6) protects body: markdown text with model: in body is 100% preserved and untouched", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const targetFile = path.join(agentsDir, "harness-implementer.md");

  // Append markdown body with false model: mentions and inner delimiters
  const injectedBody = `\n# Mission\n\nDiscussion about model: gemini-old and its behavior.\n---\nAnother boundary line.\nmodel: test-in-body\n`;
  const { frontmatter, openNl, closeNl } = readFrontmatter(targetFile);
  const newContent = "---" + openNl + frontmatter + "---" + closeNl + injectedBody;
  fs.writeFileSync(targetFile, newContent, "utf8");

  const configPath = path.join(directory, "config.json");
  writeJson(configPath, {
    agents: {
      models: {
        "harness-implementer": "gemini-3.8-flash-high",
      },
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 0, result.stderr);

  const updated = readFrontmatter(targetFile);
  const matches = updated.frontmatter.match(/^model:[ \t]*\S+.*$/gm);
  assert.ok(matches);
  assert.equal(matches.length, 1);
  assert.equal(matches[0], "model: gemini-3.8-flash-high");
  // Body must remain completely identical
  assert.equal(updated.body, injectedBody);
});

test("(7) protects all other frontmatter fields: commandExecutionPolicy, tools, name, etc.", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const targetFile = path.join(agentsDir, "harness-reviewer.md");

  const before = readFrontmatter(targetFile);
  const beforeNonModelLines = before.frontmatter
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("model:"));

  const configPath = path.join(directory, "config.json");
  writeJson(configPath, {
    agents: {
      models: {
        "harness-reviewer": "gemini-3.8-flash-high",
      },
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 0, result.stderr);

  const after = readFrontmatter(targetFile);
  const afterNonModelLines = after.frontmatter
    .split(/\r?\n/)
    .filter((line) => !line.startsWith("model:"));

  assert.deepEqual(afterNonModelLines, beforeNonModelLines);
  assert.match(after.frontmatter, /^commandExecutionPolicy: sandbox$/m);
  assert.match(after.frontmatter, /^name: harness-reviewer$/m);
  assert.match(after.frontmatter, /^model: gemini-3.8-flash-high$/m);
});

test("(8) fails closed on unknown agent name in config.agents.models", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const configPath = path.join(directory, "config.json");

  writeJson(configPath, {
    agents: {
      models: {
        "unknown-agent": "gemini-3.8-flash-high",
      },
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /unknown key "unknown-agent"/);
});

test("(9) fails closed on empty or invalid model values", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);

  const invalidDefaultModels = [
    ["empty string", ""],
    ["whitespace string", "   "],
    ["number", 123],
    ["boolean", true],
    ["array", ["gemini-3.8-flash-high"]],
    ["object", { model: "pro" }],
    ["null", null],
  ];

  for (const [label, badValue] of invalidDefaultModels) {
    const configPath = path.join(directory, `bad-default-${label.replace(/\s+/g, "-")}.json`);
    writeJson(configPath, {
      agents: {
        defaultModel: badValue,
      },
    });
    const result = runRenderer({ agentsDir, config: configPath });
    assert.equal(result.status, 2, `expected failure for defaultModel with ${label}`);
    assert.match(result.stderr, /configuration\.agents\.defaultModel must be a non-empty string/);
  }

  const invalidAgentModels = [
    ["empty string", ""],
    ["whitespace string", "   "],
    ["number", 42],
    ["boolean", false],
    ["null", null],
  ];

  for (const [label, badValue] of invalidAgentModels) {
    const configPath = path.join(directory, `bad-model-${label.replace(/\s+/g, "-")}.json`);
    writeJson(configPath, {
      agents: {
        models: {
          "harness-researcher": badValue,
        },
      },
    });
    const result = runRenderer({ agentsDir, config: configPath });
    assert.equal(result.status, 2, `expected failure for models.harness-researcher with ${label}`);
    assert.match(
      result.stderr,
      /configuration\.agents\.models\.harness-researcher must be a non-empty string/,
    );
  }
});

test("(10) rejects prototype pollution and forbidden keys (__proto__, prototype, constructor)", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);

  const dangerousPayloads = [
    '{"agents":{"__proto__":{"polluted":true},"defaultModel":"flash"}}',
    '{"agents":{"prototype":{"polluted":true},"defaultModel":"flash"}}',
    '{"agents":{"constructor":{"polluted":true},"defaultModel":"flash"}}',
    '{"__proto__":{"polluted":true},"agents":{"defaultModel":"flash"}}',
  ];

  for (let index = 0; index < dangerousPayloads.length; index += 1) {
    const configPath = path.join(directory, `proto-${index}.json`);
    fs.writeFileSync(configPath, dangerousPayloads[index], "utf8");
    const result = runRenderer({ agentsDir, config: configPath });
    assert.equal(result.status, 2, `expected failure for prototype payload ${index}`);
    assert.match(result.stderr, /forbidden key/);
  }
});

test("(11) operates cleanly on temporary fixture directories and validates required arguments", () => {
  const directory = makeDirectory();

  // Missing --agents-dir
  let result = spawnSync(process.execPath, [RENDERER], { encoding: "utf8" });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /missing required option --agents-dir/);

  // Non-existent directory
  result = runRenderer({ agentsDir: path.join(directory, "nonexistent") });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /agents directory does not exist/);

  // Directory missing required agent files
  const incompleteDir = path.join(directory, "incomplete-agents");
  fs.mkdirSync(incompleteDir);
  fs.writeFileSync(path.join(incompleteDir, "harness-researcher.md"), "---\nmodel: inherit\n---\n");
  result = runRenderer({ agentsDir: incompleteDir });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /agent file not found/);

  // Unknown option
  const agentsDir = createFixtureAgents(directory);
  result = runRenderer({ agentsDir, extraArguments: ["--unknown-flag"] });
  assert.equal(result.status, 2);
  assert.match(result.stderr, /unknown option "--unknown-flag"/);
});

test("(12) preserves CRLF line endings and UTF-8 BOM when present", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);
  const targetFile = path.join(agentsDir, "harness-documenter.md");

  // Rewrite harness-documenter.md with BOM and CRLF
  const original = fs.readFileSync(targetFile, "utf8");
  const crlfContent = "\ufeff" + original.replace(/\n/g, "\r\n");
  fs.writeFileSync(targetFile, crlfContent, "utf8");

  const configPath = path.join(directory, "config.json");
  writeJson(configPath, {
    agents: {
      models: {
        "harness-documenter": "gemini-3.7-flash-medium",
      },
    },
  });

  const result = runRenderer({ agentsDir, config: configPath });
  assert.equal(result.status, 0, result.stderr);

  const updatedRaw = fs.readFileSync(targetFile, "utf8");
  assert.equal(updatedRaw.charCodeAt(0), 0xfeff, "BOM must be preserved");
  assert.ok(updatedRaw.includes("\r\n"), "CRLF must be preserved");
  assert.match(updatedRaw, /^model: gemini-3.7-flash-medium\r?$/m);
});

test("(13) rejects model names containing newlines, whitespace, or YAML injection characters", () => {
  const directory = makeDirectory();
  const agentsDir = createFixtureAgents(directory);

  const injectionPayloads = [
    ["newline injection", "gemini-pro\ninjected: true"],
    ["crlf injection", "gemini-pro\r\ninjected: true"],
    ["inner space", "gemini 3.8 flash"],
    ["leading space", " gemini-3.8"],
    ["trailing space", "gemini-3.8 "],
    ["tab character", "gemini\t3.8"],
    ["yaml comment injection", "gemini#comment"],
    ["yaml colon-space injection", "gemini: true"],
    ["yaml array injection", "gemini [1, 2]"],
    ["yaml map injection", "gemini {key: val}"],
    ["quote character single", "gemini'quote"],
    ["quote character double", 'gemini"quote'],
    ["dollar character", "gemini$dollar"],
    ["semicolon character", "gemini;cmd"],
  ];

  // Test injection in defaultModel
  for (const [label, payload] of injectionPayloads) {
    const configPath = path.join(directory, `injection-default-${label.replace(/[^a-zA-Z0-9]/g, "-")}.json`);
    writeJson(configPath, {
      agents: {
        defaultModel: payload,
      },
    });
    const result = runRenderer({ agentsDir, config: configPath });
    assert.equal(result.status, 2, `expected failure for defaultModel with ${label}`);
    assert.match(
      result.stderr,
      /configuration\.agents\.defaultModel contains invalid model name \(only letters, digits, and _ \. : \/ - are allowed\)/,
    );
  }

  // Test injection in models map
  for (const [label, payload] of injectionPayloads) {
    const configPath = path.join(directory, `injection-models-${label.replace(/[^a-zA-Z0-9]/g, "-")}.json`);
    writeJson(configPath, {
      agents: {
        models: {
          "harness-researcher": payload,
        },
      },
    });
    const result = runRenderer({ agentsDir, config: configPath });
    assert.equal(result.status, 2, `expected failure for models.harness-researcher with ${label}`);
    assert.match(
      result.stderr,
      /configuration\.agents\.models\.harness-researcher contains invalid model name \(only letters, digits, and _ \. : \/ - are allowed\)/,
    );
  }

  // Test that valid model name characters (letters, digits, and _ . : / -) succeed
  const validModel = "google/gemini-2.5_flash.pro:v1";
  const validConfigPath = path.join(directory, "valid-model.json");
  writeJson(validConfigPath, {
    agents: {
      defaultModel: validModel,
    },
  });
  const validResult = runRenderer({ agentsDir, config: validConfigPath });
  assert.equal(validResult.status, 0, validResult.stderr);
});

