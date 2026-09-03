#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"

fail() {
  printf '[fail] %s\n' "$1" >&2
  exit 1
}

printf '[check] policy sources stay synchronized\n'
cmp -s global/GEMINI.md plugin/codex-claude-harness/rules/engineering-harness.md || \
  fail 'global and plugin policies differ'

printf '[check] shell syntax\n'
shell_files=(install.sh doctor.sh install.command evals/run-smoke.sh scripts/update-checksums.sh)
if [[ -d plugin/codex-claude-harness/scripts ]]; then
  while IFS= read -r script_path; do
    shell_files+=("${script_path}")
  done < <(find plugin/codex-claude-harness/scripts -type f -name '*.sh' -print | sort)
fi
bash -n "${shell_files[@]}"

printf '[check] eval, policy, and lifecycle fixture coverage\n'
python3 -m unittest -q tests/test_evals.py tests/test_policy.py tests/test_lifecycle_guard.py

printf '[check] plugin JSON and frontmatter inventory\n'
python3 - "${repo_root}" <<'PY'
import json
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
json_paths = [root / "plugin/codex-claude-harness/plugin.json"]
json_paths.extend(sorted((root / "plugin/codex-claude-harness").glob("*.json")))
profile_paths = sorted(root.glob("plugin/codex-claude-harness/skills/*/assets/*.json"))
json_paths.extend(profile_paths)
for path in dict.fromkeys(json_paths):
    with path.open(encoding="utf-8") as handle:
        json.load(handle)

hooks = json.loads((root / "plugin/codex-claude-harness/hooks.json").read_text(encoding="utf-8"))
if "SessionStart" in json.dumps(hooks):
    raise SystemExit("project context must use supported PreInvocation, not SessionStart")
if hooks.get("security-gate", {}).get("PreToolUse", [{}])[0].get("matcher") != (
    "write_to_file|replace_file_content|multi_replace_file_content|run_command"
):
    raise SystemExit("security gate must inspect every write and terminal tool")
if "PreInvocation" not in hooks.get("project-context", {}):
    raise SystemExit("bounded project context must run through PreInvocation")
if hooks.get("auto-format", {}).get("PostToolUse", [{}])[0].get("matcher") != (
    "write_to_file|replace_file_content|multi_replace_file_content"
):
    raise SystemExit("auto-format must run only after successful-capable write tools")
if not {"PostToolUse", "Stop"}.issubset(hooks.get("verification-gate", {})):
    raise SystemExit("verification gate registration is incomplete")
guard_source = (root / "plugin/codex-claude-harness/scripts/lifecycle_guard.py").read_text(encoding="utf-8")
launcher_source = (root / "plugin/codex-claude-harness/scripts/lifecycle_guard.cmd").read_text(encoding="utf-8")
verification_launcher = (root / "plugin/codex-claude-harness/scripts/verification_gate.cmd").read_text(encoding="utf-8")
for required in ("force_ask", "HARNESS_AUTO_FORMAT", "invocationNum", "MAX_CONTEXT_BYTES"):
    if required not in guard_source:
        raise SystemExit(f"lifecycle guard is missing bounded behavior: {required}")
for name, source in (("lifecycle", launcher_source), ("verification", verification_launcher)):
    if ".python-runtime" not in source:
        raise SystemExit(f"{name} launcher must use the installer-pinned Python runtime")
    if "command -v python" in source or "py -3" in source or "set /p python_runtime" in source:
        raise SystemExit(f"{name} launcher must never execute a PATH or codepage-decoded Python")
    if "System32\\WindowsPowerShell\\v1.0\\powershell.exe" not in source or "UTF8Encoding" not in source:
        raise SystemExit(f"{name} Windows launcher must read the UTF-8 marker through fixed PowerShell")
    if "$args[" in source or "$env:harness_python_marker" not in source:
        raise SystemExit(f"{name} Windows launcher must pass fixed paths without PowerShell -Command argument ambiguity")

