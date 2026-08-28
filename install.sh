#!/usr/bin/env bash

set -euo pipefail

package_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
plugin_dir="${package_root}/plugin/codex-claude-harness"
policy_source="${package_root}/global/GEMINI.md"
agy_executable="$(command -v agy || true)"
installer_path=""
policy_temp_path=""
github_mcp_temp_dir=""
plugin_temp_dir=""
agy_was_installed="true"
github_mcp_status="skipped"
github_mcp_version="1.10.1"
mcp_enabled="true"
skip_mcp="false"
playwright_default_origins='http://localhost:*;http://127.0.0.1:*;https://localhost:*;https://127.0.0.1:*'
playwright_extra_origins="${HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS:-}"
plugin_install_source="${plugin_dir}"
mcp_failure_reason=""
python_runtime=""

usage() {
  printf 'Usage: %s [--skip-mcp]\n' "${0##*/}"
  printf '  --skip-mcp  Install the core harness without starting or registering MCP servers.\n'
}

for argument in "$@"; do
  case "${argument}" in
    --skip-mcp)
      skip_mcp="true"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Error: unknown option: %s\n' "${argument}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ "${HARNESS_SKIP_MCP_BOOTSTRAP:-0}" == "1" ]]; then
  skip_mcp="true"
fi

cleanup() {
  if [[ -n "${installer_path}" && -f "${installer_path}" ]]; then
    rm -f -- "${installer_path}"
  fi
  if [[ -n "${policy_temp_path}" && -f "${policy_temp_path}" ]]; then
    rm -f -- "${policy_temp_path}"
  fi
  if [[ -n "${github_mcp_temp_dir}" && -d "${github_mcp_temp_dir}" ]]; then
    rm -rf -- "${github_mcp_temp_dir}"
  fi
  if [[ -n "${plugin_temp_dir}" && -d "${plugin_temp_dir}" ]]; then
    rm -rf -- "${plugin_temp_dir}"
  fi
}
trap cleanup EXIT

if [[ ! -f "${plugin_dir}/plugin.json" ]]; then
  printf 'Error: plugin source not found at %s\n' "${plugin_dir}" >&2
  exit 1
fi

if [[ ! -f "${policy_source}" ]]; then
  printf 'Error: global harness policy not found at %s\n' "${policy_source}" >&2
  exit 1
fi

if [[ -z "${agy_executable}" ]]; then
  agy_was_installed="false"
  if ! command -v curl >/dev/null 2>&1; then
    printf 'Error: curl is required to install Antigravity CLI.\n' >&2
    exit 1
  fi

  printf 'Antigravity CLI is not installed; downloading the official installer...\n'
  installer_path="$(mktemp "${TMPDIR:-/tmp}/agy-install.XXXXXX")"
  curl -fsSL https://antigravity.google/cli/install.sh -o "${installer_path}"
  bash "${installer_path}"

  user_home="${HOME:?HOME is not set}"
  if [[ -x "${user_home}/.local/bin/agy" ]]; then
    agy_executable="${user_home}/.local/bin/agy"
  else
    agy_executable="$(command -v agy || true)"
  fi
fi

if [[ -z "${agy_executable}" ]]; then
  printf 'Error: agy was installed but is not available on PATH. Open a new shell and rerun this installer.\n' >&2
  exit 1
fi

