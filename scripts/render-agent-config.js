#!/usr/bin/env node

"use strict";

const fs = require("node:fs");
const path = require("node:path");

const AGENT_NAMES = [
  "harness-researcher",
  "harness-implementer",
  "harness-reviewer",
  "harness-verifier",
  "harness-documenter",
  "harness-security-auditor",
  "harness-db-architect",
];

const MODEL_NAME_PATTERN = /^[A-Za-z0-9_.:/-]+$/;
const DANGEROUS_KEYS = new Set(["__proto__", "prototype", "constructor"]);
const VALUE_OPTIONS = new Set(["--agents-dir", "--config"]);

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

function validateConfig(config) {
  assertExactKeys(config, ["$schema", "version", "mcp", "agents"], [], "configuration");
  if (Object.prototype.hasOwnProperty.call(config, "$schema")) {
    if (typeof config.$schema !== "string" || config.$schema.trim() === "") {
      fail("configuration.$schema must be a non-empty string");
    }
  }
  if (Object.prototype.hasOwnProperty.call(config, "version")) {
    if (config.version !== 1) {
      fail("configuration.version must be exactly 1");
    }
  }
  if (Object.prototype.hasOwnProperty.call(config, "mcp")) {
    assertRecord(config.mcp, "configuration.mcp");
  }
  if (Object.prototype.hasOwnProperty.call(config, "agents")) {
    assertRecord(config.agents, "configuration.agents");
    assertExactKeys(config.agents, ["defaultModel", "models"], [], "configuration.agents");
    if (Object.prototype.hasOwnProperty.call(config.agents, "defaultModel")) {
      if (typeof config.agents.defaultModel !== "string" || config.agents.defaultModel.trim() === "") {
        fail("configuration.agents.defaultModel must be a non-empty string");
      }
      if (!MODEL_NAME_PATTERN.test(config.agents.defaultModel)) {
        fail("configuration.agents.defaultModel contains invalid model name (only letters, digits, and _ . : / - are allowed)");
      }
    }
    if (Object.prototype.hasOwnProperty.call(config.agents, "models")) {
      assertRecord(config.agents.models, "configuration.agents.models");
      assertExactKeys(config.agents.models, AGENT_NAMES, [], "configuration.agents.models");
      for (const [agentName, model] of Object.entries(config.agents.models)) {
        if (typeof model !== "string" || model.trim() === "") {
          fail(`configuration.agents.models.${agentName} must be a non-empty string`);
        }
        if (!MODEL_NAME_PATTERN.test(model)) {
          fail(`configuration.agents.models.${agentName} contains invalid model name (only letters, digits, and _ . : / - are allowed)`);
        }
      }
    }
  }
  return config;
}

function parseArguments(argv) {
  const options = {};
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (!VALUE_OPTIONS.has(argument)) {
      fail(`unknown option ${JSON.stringify(argument)}`);
    }
    if (Object.prototype.hasOwnProperty.call(options, argument)) {
      fail(`option ${argument} may be specified only once`);
    }
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) {
      fail(`option ${argument} requires a value`);
    }
    options[argument] = value;
    index += 1;
  }
  if (!options["--agents-dir"]) {
    fail("missing required option --agents-dir");
  }
  return options;
}

function resolveTargetModel(config, agentName) {
  if (config && config.agents) {
    if (
      config.agents.models &&
      Object.prototype.hasOwnProperty.call(config.agents.models, agentName)
    ) {
      return config.agents.models[agentName].trim();
    }
    if (
      config.agents.defaultModel &&
      typeof config.agents.defaultModel === "string" &&
      config.agents.defaultModel.trim() !== ""
    ) {
      return config.agents.defaultModel.trim();
    }
  }
  return null;
}