vscode = json.loads((root / ".vscode/tasks.json").read_text(encoding="utf-8"))
tasks = {task.get("label"): task for task in vscode.get("tasks", [])}
expected_tasks = {
    "Harness: Antigravity (interactive)",
    "Harness: Doctor",
    "Harness: Deterministic source checks",
    "Harness: Interactive read-only review",
}
if set(tasks) != expected_tasks:
    raise SystemExit(f"unexpected VS Code task inventory: {sorted(tasks)}")
if any(task.get("runOptions", {}).get("runOn") != "default" for task in tasks.values()):
    raise SystemExit("VS Code harness tasks must remain manual")
review_args = tasks["Harness: Interactive read-only review"].get("args", [])
if not {"--prompt-interactive", "--sandbox", "--mode=plan", "high"}.issubset(review_args):
    raise SystemExit("interactive review task is missing High/sandbox/plan safeguards")
windows_check = json.dumps(tasks["Harness: Deterministic source checks"].get("windows", {}))
if "Get-Command py" not in windows_check or "py -3 -m unittest" not in windows_check or "Get-Command python" not in windows_check:
    raise SystemExit("Windows source-check task must support py -3 before python")
if "--dangerously-skip-permissions" in json.dumps(vscode):
    raise SystemExit("VS Code tasks must never bypass Antigravity permissions")

runtime_path = root / "plugin/codex-claude-harness/mcp_config.json"
runtime_servers = json.loads(runtime_path.read_text(encoding="utf-8")).get("mcpServers", {})
reference_servers = {}
for path in profile_paths:
    data = json.loads(path.read_text(encoding="utf-8"))
    servers = data.get("mcpServers", {})
    if len(servers) != 1:
        raise SystemExit(f"{path}: expected exactly one MCP server")
    server = next(iter(servers.values()))
    if server.get("disabled") is not True:
        raise SystemExit(f"{path}: shared MCP templates must default to disabled")
    name = next(iter(servers))
    if not name.startswith("harness-"):
        raise SystemExit(f"{path}: MCP server must use the harness- namespace")
    reference_servers[name] = server

expected_names = {
    "harness-context7",
    "harness-serena",
    "harness-playwright",
    "harness-github",
    "harness-sentry",
}
if set(reference_servers) != expected_names or set(runtime_servers) != expected_names:
    raise SystemExit("runtime and reference MCP inventories must contain the five namespaced servers")

for name, reference in reference_servers.items():
    expected = dict(reference)
    expected["disabled"] = False
    if runtime_servers[name] != expected:
        raise SystemExit(f"runtime MCP {name} differs from its disabled reference template")

for name, server in runtime_servers.items():
    transports = [key for key in ("command", "serverUrl") if key in server]
    if len(transports) != 1:
        raise SystemExit(f"runtime MCP {name} must define exactly one transport")
    if server.get("disabled") is not False:
        raise SystemExit(f"runtime MCP {name} must be pre-registered and enabled")
    if any(key in server for key in ("env", "headers", "oauth")):
        raise SystemExit(f"runtime MCP {name} must not embed credentials")

github = runtime_servers["harness-github"]
if github.get("command") != "codex-harness-github-mcp-server":
    raise SystemExit("GitHub MCP must use the checksum-verified harness binary")
github_args = set(github.get("args", []))
if not {"--read-only", "--lockdown-mode", "--oauth-scopes=repo,read:org"}.issubset(github_args):
    raise SystemExit("GitHub MCP must remain read-only, locked down, and limited to the documented OAuth scopes")

serena = runtime_servers["harness-serena"]
if serena.get("args", [])[:3] != ["--from", "serena-agent==1.7.0", "serena"]:
    raise SystemExit("Serena MCP must use the pinned uvx package")
serena_args = set(serena.get("args", []))
if not {
    "--enable-web-dashboard=false",
    "--enable-gui-log-window=false",
    "--open-web-dashboard=false",
}.issubset(serena_args):
    raise SystemExit("Serena MCP must start without opening dashboard UI")
if "activate_project" in set(serena.get("disabledTools", [])):
    raise SystemExit("Serena must keep activate_project available for Antigravity clients")

sentry = runtime_servers["harness-sentry"]
if sentry.get("serverUrl") != "https://mcp.sentry.dev/mcp?skills=inspect":
    raise SystemExit("Sentry MCP must request the upstream inspect-only capability")
