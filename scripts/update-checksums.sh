#!/usr/bin/env bash

set -euo pipefail

repo_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
version="${1:-}"
manifest_path=""

cleanup() {
  if [[ -n "${manifest_path}" && -f "${manifest_path}" ]]; then
    rm -f -- "${manifest_path}"
  fi
}
trap cleanup EXIT

if [[ ! "${version}" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  printf 'Usage: %s <github-mcp-version>\n' "${0##*/}" >&2
  printf 'Example: %s 1.10.1\n' "${0##*/}" >&2
  exit 2
fi

for runtime in curl python3; do
  if ! command -v "${runtime}" >/dev/null 2>&1; then
    printf 'Error: %s is required.\n' "${runtime}" >&2
    exit 1
  fi
done

manifest_path="$(mktemp "${TMPDIR:-/tmp}/github-mcp-checksums.XXXXXX")"
manifest_url="https://github.com/github/github-mcp-server/releases/download/v${version}/github-mcp-server_${version}_checksums.txt"
printf 'Downloading official GitHub MCP checksum manifest for v%s...\n' "${version}"
curl --proto '=https' --tlsv1.2 -fsSL "${manifest_url}" -o "${manifest_path}"

python3 - "${repo_root}" "${version}" "${manifest_path}" <<'PY'
from __future__ import annotations

import os
import pathlib
import re
import sys
import tempfile


root = pathlib.Path(sys.argv[1]).resolve()
version = sys.argv[2]
manifest_path = pathlib.Path(sys.argv[3])

assets = {
    "github-mcp-server_Darwin_arm64.tar.gz",
    "github-mcp-server_Darwin_x86_64.tar.gz",
    "github-mcp-server_Linux_arm64.tar.gz",
    "github-mcp-server_Linux_x86_64.tar.gz",
    "github-mcp-server_Windows_arm64.zip",
    "github-mcp-server_Windows_i386.zip",
    "github-mcp-server_Windows_x86_64.zip",
}
checksums: dict[str, str] = {}
line_pattern = re.compile(r"^([0-9a-fA-F]{64})  (github-mcp-server_[A-Za-z0-9_.-]+)$")
for line in manifest_path.read_text(encoding="utf-8").splitlines():
    match = line_pattern.fullmatch(line)
    if not match or match.group(2) not in assets:
        continue
    name = match.group(2)
    if name in checksums:
        raise SystemExit(f"duplicate checksum entry for {name}")
    checksums[name] = match.group(1).lower()

missing = sorted(assets - checksums.keys())
if missing:
    raise SystemExit(f"official manifest is missing required assets: {', '.join(missing)}")


def replace_expected(text: str, pattern: str, replacement: str, expected_count: int, label: str) -> str:
    updated, count = re.subn(pattern, replacement, text, flags=re.MULTILINE)
    if count != expected_count:
        raise SystemExit(f"expected exactly {expected_count} {label}; found {count}")
    return updated


def replace_once(text: str, pattern: str, replacement: str, label: str) -> str:
    return replace_expected(text, pattern, replacement, 1, label)


def replace_literal_expected(text: str, pattern: str, replacement: str, expected_count: int, label: str) -> str:
    updated, count = re.subn(pattern, lambda _match: replacement, text, flags=re.MULTILINE)
    if count != expected_count:
        raise SystemExit(f"expected exactly {expected_count} {label}; found {count}")
    return updated


def atomic_write(path: pathlib.Path, text: str, bom: bool = False) -> None:
    data = text.encode("utf-8")
    if bom:
        data = b"\xef\xbb\xbf" + data
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, path.stat().st_mode)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


install_sh_path = root / "install.sh"
install_sh = install_sh_path.read_text(encoding="utf-8")
install_sh = replace_once(
    install_sh,
    r'github_mcp_version="[0-9]+\.[0-9]+\.[0-9]+"',
    f'github_mcp_version="{version}"',
    "install.sh version",
)
for name in sorted(asset for asset in assets if "Windows" not in asset):
    install_sh = replace_once(
        install_sh,
        rf'(archive="{re.escape(name)}"\n\s+expected_hash=")[0-9a-f]{{64}}(")',
        rf'\g<1>{checksums[name]}\2',
        f"install.sh checksum for {name}",
    )

install_ps1_path = root / "install.ps1"
raw_ps1 = install_ps1_path.read_bytes()
had_bom = raw_ps1.startswith(b"\xef\xbb\xbf")
install_ps1 = raw_ps1.decode("utf-8-sig")
install_ps1 = replace_once(
    install_ps1,
    r'\$githubMcpVersion = "[0-9]+\.[0-9]+\.[0-9]+"',
    f'$githubMcpVersion = "{version}"',
    "install.ps1 version",
)
for name in sorted(asset for asset in assets if "Windows" in asset):
    install_ps1 = replace_once(
        install_ps1,
        rf'(\$archiveName = "{re.escape(name)}"\r?\n\s+\$expectedHash = ")[0-9a-f]{{64}}(")',
        rf'\g<1>{checksums[name]}\2',
        f"install.ps1 checksum for {name}",
    )

test_path = root / "tests/test-source.sh"
test_source = test_path.read_text(encoding="utf-8")
test_source = replace_once(
    test_source,
    r'github_mcp_version="[0-9]+\.[0-9]+\.[0-9]+"',
    f'github_mcp_version="{version}"',
    "test-source.sh shell version assertion",
)
test_source = replace_once(
    test_source,
    r'\$githubMcpVersion = "[0-9]+\.[0-9]+\.[0-9]+"',
    f'$githubMcpVersion = "{version}"',
    "test-source.sh PowerShell version assertion",
)
test_source = replace_once(
    test_source,
    r"installers must pin GitHub MCP v[0-9]+\.[0-9]+\.[0-9]+",
    f"installers must pin GitHub MCP v{version}",
    "test-source.sh version message",
)
test_source = replace_literal_expected(
    test_source,
    r"printf 'Version: [0-9]+\.[0-9]+\.[0-9]+\\n'",
    f"printf 'Version: {version}\\n'",
    2,
    "test-source.sh fake GitHub MCP version",
)
test_source = replace_literal_expected(
    test_source,
    r"printf '[0-9]+\.[0-9]+\.[0-9]+\\n' > \"\$\{fake_bin\}/codex-harness-github-mcp-server.version\"",
    f'printf \'{version}\\n\' > "${{fake_bin}}/codex-harness-github-mcp-server.version"',
    1,
    "test-source.sh fake GitHub MCP marker",
)
for name in sorted(assets):
    test_source = replace_once(
        test_source,
        rf'("{re.escape(name)}": ")[0-9a-f]{{64}}(")',
        rf'\g<1>{checksums[name]}\2',
        f"test-source.sh checksum for {name}",
    )

doctor_path = root / "doctor.sh"
doctor = doctor_path.read_text(encoding="utf-8")
doctor = replace_once(
    doctor,
    r"Version: [0-9]+\.[0-9]+\.[0-9]+",
    f"Version: {version}",
    "doctor.sh expected version",
)
doctor = replace_once(
    doctor,
    r"pinned [0-9]+\.[0-9]+\.[0-9]+ release",
    f"pinned {version} release",
    "doctor.sh version message",
)

profiles_path = root / "plugin/codex-claude-harness/skills/harness-mcp-profile/references/profiles.md"
profiles = profiles_path.read_text(encoding="utf-8")
profiles = replace_once(
    profiles,
    r"github-mcp-server` v[0-9]+\.[0-9]+\.[0-9]+",
    f"github-mcp-server` v{version}",
    "MCP profile GitHub version",
)

atomic_write(install_sh_path, install_sh)
atomic_write(install_ps1_path, install_ps1, bom=had_bom)
atomic_write(test_path, test_source)
atomic_write(doctor_path, doctor)
atomic_write(profiles_path, profiles)
print(f"Updated GitHub MCP v{version} and seven official checksums.")
PY

printf 'Run ./tests/test-source.sh before committing the release update.\n'