configure_optional_shell_paths() {
  [[ "${agy_was_installed}" == "false" ]] || return 0

  local user_home user_local_bin agy_bin_dir shell_config path_line config_root nushell_config_dir
  user_home="${HOME:?HOME is not set}"
  user_local_bin="$(cd -- "${user_home}/.local/bin" && pwd)"
  agy_bin_dir="$(cd -- "$(dirname -- "${agy_executable}")" && pwd)"
  [[ "${agy_bin_dir}" == "${user_local_bin}" ]] || return 0

  config_root="${XDG_CONFIG_HOME:-${user_home}/.config}"
  if command -v fish >/dev/null 2>&1 || [[ -d "${config_root}/fish" ]]; then
    shell_config="${config_root}/fish/config.fish"
    path_line="fish_add_path -g \"\$HOME/.local/bin\""
    mkdir -p -- "$(dirname -- "${shell_config}")"
    if [[ ! -f "${shell_config}" ]] || ! grep -Fqx "${path_line}" "${shell_config}"; then
      printf '\n%s\n' "${path_line}" >> "${shell_config}"
    fi
  fi

  if [[ -n "${XDG_CONFIG_HOME:-}" ]]; then
    nushell_config_dir="${XDG_CONFIG_HOME}/nushell"
  elif [[ "$(uname -s)" == "Darwin" ]]; then
    nushell_config_dir="${user_home}/Library/Application Support/nushell"
  else
    nushell_config_dir="${user_home}/.config/nushell"
  fi
  if command -v nu >/dev/null 2>&1 || [[ -d "${nushell_config_dir}" ]]; then
    shell_config="${nushell_config_dir}/config.nu"
    path_line="\$env.PATH = (\$env.PATH | prepend (\$nu.home-path | path join \".local\" \"bin\"))"
    mkdir -p -- "$(dirname -- "${shell_config}")"
    if [[ ! -f "${shell_config}" ]] || ! grep -Fqx "${path_line}" "${shell_config}"; then
      printf '\n%s\n' "${path_line}" >> "${shell_config}"
    fi
  fi
}

configure_optional_shell_paths