if not {"update_issue", "analyze_issue_with_seer", "execute_sentry_tool"}.issubset(
    set(sentry.get("disabledTools", []))
):
    raise SystemExit("Sentry MCP must disable its direct and catalog mutation surfaces")

playwright = runtime_servers["harness-playwright"]
playwright_args = playwright.get("args", [])
allowed_origins_index = playwright_args.index("--allowed-origins") + 1
if playwright_args[allowed_origins_index] != (
    "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*"
):
    raise SystemExit("Playwright MCP must support any loopback dev-server port without remote origins")

install_sh = (root / "install.sh").read_text(encoding="utf-8")
install_ps1 = (root / "install.ps1").read_text(encoding="utf-8-sig")
if 'github_mcp_version="1.10.1"' not in install_sh or '$githubMcpVersion = "1.10.1"' not in install_ps1:
    raise SystemExit("installers must pin GitHub MCP v1.10.1")
for required_runtime in ("node", "npx", "uvx"):
    if required_runtime not in install_sh or required_runtime not in install_ps1:
        raise SystemExit(f"installers must preflight the {required_runtime} MCP runtime")
if "20.18.1" not in install_sh or "20.18.1" not in install_ps1:
    raise SystemExit("installers must enforce the pinned MCP Node.js floor")
if '"${target}" --version' not in install_sh or "& $target --version" not in install_ps1:
    raise SystemExit("installers must verify an existing GitHub MCP binary before the idempotent early return")
if "--skip-mcp" not in install_sh or "SkipMcp" not in install_ps1:
    raise SystemExit("installers must expose an explicit core-only MCP skip option")
if "--playwright-unrestricted" not in install_sh or "PlaywrightUnrestricted" not in install_ps1:
    raise SystemExit("installers must expose an explicit unrestricted Playwright opt-in")
if "HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS" not in install_sh or "HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS" not in install_ps1:
    raise SystemExit("installers must support a validated Playwright staging-origin allowlist")
if "core-only" not in install_sh or "core-only" not in install_ps1:
    raise SystemExit("installers must report graceful core-only MCP fallback")
for source in (install_sh, install_ps1):
    if ".python-runtime" not in source or "sys.executable" not in source or "(3, 8)" not in source:
        raise SystemExit("installers must resolve and persist an absolute Python 3.8+ runtime")
if '${package_root}"/*' not in install_sh or "/private/tmp/*" not in install_sh:
    raise SystemExit("POSIX installer must reject workspace/temp Python runtimes")
if "Test-HarnessTrustedPythonRuntime" not in install_ps1 or "GetTempPath" not in install_ps1:
    raise SystemExit("PowerShell installer must reject workspace/temp Python runtimes")
if '"python3", "python", "py"' not in install_ps1:
    raise SystemExit("PowerShell installer must support py-launcher-only Windows")
if "$onWindows = [Environment]::OSVersion.Platform" not in install_ps1 or "$IsWindows" in install_ps1:
    raise SystemExit("PowerShell installer must support Windows PowerShell 5.1")
if "System.Text.UTF8Encoding($false)" not in install_ps1:
    raise SystemExit("PowerShell installer must preserve non-ASCII runtime paths as UTF-8")
windows_fixture = (root / "tests/Test-Install.ps1").read_text(encoding="utf-8-sig")
if "(Get-Process -Id $PID).Path" not in windows_fixture or "& pwsh" in windows_fixture:
    raise SystemExit("PowerShell fixture must reuse its host so Windows PowerShell 5.1 is testable")

doctor = (root / "doctor.sh").read_text(encoding="utf-8")
for required in (
    "Python 3.8 or newer",
    ".python-runtime",
    "pinned lifecycle hook runtime",
    '"@playwright/mcp@0.0.79", "install-browser", "--dry-run", "chromium"',
    "INSTALLATION_COMPLETE",
    "timeout=20",
):
    if required not in doctor:
        raise SystemExit(f"doctor.sh is missing diagnostic guard: {required}")

