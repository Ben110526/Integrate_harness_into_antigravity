#!/usr/bin/env bash

set -euo pipefail

# Removes what install.sh installed: the harness plugin, the managed GEMINI.md
# block (restoring the pre-install backup when present), and the pinned GitHub
# MCP binary. The installer never modifies settings.json, so terminal
# permissions and other user settings are left untouched.

user_home="${HOME:?HOME is not set}"
policy_dir="${user_home}/.gemini"
policy_target="${policy_dir}/GEMINI.md"
policy_backup="${policy_target}.bak"
policy_start_marker='<!-- auto-harness:start -->'
policy_end_marker='<!-- auto-harness:end -->'
plugin_name="codex-claude-harness"

agy_executable="$(command -v agy || true)"
plugin_removed="false"
if [[ -n "${agy_executable}" ]] && "${agy_executable}" plugin uninstall "${plugin_name}" >/dev/null 2>&1; then
  plugin_removed="true"
  printf '[ok] plugin uninstalled via agy.\n'
fi
for candidate_dir in \
  "${policy_dir}/config/plugins/${plugin_name}" \
  "${policy_dir}/antigravity-cli/plugins/${plugin_name}"; do
  if [[ -d "${candidate_dir}" ]]; then
    case "${candidate_dir}" in
      "${user_home}"/.gemini/*/plugins/"${plugin_name}") ;;
      *)
        printf 'Error: refusing to remove unexpected path %s\n' "${candidate_dir}" >&2
        exit 1
        ;;
    esac
    rm -rf -- "${candidate_dir}"
    plugin_removed="true"
    printf '[ok] removed %s\n' "${candidate_dir}"
  fi
done
[[ "${plugin_removed}" == "true" ]] || printf '[skip] harness plugin was not installed.\n'

if [[ -n "${agy_executable}" ]]; then
  agy_dir="$(cd -- "$(dirname -- "${agy_executable}")" && pwd)"
  for artifact in \
    "${agy_dir}/codex-harness-github-mcp-server" \
    "${agy_dir}/codex-harness-github-mcp-server.version"; do
    if [[ -f "${artifact}" ]]; then
      rm -f -- "${artifact}"
      printf '[ok] removed %s\n' "${artifact}"
    fi
  done
fi

if [[ -f "${policy_backup}" ]]; then
  mv -- "${policy_backup}" "${policy_target}"
  printf '[ok] restored %s from the pre-install backup.\n' "${policy_target}"
elif [[ -f "${policy_target}" ]] && grep -Fq "${policy_start_marker}" "${policy_target}"; then
  policy_temp_path="$(mktemp "${policy_dir}/.auto-harness-policy.XXXXXX")"
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
  if [[ -s "${policy_temp_path}" ]]; then
    mv -- "${policy_temp_path}" "${policy_target}"
    printf '[ok] removed the managed block from %s\n' "${policy_target}"
  else
    rm -f -- "${policy_temp_path}" "${policy_target}"
    printf '[ok] removed %s (it only contained the managed block)\n' "${policy_target}"
  fi
else
  printf '[skip] no managed policy block found in %s.\n' "${policy_target}"
fi

printf 'Done. The installer never modifies settings.json, so no permission cleanup is needed.\n'
