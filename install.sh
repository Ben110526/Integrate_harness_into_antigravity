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
profile_temp_dir=""
agy_was_installed="true"
github_mcp_status="skipped"
github_mcp_version="1.10.1"
mcp_enabled="true"
skip_mcp="false"
playwright_unrestricted="false"
playwright_extra_origins="${HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS:-}"
playwright_mode="loopback"
harness_config_path=""
effective_mcp_config=""
enabled_mcp_servers=""
plugin_install_source="${plugin_dir}"
mcp_failure_reason=""
python_runtime=""

usage() {
  printf 'Usage: %s [--config PATH] [--skip-mcp] [--playwright-unrestricted]\n' "${0##*/}"
  printf '  --config PATH              Use an explicit strict v1 MCP install profile.\n'
  printf '  --skip-mcp                 Install the core harness without starting or registering MCP servers.\n'
  printf '  --playwright-unrestricted  Allow Playwright MCP to access all HTTP(S) origins.\n'
}

while (( $# > 0 )); do
  case "$1" in
    --config)
      if (( $# < 2 )) || [[ -z "$2" ]]; then
        printf 'Error: --config requires a path.\n' >&2
        exit 2
      fi
      harness_config_path="$2"
      shift 2
      ;;
    --skip-mcp)
      skip_mcp="true"
      shift
      ;;
    --playwright-unrestricted)
      playwright_unrestricted="true"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      printf 'Error: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "${harness_config_path}" && -f "${package_root}/harness.config.json" ]]; then
  harness_config_path="${package_root}/harness.config.json"
fi

if [[ "${HARNESS_SKIP_MCP_BOOTSTRAP:-0}" == "1" ]]; then
  skip_mcp="true"
fi

if [[ "${skip_mcp}" == "true" && "${playwright_unrestricted}" == "true" ]]; then
  printf 'Error: --skip-mcp cannot be combined with --playwright-unrestricted.\n' >&2
  exit 2
fi
if [[ "${playwright_unrestricted}" == "true" && -n "${playwright_extra_origins}" ]]; then
  printf 'Error: --playwright-unrestricted cannot be combined with HARNESS_PLAYWRIGHT_ALLOWED_ORIGINS.\n' >&2
  exit 2
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
  if [[ -n "${profile_temp_dir}" && -d "${profile_temp_dir}" ]]; then
    rm -rf -- "${profile_temp_dir}"
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

mcp_server_enabled() {
  local inventory=",$1,"
  [[ "${inventory}" == *",$2,"* ]]
}

node_mcp_runtime_available() {
  local node_version node_major node_minor node_patch
  if ! command -v node >/dev/null 2>&1 || ! command -v npx >/dev/null 2>&1; then
    mcp_failure_reason="Node.js and npx are required by enabled Node-based MCP servers"
    return 1
  fi
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
    mcp_failure_reason="enabled Node-based MCP servers require Node.js 20.18.1 or newer; found ${node_version:-unknown}"
    return 1
  fi
}

render_mcp_profile() {
  local output_path="$1"
  shift
  local server_name playwright_disabled="false"
  local -a render_arguments
  render_arguments=(
    "${package_root}/scripts/render-mcp-config.js"
    --input "${plugin_dir}/mcp_config.json"
    --output "${output_path}"
  )
  if [[ -n "${harness_config_path}" ]]; then
    render_arguments+=(--config "${harness_config_path}")
  fi
  for server_name in "$@"; do
    if [[ "${server_name}" == "playwright" ]]; then
      playwright_disabled="true"
      break
    fi
  done
  if [[ "${playwright_disabled}" != "true" && "${playwright_unrestricted}" == "true" ]]; then
    render_arguments+=(--playwright-mode unrestricted)
  elif [[ "${playwright_disabled}" != "true" && -n "${playwright_extra_origins}" ]]; then
    render_arguments+=(--playwright-extra-origins "${playwright_extra_origins}")
  fi
  while (( $# > 0 )); do
    render_arguments+=(--disable-server "$1")
    shift
  done

  local profile_summary
  if ! profile_summary="$(node "${render_arguments[@]}")"; then
    return 1
  fi
  enabled_mcp_servers="$(printf '%s\n' "${profile_summary}" | sed -n 's/^mcp\.servers=//p')"
  playwright_mode="$(printf '%s\n' "${profile_summary}" | sed -n 's/^playwright\.mode=//p')"
  if [[ "$(printf '%s\n' "${profile_summary}" | grep -c '^mcp\.servers=')" != "1" ||
    "$(printf '%s\n' "${profile_summary}" | grep -c '^playwright\.mode=')" != "1" ]]; then
    printf 'Error: MCP profile renderer returned an invalid summary.\n' >&2
    return 1
  fi
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
  rm -f -- "${plugin_install_source}/mcp_config.json"
  cp -- "${effective_mcp_config}" "${plugin_install_source}/mcp_config.json"
  chmod 0600 "${plugin_install_source}/mcp_config.json"
}

if [[ "${skip_mcp}" == "true" ]]; then
  mcp_enabled="false"
  github_mcp_status="skipped; core-only plugin requested"
elif ! validate_playwright_origins; then
  exit 2
elif ! command -v node >/dev/null 2>&1; then
  if [[ -n "${harness_config_path}" ]]; then
    printf 'Error: Node.js is required to validate the MCP install profile: %s\n' "${harness_config_path}" >&2
    exit 2
  fi
  mcp_enabled="false"
  github_mcp_status="unavailable; installed core-only harness"
  printf '[warn] MCP bootstrap unavailable: Node.js is missing. Continuing with the core harness only.\n' >&2
  printf '[warn] Install Node.js 20.18.1+ and rerun ./install.sh to enable MCP.\n' >&2
else
  profile_temp_dir="$(mktemp -d "${TMPDIR:-/tmp}/harness-mcp-profile.XXXXXX")"
  requested_mcp_config="${profile_temp_dir}/requested.json"
  if ! render_mcp_profile "${requested_mcp_config}"; then
    exit 2
  fi
  requested_mcp_servers="${enabled_mcp_servers}"
  disabled_mcp_servers=()

  if mcp_server_enabled "${requested_mcp_servers}" context7 ||
    mcp_server_enabled "${requested_mcp_servers}" playwright; then
    if ! node_mcp_runtime_available; then
      mcp_server_enabled "${requested_mcp_servers}" context7 && disabled_mcp_servers+=(context7)
      mcp_server_enabled "${requested_mcp_servers}" playwright && disabled_mcp_servers+=(playwright)
      printf '[warn] %s; those MCP servers were omitted.\n' "${mcp_failure_reason}" >&2
    fi
  fi
  if mcp_server_enabled "${requested_mcp_servers}" serena && ! command -v uvx >/dev/null 2>&1; then
    disabled_mcp_servers+=(serena)
    printf '[warn] Serena MCP was omitted because uvx is unavailable.\n' >&2
  fi
  if (( ${#disabled_mcp_servers[@]} > 0 )); then
    effective_mcp_config="${profile_temp_dir}/effective.json"
    if ! render_mcp_profile "${effective_mcp_config}" "${disabled_mcp_servers[@]}"; then
      exit 2
    fi
  else
    effective_mcp_config="${requested_mcp_config}"
  fi
  if [[ -z "${enabled_mcp_servers}" ]]; then
    mcp_enabled="false"
    [[ "${github_mcp_status}" != "skipped" ]] || github_mcp_status="disabled by install profile"
  fi
fi

# Validate and plan the MCP inventory before any network download, upstream
# installer execution, shell-profile update, plugin write, or policy write.
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

configure_optional_shell_paths

if [[ "${skip_mcp}" != "true" ]] && mcp_server_enabled "${enabled_mcp_servers}" github; then
  if ! install_github_mcp; then
    disabled_mcp_servers+=(github)
    github_mcp_status="unavailable; GitHub MCP omitted"
    printf '[warn] GitHub MCP bootstrap unavailable: %s. Continuing with independent MCP servers.\n' "${mcp_failure_reason}" >&2
    effective_mcp_config="${profile_temp_dir}/effective-github.json"
    if ! render_mcp_profile "${effective_mcp_config}" "${disabled_mcp_servers[@]}"; then
      exit 2
    fi
  fi
elif [[ "${skip_mcp}" != "true" ]]; then
  github_mcp_status="disabled by effective configuration"
fi

if [[ -z "${enabled_mcp_servers}" ]]; then
  mcp_enabled="false"
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
  mcp_server_count="$(printf '%s' "${enabled_mcp_servers}" | awk -F, '{ print NF }')"
  component_summary="${component_summary}, ${mcp_server_count} auto-routed MCP servers"
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
if [[ "${mcp_enabled}" == "true" && "${playwright_mode}" == "unrestricted" ]]; then
  printf 'Playwright MCP  : unrestricted origins (explicit opt-in)\n'
elif [[ "${mcp_enabled}" == "true" && "${playwright_mode}" == "loopback-plus-allowlist" ]]; then
  printf 'Playwright MCP  : loopback plus custom origin allowlist\n'
elif [[ "${mcp_enabled}" == "true" && "${playwright_mode}" == "allowlist" ]]; then
  printf 'Playwright MCP  : exact custom origin allowlist\n'
elif [[ "${mcp_enabled}" == "true" && "${playwright_mode}" == "disabled" ]]; then
  printf 'Playwright MCP  : disabled by install profile\n'
elif [[ "${mcp_enabled}" == "true" ]]; then
  printf 'Playwright MCP  : loopback origins only\n'
else
  printf 'Playwright MCP  : disabled with MCP bootstrap\n'
fi
if [[ -n "${harness_config_path}" ]]; then
  printf 'Install profile : %s\n' "${harness_config_path}"
fi
printf 'Tổng dung lượng  : %s\n' "${total_size}"
printf 'Thành phần      : %s\n' "${component_summary}"
printf 'Nguồn cài       : %s\n' "${package_root}"
printf '============================================================\n'
printf 'Dùng hằng ngày  : cd /duong/dan/project && agy\n'
printf 'Model coding    : chọn Gemini 3.8 Flash High bằng /model (được lưu qua các phiên)\n'
printf 'Lần chạy đầu có thể mở browser để đăng nhập Google.\n'
if [[ "${agy_was_installed}" == "false" ]]; then
  printf 'Shell PATH      : bash/zsh và Fish/Nushell đã được cấu hình khi phát hiện shell tương ứng.\n'
fi
