#!/usr/bin/env bash

set -euo pipefail

package_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${package_root}/plugin/codex-claude-harness"
agy_executable="$(command -v agy || true)"
readiness_warnings=0

if [[ -z "${agy_executable}" ]]; then
  printf '[fail] agy is not installed or not on PATH.\n' >&2
  exit 1
fi

printf '[ok] agy: %s\n' "${agy_executable}"
"${agy_executable}" --version

plugin_list="$("${agy_executable}" plugin list)"
if [[ "${plugin_list}" != *'"name": "codex-claude-harness"'* ]]; then
  printf '[fail] codex-claude-harness is not installed. Run ./install.sh.\n' >&2
  exit 1
fi
printf '[ok] codex-claude-harness is installed.\n'

user_home="${HOME:?HOME is not set}"
plugin_install_dir=""
for candidate_dir in \
  "${user_home}/.gemini/config/plugins/codex-claude-harness" \
  "${user_home}/.gemini/antigravity-cli/plugins/codex-claude-harness"; do
  if [[ -d "${candidate_dir}" ]]; then
    plugin_install_dir="${candidate_dir}"
    break
  fi
done
plugin_check_dir="${plugin_dir}"
if [[ -n "${plugin_install_dir}" ]]; then
  plugin_check_dir="${plugin_install_dir}"
fi
"${agy_executable}" plugin validate "${plugin_check_dir}"