function renderAgentFile(filePath, agentName, targetModel) {
  let raw;
  try {
    raw = fs.readFileSync(filePath, "utf8");
  } catch (error) {
    fail(`could not read agent file at ${filePath}: ${error.message}`);
  }

  const hasBom = raw.charCodeAt(0) === 0xfeff;
  const contents = hasBom ? raw.slice(1) : raw;

  // Frontmatter Boundary Isolation:
  // Match opening --- and closing ---, isolating frontmatter between them.
  const match = contents.match(/^---(\r?\n)([\s\S]*?\r?\n)---(\r?\n?)([\s\S]*)$/);
  if (!match) {
    fail(`agent file ${filePath} does not have valid frontmatter enclosed by '---'`);
  }

  const openNewline = match[1];
  const frontmatter = match[2];
  const closeNewline = match[3];
  const body = match[4];

  // Match count assertion: exactly 1 model line in frontmatter
  const matches = frontmatter.match(/^model:[ \t]*\S+.*$/gm);
  const matchCount = matches ? matches.length : 0;
  if (matchCount === 0) {
    fail(`agent file ${filePath} is missing required 'model:' field in frontmatter`);
  }
  if (matchCount > 1) {
    fail(`agent file ${filePath} contains multiple (${matchCount}) 'model:' declarations in frontmatter`);
  }

  const updatedFrontmatter = targetModel !== null
    ? frontmatter.replace(/^model:[ \t]*\S+.*$/m, () => `model: ${targetModel}`)
    : frontmatter;

  const reconstructed =
    (hasBom ? "\ufeff" : "") +
    "---" +
    openNewline +
    updatedFrontmatter +
    "---" +
    closeNewline +
    body;

  try {
    fs.writeFileSync(filePath, reconstructed, "utf8");
  } catch (error) {
    fail(`could not write updated agent file at ${filePath}: ${error.message}`);
  }

  // Syntax and boundary integrity check after write
  const written = fs.readFileSync(filePath, "utf8");
  const writtenClean = written.charCodeAt(0) === 0xfeff ? written.slice(1) : written;
  const verifyMatch = writtenClean.match(/^---(\r?\n)([\s\S]*?\r?\n)---(\r?\n?)([\s\S]*)$/);
  if (!verifyMatch) {
    fail(`agent file ${filePath} failed syntax integrity check after writing`);
  }
  const verifyModelMatches = verifyMatch[2].match(/^model:[ \t]*\S+.*$/gm);
  if (!verifyModelMatches || verifyModelMatches.length !== 1) {
    fail(`agent file ${filePath} failed model line integrity check after writing`);
  }

  const effectiveModel = targetModel !== null
    ? targetModel
    : verifyModelMatches[0].replace(/^model:[ \t]*/, "").trim();

  return effectiveModel;
}

function renderAgents(agentsDir, config) {
  if (!fs.existsSync(agentsDir)) {
    fail(`agents directory does not exist: ${agentsDir}`);
  }
  let stat;
  try {
    stat = fs.statSync(agentsDir);
  } catch (error) {
    fail(`could not inspect agents directory at ${agentsDir}: ${error.message}`);
  }
  if (!stat.isDirectory()) {
    fail(`agents-dir is not a directory: ${agentsDir}`);
  }

  // Verify all 7 required agent files exist
  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    if (!fs.existsSync(filePath)) {
      fail(`agent file not found: ${filePath}`);
    }
  }

  const results = {};
  for (const agentName of AGENT_NAMES) {
    const filePath = path.join(agentsDir, `${agentName}.md`);
    const targetModel = resolveTargetModel(config, agentName);
    const effectiveModel = renderAgentFile(filePath, agentName, targetModel);
    results[agentName] = effectiveModel;
    process.stdout.write(`agent.${agentName}=${effectiveModel}\n`);
  }
  return results;
}

function main() {
  const options = parseArguments(process.argv.slice(2));
  const config = options["--config"]
    ? validateConfig(parseJsonFile(options["--config"], "harness configuration"))
    : null;
  renderAgents(options["--agents-dir"], config);
}

try {
  main();
} catch (error) {
  process.stderr.write(`Error: ${error.message}\n`);
  process.exitCode = 2;
}