checksum_updater = root / "scripts/update-checksums.sh"
if not checksum_updater.is_file() or not checksum_updater.stat().st_mode & 0o111:
    raise SystemExit("checksum updater must exist and be executable")
updater_source = checksum_updater.read_text(encoding="utf-8")
for required in (
    "github.com/github/github-mcp-server/releases/download",
    "--proto '=https'",
    "official manifest is missing required assets",
    "os.replace",
):
    if required not in updater_source:
        raise SystemExit(f"checksum updater is missing safety control: {required}")

unix_archives = {
    "github-mcp-server_Darwin_arm64.tar.gz": "ca530ba9abf04030104166cc37e1072087a30a173e921c0ed9064f98c73ca039",
    "github-mcp-server_Darwin_x86_64.tar.gz": "ea6e86baea583c6c5b55cce071c1c19253009a90f1e987788cb5eb228fcd9556",
    "github-mcp-server_Linux_arm64.tar.gz": "c51dc6cf192c35a328b9f71696d42c38a9a3ba3c2ffe010da836bed071d1ac8a",
    "github-mcp-server_Linux_x86_64.tar.gz": "c2629e850a344275cfc5a1590acdfd8c11476a44b688812d460163768e05572d",
}
windows_archives = {
    "github-mcp-server_Windows_arm64.zip": "7bc50942376f254192f0e28b3f76975a862f04e58bc7fa3a5b0d698d7a2d5d16",
    "github-mcp-server_Windows_i386.zip": "ae2c9191629122e33c503b53b8c3cc0b7bf56596d876e1f23476bd03f7039dd7",
    "github-mcp-server_Windows_x86_64.zip": "3b94ca079cf51a54698401b7affea7288a64b38118c243ae488dd8dd96f4ffb2",
}
for archive, checksum in unix_archives.items():
    if archive not in install_sh or checksum not in install_sh:
        raise SystemExit(f"install.sh is missing the official checksum for {archive}")
for archive, checksum in windows_archives.items():
    if archive not in install_ps1 or checksum not in install_ps1:
        raise SystemExit(f"install.ps1 is missing the official checksum for {archive}")

name_pattern = re.compile(r"^name:\s*(\S+)\s*$", re.MULTILINE)
expected_inventory = {
    "skill": {
        "harness-adr", "harness-benchmark", "harness-clarify", "harness-debug", "harness-implement",
        "harness-mcp-profile", "harness-migration", "harness-plan", "harness-review",
        "harness-ship", "harness-test",
    },
    "agent": {
        "harness-db-architect", "harness-documenter", "harness-implementer",
        "harness-researcher", "harness-reviewer", "harness-security-auditor",
        "harness-verifier",
    },
}
for kind, pattern in (
    ("skill", "plugin/codex-claude-harness/skills/*/SKILL.md"),
    ("agent", "plugin/codex-claude-harness/agents/*.md"),
):
    names = []
    for path in sorted(root.glob(pattern)):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise SystemExit(f"{path}: missing YAML frontmatter")
        match = name_pattern.search(text)
        if not match:
            raise SystemExit(f"{path}: missing frontmatter name")
        names.append(match.group(1))
    if len(names) != len(set(names)):
        raise SystemExit(f"duplicate {kind} names: {names}")
    if set(names) != expected_inventory[kind]:
        raise SystemExit(f"unexpected {kind} inventory: {names}")
PY

printf '[check] installer preserves user policy and is idempotent\n'
test_root="$(mktemp -d "${TMPDIR:-/tmp}/auto-harness-test.XXXXXX")"
cleanup() {
  rm -rf -- "${test_root}"
}
trap cleanup EXIT

fake_bin="${test_root}/bin"
fake_home="${test_root}/home"
fake_tmp="${test_root}/tmp"
real_node="$(command -v node || true)"
[[ -n "${real_node}" ]] || fail 'Node.js is required for installer fixture checks'
export HARNESS_TEST_REAL_NODE="${real_node}"
mkdir -p -- "${fake_bin}" "${fake_home}/.gemini" "${fake_tmp}"
printf '# Existing user rule\n\n- Keep this line.\n' > "${fake_home}/.gemini/GEMINI.md"