resolve_python_runtime() {
  local name candidate resolved_runtime temp_root
  if ! temp_root="$(unset CDPATH; cd -- "${TMPDIR:-/tmp}" 2>/dev/null && pwd -P)"; then
    temp_root=""
  fi
  for name in python3 python; do
    candidate="$(command -v "${name}" 2>/dev/null || true)"
    [[ -n "${candidate}" ]] || continue
    resolved_runtime="$("${candidate}" -c 'import os, sys; sys.exit(1) if sys.version_info < (3, 8) else print(os.path.realpath(sys.executable))' 2>/dev/null || true)"
    [[ "${resolved_runtime}" == /* && -x "${resolved_runtime}" ]] || continue
    case "${resolved_runtime}" in
      "${package_root}"|"${package_root}"/*|/tmp/*|/private/tmp/*|/var/tmp/*)
        continue
        ;;
    esac
    if [[ -n "${temp_root}" ]]; then
      case "${resolved_runtime}" in
        "${temp_root}"|"${temp_root}"/*) continue ;;
      esac
    fi
    python_runtime="${resolved_runtime}"
    return 0
  done
  return 1
}

if ! resolve_python_runtime; then
  printf '[warn] Python 3.8+ was not found; lifecycle security will require review and verification will fail open.\n' >&2
fi

install_github_mcp() {
  local runtime
  for runtime in node npx uvx; do
    if ! command -v "${runtime}" >/dev/null 2>&1; then
      mcp_failure_reason="missing runtime ${runtime}"
      return 1
    fi
  done

  local node_version node_major node_minor node_patch
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
    mcp_failure_reason="Context7 requires Node.js 20.18.1 or newer; found ${node_version:-unknown}"
    return 1
  fi

  if ! command -v curl >/dev/null 2>&1; then
    mcp_failure_reason="curl is unavailable"
    return 1
  fi

  local platform architecture archive expected_hash
  platform="$(uname -s)"
  architecture="$(uname -m)"
  case "${platform}/${architecture}" in
    Darwin/arm64)
      archive="github-mcp-server_Darwin_arm64.tar.gz"
      expected_hash="ca530ba9abf04030104166cc37e1072087a30a173e921c0ed9064f98c73ca039"
      ;;
    Darwin/x86_64)
      archive="github-mcp-server_Darwin_x86_64.tar.gz"
      expected_hash="ea6e86baea583c6c5b55cce071c1c19253009a90f1e987788cb5eb228fcd9556"
      ;;
    Linux/arm64|Linux/aarch64)
      archive="github-mcp-server_Linux_arm64.tar.gz"
      expected_hash="c51dc6cf192c35a328b9f71696d42c38a9a3ba3c2ffe010da836bed071d1ac8a"
      ;;
    Linux/x86_64|Linux/amd64)
      archive="github-mcp-server_Linux_x86_64.tar.gz"
      expected_hash="c2629e850a344275cfc5a1590acdfd8c11476a44b688812d460163768e05572d"
      ;;
    *)
      mcp_failure_reason="unsupported GitHub MCP platform ${platform}/${architecture}"
      return 1
      ;;
  esac

  local bin_dir target marker installed_version_output archive_path actual_hash extracted
  bin_dir="$(cd -- "$(dirname -- "${agy_executable}")" && pwd)"
  target="${bin_dir}/codex-harness-github-mcp-server"
  marker="${target}.version"
  if [[ -x "${target}" && -f "${marker}" ]] && \
    [[ "$(< "${marker}")" == "${github_mcp_version}" ]]; then
    installed_version_output="$("${target}" --version 2>/dev/null || true)"
    if grep -Fqx "Version: ${github_mcp_version}" <<< "${installed_version_output}"; then
      github_mcp_status="v${github_mcp_version} already installed and verified"
      return
    fi
    printf 'Existing GitHub MCP failed version verification; reinstalling v%s...\n' "${github_mcp_version}"
  fi

  printf 'Downloading pinned GitHub MCP server v%s...\n' "${github_mcp_version}"
  if ! github_mcp_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/github-mcp.XXXXXX")"; then
    mcp_failure_reason="could not create a temporary directory for GitHub MCP"
    return 1
  fi
  archive_path="${github_mcp_temp_dir}/${archive}"
  if ! curl -fsSL \
    "https://github.com/github/github-mcp-server/releases/download/v${github_mcp_version}/${archive}" \
    -o "${archive_path}"; then
    mcp_failure_reason="GitHub release download failed (network, proxy, or rate limit)"
    return 1
  fi

  if command -v shasum >/dev/null 2>&1; then
    actual_hash="$(shasum -a 256 "${archive_path}" | awk '{print $1}')"
  elif command -v sha256sum >/dev/null 2>&1; then
    actual_hash="$(sha256sum "${archive_path}" | awk '{print $1}')"
  else
    mcp_failure_reason="shasum or sha256sum is unavailable"
    return 1
  fi
  actual_hash="$(printf '%s' "${actual_hash}" | tr '[:upper:]' '[:lower:]')"
  if [[ "${actual_hash}" != "${expected_hash}" ]]; then
    mcp_failure_reason="GitHub MCP checksum mismatch for ${archive}"
    return 1
  fi

  if ! tar -xzf "${archive_path}" -C "${github_mcp_temp_dir}"; then
    mcp_failure_reason="GitHub MCP archive extraction failed"
    return 1
  fi
  extracted="$(find "${github_mcp_temp_dir}" -type f -name 'github-mcp-server' -print -quit)"
  if [[ -z "${extracted}" ]]; then
    mcp_failure_reason="GitHub MCP archive did not contain the expected executable"
    return 1
  fi
  if ! cp -- "${extracted}" "${target}" || ! chmod 0755 "${target}" || \
    ! printf '%s\n' "${github_mcp_version}" > "${marker}"; then
    mcp_failure_reason="GitHub MCP binary could not be installed beside agy"
    return 1
  fi
  github_mcp_status="v${github_mcp_version} installed and verified"
}

validate_playwright_origins() {
  [[ -z "${playwright_extra_origins}" ]] && return 0

  if [[ "${playwright_extra_origins}" == ';'* || "${playwright_extra_origins}" == *';' || \
    "${playwright_extra_origins}" == *';;'* ]]; then
    printf 'Error: HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS contains an empty origin.\n' >&2
    return 1
  fi

  local origin port
  local -a origins
  IFS=';' read -r -a origins <<< "${playwright_extra_origins}"
  for origin in "${origins[@]}"; do
    if [[ -z "${origin}" || "${origin}" == *'*'* || \
      ! "${origin}" =~ ^https?://([A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?)(:([0-9]{1,5}))?$ ]]; then
      printf 'Error: HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS must be a semicolon-separated list of exact HTTP(S) origins without paths, credentials, or wildcards; invalid value: %s\n' "${origin:-<empty>}" >&2
      return 1
    fi
    port="${BASH_REMATCH[4]:-}"
    if [[ -n "${port}" ]] && (( 10#${port} < 1 || 10#${port} > 65535 )); then
      printf 'Error: invalid port in HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS: %s\n' "${origin}" >&2
      return 1
    fi
  done
}

prepare_plugin_source() {
  plugin_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/codex-harness-plugin.XXXXXX")"
  cp -R -- "${plugin_dir}/." "${plugin_temp_dir}/"
  plugin_install_source="${plugin_temp_dir}"

  if [[ -n "${python_runtime}" ]]; then
    printf '%s\n' "${python_runtime}" > "${plugin_install_source}/scripts/.python-runtime"
    chmod 0600 "${plugin_install_source}/scripts/.python-runtime"
  else
    rm -f -- "${plugin_install_source}/scripts/.python-runtime"
  fi

  if [[ "${mcp_enabled}" != "true" ]]; then
    rm -f -- "${plugin_install_source}/mcp_config.json"
    return
  fi

  HARNESS_MCP_CONFIG="${plugin_install_source}/mcp_config.json" \
    HARNESS_PLAYWRIGHT_ORIGINS="${playwright_default_origins};${playwright_extra_origins}" \
    node -e '
      const fs = require("fs");
      const path = process.env.HARNESS_MCP_CONFIG;
      const config = JSON.parse(fs.readFileSync(path, "utf8"));
      const args = config.mcpServers["harness-playwright"].args;
      const index = args.indexOf("--allowed-origins");
      if (index < 0 || index + 1 >= args.length) throw new Error("Playwright allowlist argument is missing");
      args[index + 1] = process.env.HARNESS_PLAYWRIGHT_ORIGINS;
      fs.writeFileSync(path, JSON.stringify(config, null, 2) + "\n", { mode: 0o600 });
    '
}

if [[ "${skip_mcp}" == "true" ]]; then
  mcp_enabled="false"
  github_mcp_status="skipped; core-only plugin requested"
elif ! validate_playwright_origins; then
  exit 2
elif ! install_github_mcp; then
  mcp_enabled="false"
  github_mcp_status="unavailable; installed core-only harness"
  printf '[warn] MCP bootstrap unavailable: %s. Continuing with the core harness only.\n' "${mcp_failure_reason}" >&2
  printf '[warn] Fix the runtime/network issue and rerun ./install.sh to enable MCP.\n' >&2
fi

prepare_plugin_source

printf 'Validating harness plugin...\n'
"${agy_executable}" plugin validate "${plugin_install_source}"

printf 'Installing or updating harness plugin...\n'
"${agy_executable}" plugin install "${plugin_install_source}"

user_home="${HOME:?HOME is not set}"
policy_dir="${user_home}/.gemini"
policy_target="${policy_dir}/GEMINI.md"
policy_start_marker='<!-- auto-harness:start -->'
policy_end_marker='<!-- auto-harness:end -->'

printf 'Installing or updating always-on global policy...\n'
mkdir -p -- "${policy_dir}"
policy_temp_path="$(mktemp "${TMPDIR:-/tmp}/auto-harness-policy.XXXXXX")"
if [[ -f "${policy_target}" ]]; then
  awk -v start="${policy_start_marker}" -v end="${policy_end_marker}" '
    { sub(/\r$/, "") }
    $0 == start { in_managed_block = 1; next }
    $0 == end { in_managed_block = 0; next }
    in_managed_block { next }
    /^[[:space:]]*$/ { pending_blank_lines += 1; next }
    {
      while (pending_blank_lines > 0) {
        print ""
        pending_blank_lines -= 1
      }
      print
    }
  ' "${policy_target}" > "${policy_temp_path}"
fi

if [[ -s "${policy_temp_path}" ]]; then
  printf '\n' >> "${policy_temp_path}"
fi
printf '%s\n' "${policy_start_marker}" >> "${policy_temp_path}"
while IFS= read -r policy_line || [[ -n "${policy_line}" ]]; do
  printf '%s\n' "${policy_line}" >> "${policy_temp_path}"
done < "${policy_source}"
printf '%s\n' "${policy_end_marker}" >> "${policy_temp_path}"
mv -- "${policy_temp_path}" "${policy_target}"
policy_temp_path=""

plugin_install_dir=""
for candidate_dir in \
  "${user_home}/.gemini/config/plugins/codex-claude-harness" \
  "${user_home}/.gemini/antigravity-cli/plugins/codex-claude-harness"; do
  if [[ -d "${candidate_dir}" ]]; then
    plugin_install_dir="${candidate_dir}"
    break
  fi
done

if [[ -n "${plugin_install_dir}" ]]; then
  if [[ -n "${python_runtime}" ]]; then
    mkdir -p -- "${plugin_install_dir}/scripts"
    printf '%s\n' "${python_runtime}" > "${plugin_install_dir}/scripts/.python-runtime"
    chmod 0600 "${plugin_install_dir}/scripts/.python-runtime"
  else
    rm -f -- "${plugin_install_dir}/scripts/.python-runtime"
  fi
fi

if [[ "${mcp_enabled}" != "true" && -n "${plugin_install_dir}" ]]; then
  rm -f -- "${plugin_install_dir}/mcp_config.json"
fi

cli_size="$(du -h "${agy_executable}" 2>/dev/null | awk 'NR == 1 { print $1 }')"
cli_kib="$(du -sk "${agy_executable}" 2>/dev/null | awk 'NR == 1 { print $1 }')"
if [[ -z "${cli_size}" ]]; then
  cli_size="không xác định"
fi

plugin_size="không xác định"
plugin_kib="0"
if [[ -n "${plugin_install_dir}" ]]; then
  plugin_size="$(du -sh "${plugin_install_dir}" 2>/dev/null | awk 'NR == 1 { print $1 }')"
  plugin_kib="$(du -sk "${plugin_install_dir}" 2>/dev/null | awk 'NR == 1 { print $1 }')"
fi

total_size="không xác định"
if [[ "${cli_kib}" =~ ^[0-9]+$ && "${plugin_kib}" =~ ^[0-9]+$ ]]; then
  total_kib="$((cli_kib + plugin_kib))"
  total_size="$(awk -v kib="${total_kib}" 'BEGIN {
    if (kib >= 1048576) printf "%.2f GB", kib / 1048576;
    else if (kib >= 1024) printf "%.2f MB", kib / 1024;
    else printf "%d KB", kib;
  }')"
fi

agy_status="đã có sẵn, giữ nguyên"
if [[ "${agy_was_installed}" == "false" ]]; then
  agy_status="vừa cài mới"
fi

skill_count="$(find "${plugin_dir}/skills" -mindepth 2 -maxdepth 2 -type f -name 'SKILL.md' | wc -l | tr -d '[:space:]')"
agent_count="$(find "${plugin_dir}/agents" -mindepth 1 -maxdepth 1 -type f -name '*.md' | wc -l | tr -d '[:space:]')"
component_summary="${skill_count} skills, ${agent_count} subagents, 1 policy rule"
if [[ -f "${plugin_dir}/hooks.json" ]]; then
  component_summary="${component_summary}, 4 lifecycle hooks"
fi
if [[ "${mcp_enabled}" == "true" ]]; then
  component_summary="${component_summary}, 5 auto-routed MCP servers"
else
  component_summary="${component_summary}, core-only (MCP disabled)"
fi

printf '\n============================================================\n'
printf 'CÀI ĐẶT THÀNH CÔNG\n'
printf '============================================================\n'
printf 'Antigravity CLI : %s\n' "${agy_executable}"
printf 'Trạng thái      : %s\n' "${agy_status}"
printf 'Dung lượng CLI  : %s\n' "${cli_size}"
if [[ -n "${plugin_install_dir}" ]]; then
  printf 'Harness plugin  : %s\n' "${plugin_install_dir}"
else
  printf 'Harness plugin  : đã cài, nhưng CLI không công bố đường dẫn staging\n'
fi
printf 'Dung lượng plugin: %s\n' "${plugin_size}"
printf 'Global policy   : %s\n' "${policy_target}"
printf 'GitHub MCP      : %s\n' "${github_mcp_status}"
printf 'Tổng dung lượng  : %s\n' "${total_size}"
printf 'Thành phần      : %s\n' "${component_summary}"
printf 'Nguồn cài       : %s\n' "${package_root}"
printf '============================================================\n'
printf 'Dùng hằng ngày  : cd /duong/dan/project && agy\n'
printf 'Model coding    : chọn Gemini 3.7 Flash High bằng /model (được lưu qua các phiên)\n'
printf 'Lần chạy đầu có thể mở browser để đăng nhập Google.\n'
if [[ "${agy_was_installed}" == "false" ]]; then
  printf 'Shell PATH      : bash/zsh và Fish/Nushell đã được cấu hình khi phát hiện shell tương ứng.\n'
fi
