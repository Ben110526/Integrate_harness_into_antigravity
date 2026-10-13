# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this repository does
not yet cut versioned releases, so entries are grouped by date.

## Unreleased

### Security

- DLP PreToolUse now covers `call_mcp_tool`: the hook matcher includes it and
  the guard scans the serialized MCP payload plus a flattened assignment view,
  so secret material can no longer leave through MCP tool arguments
  uninspected.
- DLP content scans decode bounded standalone base64 blobs, closing the
  simplest encoding evasion for tokens and private key blocks.

### Added

- `uninstall.sh` / `uninstall.ps1`: remove the plugin, restore the pre-install
  `GEMINI.md` from the automatic `.bak` backup, and remove the pinned GitHub
  MCP binary. `settings.json` is never touched (the installer never modifies
  it).
- `doctor.ps1`: Windows parity for the `doctor.sh` diagnostic health check.
- `SECURITY.md` with a private reporting process.
- The verification gate now flags partial/blocked results that follow a logic
  write without any verification attempt, instead of letting them pass
  silently.
- Delivery-review `evidenceSteps` are cross-checked against recorded
  successful checks at registration time, not only at completion.
- A `complete` result is rejected when logic files changed but every
  requirement is declared `static`.
- Citation grounding that cannot run (unknown workspace root or file over the
  size bound) now emits a visible warning instead of passing silently.
- Anti-loop gate allows now set a persisted flag that is surfaced in the next
  repair context, so bypassed gates remain auditable.

### Fixed

- The installers write the global policy atomically and keep the first
  pre-install `.bak` backup (PowerShell previously rewrote `GEMINI.md`
  in place with no backup and no atomicity).
- Browser QA eval: `/confirmation` only releases its token to a request
  carrying the JS-computed proof header, so a bare HTTP client can no longer
  pass the interaction checks by spoofing the User-Agent.
- Removed the dead `_ENV_EGRESS_COMMAND` pattern from the lifecycle guard.
- Documentation now warns that auto-approving test/build runners executes
  arbitrary `package.json` scripts without a prompt, that Sentry tool
  arguments leave the machine, and that repository-supplied Serena project
  files are untrusted.

## 2026-10-12

- Initial public engineering harness: always-on routing policy, 7 subagents,
  11 skills, 4 lifecycle hooks, 5 pinned MCP servers, eval harness, and live
  eval methodology. (See git history for the detailed evolution.)