cat > "${fake_bin}/agy" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  plugin)
    if [[ "${EXPECT_CORE_ONLY:-0}" == "1" && -f "${3:-}/mcp_config.json" ]]; then
      printf 'core-only fixture received an enabled mcp_config.json\n' >&2
      exit 9
    fi
    if [[ -n "${EXPECT_PLAYWRIGHT_ORIGIN:-}" ]]; then
      python3 - "${3:-}" "${EXPECT_PLAYWRIGHT_ORIGIN}" <<'PY'
import json
import pathlib
import sys

config = json.loads((pathlib.Path(sys.argv[1]) / "mcp_config.json").read_text(encoding="utf-8"))
args = config["mcpServers"]["harness-playwright"]["args"]
origins = args[args.index("--allowed-origins") + 1].split(";")
required = {
    "http://localhost:*",
    "http://127.0.0.1:*",
    "https://localhost:*",
    "https://127.0.0.1:*",
    sys.argv[2],
}
if not required.issubset(origins):
    raise SystemExit(f"staged Playwright origins are incomplete: {origins}")
PY
    fi
    if [[ "${EXPECT_PLAYWRIGHT_UNRESTRICTED:-0}" == "1" ]]; then
      python3 - "${3:-}" <<'PY'
import json
import pathlib
import sys

config = json.loads((pathlib.Path(sys.argv[1]) / "mcp_config.json").read_text(encoding="utf-8"))
args = config["mcpServers"]["harness-playwright"]["args"]
if "--allowed-origins" in args:
    raise SystemExit(f"unrestricted Playwright config retained its allowlist: {args}")
if any("localhost" in argument or "127.0.0.1" in argument for argument in args):
    raise SystemExit(f"unrestricted Playwright config retained an allowlist value: {args}")
for required in ("--isolated", "--headless"):
    if required not in args:
        raise SystemExit(f"unrestricted Playwright config lost {required}: {args}")
PY
    fi
    if [[ "${EXPECT_PLAYWRIGHT_LOOPBACK_ONLY:-0}" == "1" ]]; then
      python3 - "${3:-}" <<'PY'
import json
import pathlib
import sys

config = json.loads((pathlib.Path(sys.argv[1]) / "mcp_config.json").read_text(encoding="utf-8"))
args = config["mcpServers"]["harness-playwright"]["args"]
if args.count("--allowed-origins") != 1:
    raise SystemExit(f"default Playwright config has an invalid allowlist pair: {args}")
origins = args[args.index("--allowed-origins") + 1]
expected = "http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*"
if origins != expected:
    raise SystemExit(f"default Playwright origins were not restored: {origins}")
PY
    fi
    exit 0
    ;;
  *)
    printf 'fake agy only supports plugin commands in installer tests\n' >&2
    exit 2
    ;;
esac
SH
chmod +x "${fake_bin}/agy"

installed_plugin="${fake_home}/.gemini/config/plugins/codex-claude-harness"
mkdir -p -- "${installed_plugin}"
printf '{"mcpServers":{"stale":{}}}\n' > "${installed_plugin}/mcp_config.json"

for _ in 1 2; do
  HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
    HARNESS_SKIP_MCP_BOOTSTRAP=1 \
    EXPECT_CORE_ONLY=1 \
    ./install.sh > "${test_root}/install.log"
done

policy_target="${fake_home}/.gemini/GEMINI.md"
grep -Fq -- '- Keep this line.' "${policy_target}" || fail 'installer removed existing user policy'
[[ "$(grep -Fc '<!-- auto-harness:start -->' "${policy_target}")" == "1" ]] || \
  fail 'installer duplicated the managed policy start marker'
[[ "$(grep -Fc '<!-- auto-harness:end -->' "${policy_target}")" == "1" ]] || \
  fail 'installer duplicated the managed policy end marker'
grep -Fq '# Automatic engineering harness' "${policy_target}" || \
  fail 'installer did not add the managed policy'
[[ ! -e "${installed_plugin}/mcp_config.json" ]] || \
  fail 'core-only installer left a stale enabled MCP config in the installed plugin'
