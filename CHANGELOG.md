# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this repository does
not yet cut versioned releases, so entries are grouped by date.

## Unreleased

### Security

- Native `write_file(Path, Content, Overwrite)` receives the same secret checks
  and verification invalidation as legacy file-writing tools. Protocol artifacts
  register only after an observed write inside the current artifact directory.
- DLP PreToolUse now covers `call_mcp_tool`: the hook matcher includes it and
  the guard scans the serialized MCP payload plus a flattened assignment view,
  so secret material can no longer leave through MCP tool arguments
  uninspected.
- DLP content scans decode bounded standalone base64 blobs, closing the
  simplest encoding evasion for tokens and private key blocks.

### Added

- Interrupted worker assignments retain their original owner and observed
  handoff history. A dated, one-shot POSIX runner can resume the same native
  conversation after a quota reset and record the CLI outcome separately
  from the acceptance result.
- Ordinary implementation requests with two or more independent units now
  assign each unit to a distinct implementer. After the owners hand off,
  the coordinator checks their combined changes and obtains independent
  delivery review.
- Parallel assignments now track owners, file scope, dependencies and checks
  in the harness plan. The same handoff and verification workflow can use
  the native board when the user starts `/swarm`.
- `uninstall.sh` / `uninstall.ps1`: remove the plugin, strip only the managed
  block from current `GEMINI.md`, retain the original `.bak` for recovery, and
  remove the pinned GitHub MCP binary. `settings.json` is never touched.
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

- The verification gate now recognizes checks whose terminal result appears
  after `PostToolUse`. It matches the original step and uses the CLI's process
  exit code, so a failed test with an empty callback error is recorded as a
  failure. Checks with unresolved results stay unverified. Upgrading clears
  older cached successes while preserving task, edit and unresolved-failure history.
- Plugin policy includes explicit `trigger: always_on` frontmatter required by
  the current Antigravity validator; its body still matches the global policy.
- Verification reads the current CLI's `transcript_full.jsonl` as well as the
  legacy `transcript.jsonl`, keeping both artifact-directory containment checks.
  This restores observed request IDs needed before normal implementation.
- Bounded transcript reads discard a cut-off first line before UTF-8 decoding,
  so a split multibyte character cannot hide later complete request records.
- Uninstall preserves user rules added after installation. Install/reinstall
  reject malformed managed markers and avoid backing up already-managed policy.
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
