# Live verification — 2026-09-07

Authorized local smoke checks were run on macOS with Antigravity CLI `1.1.27`
and `gemini-3.8-flash-high`. The plugin was validated and installed through the
first-party CLI: 12 skills, 7 agents, 4 hook groups, and 5 MCP servers. Installed
behavior and the managed global policy matched source. The existing canonical
MCP configuration, including isolated loopback-only Playwright, was retained;
no permission bypass was enabled.

## Observed samples

| Sample | Result | Duration | Runner continuations |
| --- | --- | --- | --- |
| Initial multi-milestone intake | Passed all 3 independent ACs; preserved the seeded user edit | 428.169 s | 0 |
| Initial tiny edit | Product test passed, but the strict status-line contract failed | 36.962 s | 0 |
| Final tiny edit | Passed behavior, one-file/one-hunk/10-line bound, and exact status-line contract | 40.742 s | 0 |
| Final multi-milestone intake | Passed all 3 independent ACs, integrated suite, allowed-path checks, and seeded user-edit preservation | 371.811 s | 0 |

The initial tiny response put its mode in parentheses inside the route instead
of using the required semicolon-separated fields. It also repeated the test
through plain unittest and then the counted adapter. The policy and fixture now
specify the exact report shape and request the counted named test directly. The
strict evaluator was not relaxed to accept the failed response.

Independent review additionally found an unresolved wildcard/symlink scope hole.
It was reproduced before the fix, then closed with the documented literal-only
scope rule and regression tests. The initial samples used behavior digest
`b9cc201bcecd9e9308954d11e5ec5cc278d7e58b97ed7fb03108497ffe09c0c8`;
the final samples use
`31239a74d5787c84c7d39211fdff1dfb61d6a230d921b728c36c448cf6ad1a73`.
Both final samples passed against the matching installed behavior. No extra
runner continuation prompt was sent in any sample; the failed initial tiny sample
remains reported rather than being omitted from the record.

## Deterministic verification

- `python3 -m unittest discover -s tests -p 'test_*.py' -q`: 197 cases,
  194 passed and 3 platform skips.
- `bash tests/test-source.sh`: passed source/policy/inventory, staged installer
  contents/idempotence, and doctor fixtures; its 15 JavaScript renderer tests passed.
- `git diff --check`: passed.
- Independent follow-up review: four targeted scope/adapter regression tests passed;
  the reported scope finding was resolved.

Windows runtime tests, PSScriptAnalyzer, and ShellCheck were not run on this Mac;
the repository CI remains the cross-platform check.

## What this does not establish

These are bounded behavioral smoke samples, not a matched three-repeat
baseline/candidate benchmark. The tiny fixture instructions changed between
samples, so their timings are not a speed comparison. No token-saving,
statistical reliability, or universal zero-test guarantee is claimed.

Zero runner continuations means the harness test driver did not send a follow-up
prompt during the sample. The JSON envelope does not establish exact internal
worker scheduling, number of permission/decision prompts, or worker reuse.
Native interruption/cancellation, app restart, mid-task requirement changes,
artifact persistence and source-aware resume remain untested. No custom
scheduler or task-state engine has been introduced on the strength of these runs.
See [the full pilot protocol](long-running-workflow.md#gated-native-pilot) and
[verification limits](verification-evidence.md).
