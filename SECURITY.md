# Security Policy

## Scope

This repository installs a prompt policy, lifecycle hooks, and MCP server
configuration for the first-party Antigravity CLI (`agy`). The hooks enforce
data-loss prevention (DLP) before write, terminal, and MCP tool calls, and a
verification gate at stop time.

In scope for reports:

- Secret or credential exfiltration paths that bypass the DLP hook.
- Hook logic that fails open silently (allowing without any visible warning).
- Installer behavior that destroys or corrupts user data (`~/.gemini` policy,
  settings, or unrelated files).
- Supply-chain weaknesses in pinned, checksum-verified components.
- Unsafe defaults in the bundled MCP configuration (network exposure, missing
  read-only enforcement).

Out of scope:

- Vulnerabilities in the Antigravity CLI itself, or in upstream MCP servers
  (report those to the respective vendors).
- Attacks requiring the user to approve a reviewed `force_ask` prompt.
- The vendor installer bootstrap (`https://antigravity.google/cli/install.*`),
  which is fetched over TLS without a hash because it is a moving target; the
  harness pins and checksum-verifies everything it vendors itself.

## Reporting a vulnerability

Please do **not** open a public issue for security reports.

- Email the maintainer via the contact listed on the GitHub profile at
  <https://github.com/Ben110526>, or use GitHub's private vulnerability
  reporting ("Security" tab → "Report a vulnerability") when enabled.
- Include: affected file/line or install path, a concrete reproduction or
  bypass scenario, and the impact (what leaks or breaks).
- Do not include real credentials, tokens, or private configuration in the
  report; redacted samples are sufficient.

## Response expectations

This is a community project maintained in spare time: reports are triaged as
soon as practical, and confirmed issues are fixed before public disclosure.
Reporters are credited in the changelog unless they prefer otherwise.

## Operational notes

- The DLP hook is defense in depth, not a perimeter: it reports categories,
  never matched secret values, and unknown encodings may evade pattern scans.
- When Python 3.8+ is unavailable, DLP falls back to forced review while the
  verification gate fails open to avoid lockouts; run `doctor.sh` /
  `doctor.ps1` to detect that state.
- Treat repository-supplied `.serena/project.yml` as untrusted before
  `activate_project`, and remember that `harness-sentry` sends tool arguments
  to the remote `mcp.sentry.dev` endpoint.