runtime_marker="${installed_plugin}/scripts/.python-runtime"
[[ -f "${runtime_marker}" ]] || fail 'installer did not persist the pinned hook runtime marker'
IFS= read -r installed_python < "${runtime_marker}"
[[ "${installed_python}" == /* && -x "${installed_python}" ]] || \
  fail 'installer persisted an invalid hook runtime path'
[[ "$(wc -l < "${runtime_marker}" | tr -d ' ')" == "1" ]] || \
  fail 'installer runtime marker is not idempotent'
if [[ "$(uname -s)" == "Darwin" ]]; then
  runtime_marker_mode="$(stat -f '%Lp' "${runtime_marker}")"
else
  runtime_marker_mode="$(stat -c '%a' "${runtime_marker}")"
fi
[[ "${runtime_marker_mode}" == "600" ]] || fail 'installer runtime marker must be mode 0600'

old_node_bin="${test_root}/old-node-bin"
mkdir -p -- "${old_node_bin}"
cat > "${old_node_bin}/node" <<'SH'
#!/usr/bin/env bash
printf 'v19.0.0\n'
SH
chmod +x "${old_node_bin}/node"
printf '{"mcpServers":{"stale":{}}}\n' > "${installed_plugin}/mcp_config.json"
HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${old_node_bin}:${fake_bin}:${PATH}" \
  EXPECT_CORE_ONLY=1 \
  ./install.sh > "${test_root}/install-graceful.log" 2>&1
grep -Fq 'Continuing with the core harness only' "${test_root}/install-graceful.log" || \
  fail 'recoverable MCP bootstrap failure did not report core-only fallback'
[[ ! -e "${installed_plugin}/mcp_config.json" ]] || \
  fail 'graceful fallback left a stale enabled MCP config in the installed plugin'

cat > "${fake_bin}/codex-harness-github-mcp-server" <<'SH'
#!/usr/bin/env bash
printf 'Version: 1.10.1\n'
SH
cat > "${fake_bin}/node" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
if [[ "${1:-}" == "--version" ]]; then
  printf 'v20.18.1\n'
  exit 0
fi
if [[ "${1:-}" == */scripts/configure-playwright-mcp.js ]]; then
  exec "${HARNESS_TEST_REAL_NODE:?}" "$@"
fi
exit 2
SH
for runtime in npx uvx; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "${fake_bin}/${runtime}"
done
chmod +x "${fake_bin}/codex-harness-github-mcp-server"
chmod +x "${fake_bin}/node" "${fake_bin}/npx" "${fake_bin}/uvx"
printf '1.10.1\n' > "${fake_bin}/codex-harness-github-mcp-server.version"

HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com:8443' \
  EXPECT_PLAYWRIGHT_ORIGIN='https://preview.example.com:8443' \
  ./install.sh > "${test_root}/install-custom-origin.log"

HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  EXPECT_PLAYWRIGHT_UNRESTRICTED=1 \
  ./install.sh --playwright-unrestricted > "${test_root}/install-unrestricted.log"

HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  EXPECT_PLAYWRIGHT_LOOPBACK_ONLY=1 \
  ./install.sh > "${test_root}/install-loopback-restored.log"

set +e
HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://preview.example.com' \
  ./install.sh --playwright-unrestricted > "${test_root}/install-conflicting-origin.log" 2>&1
conflicting_origin_status="$?"
HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  ./install.sh --skip-mcp --playwright-unrestricted > "${test_root}/install-conflicting-mode.log" 2>&1
conflicting_mode_status="$?"
set -e
[[ "${conflicting_origin_status}" == "2" ]] || fail 'installer did not reject conflicting Playwright origin modes'
[[ "${conflicting_mode_status}" == "2" ]] || fail 'installer did not reject skip-MCP with unrestricted Playwright'
grep -Fq 'cannot be combined with HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS' "${test_root}/install-conflicting-origin.log" || \
  fail 'installer did not explain the Playwright origin-mode conflict'
grep -Fq 'cannot be combined with --playwright-unrestricted' "${test_root}/install-conflicting-mode.log" || \
  fail 'installer did not explain the skip-MCP conflict'