runtime_marker="${plugin_install_dir}/scripts/.python-runtime"
pinned_python=""
if [[ -z "${plugin_install_dir}" || ! -f "${runtime_marker}" ]] || \
  ! IFS= read -r pinned_python < "${runtime_marker}" || \
  [[ "${pinned_python}" != /* ]] || [[ ! -x "${pinned_python}" ]]; then
  printf '[fail] installed hook runtime marker is missing or invalid: %s. Rerun ./install.sh.\n' "${runtime_marker}" >&2
  exit 3
fi
if ! "${pinned_python}" -c 'import sys; raise SystemExit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
  printf '[fail] installed hook runtime must be Python 3.8 or newer: %s. Rerun ./install.sh.\n' "${pinned_python}" >&2
  exit 3
fi
python_command=("${pinned_python}")
python_version="$("${pinned_python}" -c 'import platform; print(platform.python_version())' 2>/dev/null || true)"
printf '[ok] pinned lifecycle hook runtime: Python %s (%s).\n' "${python_version}" "${pinned_python}"

mcp_enabled="false"
if [[ -n "${plugin_install_dir}" && -f "${plugin_install_dir}/mcp_config.json" ]]; then
  mcp_enabled="true"
fi

if [[ "${mcp_enabled}" != "true" ]]; then
  readiness_warnings=1
  printf '[warn] harness is installed in core-only mode; automatic MCP servers are not registered. Rerun ./install.sh after restoring network/runtime access to enable them.\n' >&2
else
  for runtime in npx uvx; do
    if ! command -v "${runtime}" >/dev/null 2>&1; then
      printf '[fail] automatic MCP runtime is missing: %s. Rerun ./install.sh after installing the development runtime.\n' "${runtime}" >&2
      exit 3
    fi
  done
  node_version="$(node --version 2>/dev/null || true)"
  node_version="${node_version#v}"
  IFS=. read -r node_major node_minor node_patch <<< "${node_version}"
  node_major="${node_major%%[^0-9]*}"
  node_minor="${node_minor%%[^0-9]*}"
  node_patch="${node_patch%%[^0-9]*}"
  if [[ -z "${node_major}" || -z "${node_minor}" || -z "${node_patch}" ]] ||
    (( 10#${node_major} < 20 )) ||
    (( 10#${node_major} == 20 && 10#${node_minor} < 18 )) ||
    (( 10#${node_major} == 20 && 10#${node_minor} == 18 && 10#${node_patch} < 1 )); then
    printf '[fail] Context7 requires Node.js 20.18.1 or newer; found %s.\n' "${node_version:-unknown}" >&2
    exit 3
  fi
  github_mcp="$(dirname -- "${agy_executable}")/codex-harness-github-mcp-server"
  if [[ ! -x "${github_mcp}" ]]; then
    printf '[fail] checksum-verified GitHub MCP binary is missing. Rerun ./install.sh.\n' >&2
    exit 3
  fi
  github_mcp_version="$("${github_mcp}" --version 2>&1)"
  if ! grep -Fqx 'Version: 1.10.1' <<< "${github_mcp_version}"; then
    printf '[fail] GitHub MCP version is not the pinned 1.10.1 release. Rerun ./install.sh.\n' >&2
    exit 3
  fi
  printf '[ok] automatic MCP runtimes: Node.js %s, npx, uvx, GitHub MCP.\n' "${node_version}"

  playwright_install_command='npx -y @playwright/mcp@0.0.79 install-browser chromium'
  if playwright_dry_run="$("${python_command[@]}" - <<'PY'
import os
import subprocess
import sys

environment = os.environ.copy()
environment["npm_config_fetch_retries"] = "1"
environment["npm_config_fetch_timeout"] = "5000"
try:
    result = subprocess.run(
        ["npx", "-y", "@playwright/mcp@0.0.79", "install-browser", "--dry-run", "chromium"],
        capture_output=True,
        check=False,
        env=environment,
        text=True,
        timeout=20,
    )
except (OSError, subprocess.TimeoutExpired):
    raise SystemExit(1)
sys.stdout.write(result.stdout)
raise SystemExit(result.returncode)
PY
  )"; then
    playwright_locations="$(printf '%s\n' "${playwright_dry_run}" | sed -n 's/^[[:space:]]*Install location:[[:space:]]*//p')"
    playwright_missing="false"
    playwright_location_count=0
    while IFS= read -r playwright_location; do
      [[ -n "${playwright_location}" ]] || continue
      playwright_location_count="$((playwright_location_count + 1))"
      if [[ ! -f "${playwright_location}/INSTALLATION_COMPLETE" ]]; then
        playwright_missing="true"
        printf '[warn] pinned Playwright browser component is missing or incomplete: %s\n' "${playwright_location}" >&2
      fi
    done < <(printf '%s\n' "${playwright_locations}")

    if [[ "${playwright_location_count}" == "0" ]]; then
      readiness_warnings=1
      printf '[warn] Playwright MCP returned no browser install locations; unable to verify Chromium. Run: %s\n' "${playwright_install_command}" >&2
    elif [[ "${playwright_missing}" == "true" ]]; then
      readiness_warnings=1
      printf '[warn] Install the browser revision pinned by the MCP package with: %s\n' "${playwright_install_command}" >&2
    else
      printf '[ok] Playwright Chromium and required components match @playwright/mcp@0.0.79.\n'
    fi
  else
    readiness_warnings=1
    printf '[warn] unable to verify the Playwright browser revision within 20s (offline/proxy/npm unavailable). Run when online: %s\n' "${playwright_install_command}" >&2
  fi
fi
policy_target="${user_home}/.gemini/GEMINI.md"
if [[ ! -f "${policy_target}" ]] || ! grep -Fq '<!-- auto-harness:start -->' "${policy_target}"; then
  printf '[fail] always-on global policy is missing. Run ./install.sh.\n' >&2
  exit 1
fi
printf '[ok] always-on global policy: %s\n' "${policy_target}"

model_list="$("${agy_executable}" models)"
if [[ "${model_list}" != *'gemini-3.7-flash-high'* ]]; then
  printf '[warn] Gemini 3.7 Flash High is not currently listed for this account.\n' >&2
  exit 2
fi
printf '[ok] Gemini 3.7 Flash High is available.\n'

if ((readiness_warnings > 0)); then
  printf '\nCore harness is ready; resolve the warnings above before relying on every automatic MCP. Use Gemini 3.7 Flash High for maximum coding accuracy.\n'
else
  printf '\nEverything is ready. Run agy and select Gemini 3.7 Flash High with /model for maximum coding accuracy.\n'
fi