if HOME="${fake_home}" TMPDIR="${fake_tmp}" PATH="${fake_bin}:${PATH}" \
  HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS='https://*.example.com' \
  ./install.sh > "${test_root}/install-invalid-origin.log" 2>&1; then
  fail 'installer accepted a wildcard Playwright origin'
fi
grep -Fq 'without paths, credentials, or wildcards' "${test_root}/install-invalid-origin.log" || \
  fail 'installer did not explain the rejected Playwright origin'

shell_home="${test_root}/shell-home"
shell_bin="${test_root}/shell-bin"
mkdir -p -- "${shell_home}/.local/bin" "${shell_home}/.gemini" "${shell_bin}"
cat > "${shell_home}/.local/bin/agy" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "${1:-}" == plugin ]]
SH
chmod +x "${shell_home}/.local/bin/agy"
cat > "${shell_bin}/curl" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
output=""
while (( $# > 0 )); do
  if [[ "$1" == "-o" ]]; then
    output="$2"
    shift 2
  else
    shift
  fi
done
printf '#!/usr/bin/env bash\nexit 0\n' > "${output:?missing curl output path}"
SH
chmod +x "${shell_bin}/curl"
for optional_shell in fish nu; do
  printf '#!/usr/bin/env bash\nexit 0\n' > "${shell_bin}/${optional_shell}"
  chmod +x "${shell_bin}/${optional_shell}"
done

for _ in 1 2; do
  HOME="${shell_home}" XDG_CONFIG_HOME='' TMPDIR="${fake_tmp}" PATH="${shell_bin}:/usr/bin:/bin" \
    HARNESS_SKIP_MCP_BOOTSTRAP=1 EXPECT_CORE_ONLY=1 \
    ./install.sh > "${test_root}/install-shell-path.log"
done
fish_config="${shell_home}/.config/fish/config.fish"
if [[ "$(uname -s)" == "Darwin" ]]; then
  nu_config="${shell_home}/Library/Application Support/nushell/config.nu"
else
  nu_config="${shell_home}/.config/nushell/config.nu"
fi
if [[ ! -f "${fish_config}" || ! -f "${nu_config}" ]]; then
  sed -n '1,80p' "${test_root}/install-shell-path.log" >&2
  fail 'installer did not create Fish/Nushell PATH configuration'
fi
[[ "$(grep -Fc "fish_add_path -g \"\$HOME/.local/bin\"" "${fish_config}")" == "1" ]] || \
  fail 'Fish PATH setup is not idempotent'
[[ "$(grep -Fc "\$env.PATH = (\$env.PATH | prepend (\$nu.home-path | path join \".local\" \"bin\"))" "${nu_config}")" == "1" ]] || \
  fail 'Nushell PATH setup is not idempotent'

printf '[check] doctor verifies the pinned Playwright browser revision\n'
doctor_home="${test_root}/doctor-home"
doctor_bin="${test_root}/doctor-bin"
doctor_plugin="${doctor_home}/.gemini/config/plugins/codex-claude-harness"
browser_root="${test_root}/playwright-browsers"
mkdir -p -- "${doctor_bin}" "${doctor_plugin}" \
  "${browser_root}/chromium-1237" "${browser_root}/ffmpeg-1011" "${browser_root}/chromium_headless_shell-1237"
cp -R -- plugin/codex-claude-harness/. "${doctor_plugin}/"
mkdir -p -- "${doctor_home}/.gemini"
pinned_test_python="$(python3 -c 'import os, sys; print(os.path.realpath(sys.executable))')"
printf '%s\n' "${pinned_test_python}" > "${doctor_plugin}/scripts/.python-runtime"
chmod 0600 "${doctor_plugin}/scripts/.python-runtime"
printf '<!-- auto-harness:start -->\n<!-- auto-harness:end -->\n' > "${doctor_home}/.gemini/GEMINI.md"
for browser_component in chromium-1237 ffmpeg-1011 chromium_headless_shell-1237; do
  : > "${browser_root}/${browser_component}/INSTALLATION_COMPLETE"
done
cat > "${doctor_bin}/agy" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
case "${1:-}" in
  --version) printf 'agy fixture\n' ;;
  plugin)
    if [[ "${2:-}" == list ]]; then
      printf '[{"name": "codex-claude-harness"}]\n'
    fi
    ;;
  models) printf 'gemini-3.7-flash-high\n' ;;
  *) exit 2 ;;
esac
SH
cat > "${doctor_bin}/node" <<'SH'
#!/usr/bin/env bash
printf 'v20.18.1\n'
SH
cat > "${doctor_bin}/npx" <<'SH'
#!/usr/bin/env bash
set -euo pipefail
[[ "$*" == '-y @playwright/mcp@0.0.79 install-browser --dry-run chromium' ]]
printf 'Chromium\n  Install location:    %s/chromium-1237\n' "${PW_FIXTURE_ROOT:?}"
printf 'FFmpeg\n  Install location:    %s/ffmpeg-1011\n' "${PW_FIXTURE_ROOT}"
printf 'Headless Shell\n  Install location:    %s/chromium_headless_shell-1237\n' "${PW_FIXTURE_ROOT}"
SH
cat > "${doctor_bin}/uvx" <<'SH'
#!/usr/bin/env bash
exit 0
SH
cat > "${doctor_bin}/codex-harness-github-mcp-server" <<'SH'
#!/usr/bin/env bash
printf 'Version: 1.10.1\n'
SH
chmod +x "${doctor_bin}"/*

HOME="${doctor_home}" PATH="${doctor_bin}:${PATH}" PW_FIXTURE_ROOT="${browser_root}" \
  ./doctor.sh > "${test_root}/doctor-ok.log" 2>&1
grep -Fq 'Playwright Chromium and required components match' "${test_root}/doctor-ok.log" || \
  fail 'doctor did not verify all pinned Playwright browser components'
grep -Fq 'Everything is ready' "${test_root}/doctor-ok.log" || \
  fail 'doctor did not report full readiness after all checks passed'
grep -Fq 'pinned lifecycle hook runtime' "${test_root}/doctor-ok.log" || \
  fail 'doctor did not validate the installed runtime marker'

rm -f -- "${browser_root}/chromium_headless_shell-1237/INSTALLATION_COMPLETE"
HOME="${doctor_home}" PATH="${doctor_bin}:${PATH}" PW_FIXTURE_ROOT="${browser_root}" \
  ./doctor.sh > "${test_root}/doctor-missing.log" 2>&1
grep -Fq 'chromium_headless_shell-1237' "${test_root}/doctor-missing.log" || \
  fail 'doctor did not identify the missing pinned Playwright component'
grep -Fq 'npx -y @playwright/mcp@0.0.79 install-browser chromium' "${test_root}/doctor-missing.log" || \
  fail 'doctor did not print the correct pinned Playwright install command'
grep -Fq 'Core harness is ready; resolve the warnings above' "${test_root}/doctor-missing.log" || \
  fail 'doctor reported full readiness despite a missing browser component'

rm -f -- "${doctor_plugin}/mcp_config.json"
HOME="${doctor_home}" PATH="${doctor_bin}:${PATH}" PW_FIXTURE_ROOT="${browser_root}" \
  ./doctor.sh > "${test_root}/doctor-core-only.log" 2>&1
grep -Fq 'installed in core-only mode' "${test_root}/doctor-core-only.log" || \
  fail 'doctor did not distinguish a core-only installation from full MCP readiness'
grep -Fq 'Core harness is ready; resolve the warnings above' "${test_root}/doctor-core-only.log" || \
  fail 'doctor reported full readiness for a core-only installation'

printf 'relative/python\n' > "${doctor_plugin}/scripts/.python-runtime"
if HOME="${doctor_home}" PATH="${doctor_bin}:${PATH}" PW_FIXTURE_ROOT="${browser_root}" \
  ./doctor.sh > "${test_root}/doctor-invalid-runtime.log" 2>&1; then
  fail 'doctor accepted an invalid installed runtime marker'
fi
grep -Fq 'installed hook runtime marker is missing or invalid' "${test_root}/doctor-invalid-runtime.log" || \
  fail 'doctor did not explain the invalid installed runtime marker'

printf '[ok] source checks passed\n'
