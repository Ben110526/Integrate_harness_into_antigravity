# Quality enforcement update — 2026-10-09

Core implementation and native pilot evaluator revision: `461153e6e05a41ea99023c773ea203331f0110cc`. The containing report commit adds the protocol-3 provenance guard described below.
Baseline harness: `028f3ea87fb68653db7c5777fa7e265aefc9a7c4`.

## Delivered behavior

1. Versioned source snapshots retain missing explicit inputs and detect content, type, permission-mode and link changes. Auto scope rescans for new inputs and refuses incomplete coverage. Legacy checkpoints remain reconstructable but their verified evidence is stale until scope and checks are refreshed. Tagged evidence requires matching absolute workspace provenance.
2. Independent oracles count executed Python unittest, Node test and Go test cases. Empty/all-skipped runs, insufficient counts and cached Go replay cannot pass. Unsupported counted runners are unverified; the smoke runner skips them before consuming model quota and cannot report coverage for an all-skipped selection.
3. Complex tasks require an independent draft acceptance review before locking contract version 2 and beginning product edits. Stable discovery branches can continue meanwhile. Simpler and existing version-1 workflows stay compatible.
4. Immutable acceptance cases record scenario, expected outcome and business-rule basis. Passed version-2 rows must map each case to an observed successful check, test ID and assertion. Unresolved rules cannot pass; duplicate JSON keys and inconsistent reports are rejected.
5. The opt-in implementation pilot checks every acceptance criterion independently in trusted fixture copies, protects user changes and file modes, separates task fulfillment from report truthfulness, and retains failures/timeouts in denominators. Installed plugin and managed global policy must match the selected harness source. Metadata records reproducible comparison keys, observed-only usage and all-attempt duration distributions.

JSON structure does not authenticate an independent reviewer, prove that the requirement inventory is semantically complete, or prove that an asserted test is relevant. The actual independent review and behavioral checks remain necessary. Native worker scheduling, permission grants, MCP connections and interruption/resume are not inferred from a final status line.

## Deterministic verification

- Full Python discovery: 418 tests, 3 expected Windows-only skips. This preceded the final smoke child-environment-only fix.
- Final protocol-3 `tests/test-source.sh` in the isolated frozen clone: 392 Python tests, 3 expected Windows-only skips; 17 MCP renderer and 13 agent renderer tests passed. This includes the final initial/continuation child-environment regression.
- Independent review reran 22 implementation benchmark tests (plus four additional profile-drift scenarios), 23 oracle and 20 eval/fake-client tests successfully; earlier corrected core checks passed 45 task-state and 66 completion tests.
- Native `agy plugin validate` passed. Staged and unstaged whitespace checks passed.

The fake-client/unit runs consume no native model quota. The original dirty checkout was preserved; implementation used the attached managed worktree.

## Local installation

The candidate plugin was installed and enabled with a recoverable backup. The installed plugin behavior digest is `6f862cd8c5583638215568264245ba8b2ab9384600e429b84d27e03afb059fbf`; the installer-owned global policy digest is `7d669688220d5acca5a4f58b6e9bd8f6cb62de0bd9c548d1f4417f286c1f57f0`. Both match the selected source. The later protocol-3 change affects evaluator code, tests and documentation only.

Installed checks passed 4 hook-protocol assertions, 13 version-2/duplicate-key hook tests, 5 source-snapshot assertions and 6 parallel-planner assertions. All five bundled MCP servers are configured enabled; connections were not probed. Existing MCP configuration and global-policy bytes outside the managed block were preserved. A fresh Antigravity session is required to load the updated rules.

## Native pilot: observed outcomes, comparison invalid

Six initial prompts were run: three per harness revision, zero runner continuations, `gemini-3.8-flash-high`, a 600-second timeout and the same `long-workflow-intake` brief/fixture/evaluator. All requested failures and timeouts are retained below. These are protocol-2 records from evaluator revision `461153e6e05a41ea99023c773ea203331f0110cc`.

The CLI version observed at batch start changed from **1.2.7** for baseline to **1.3.2** for candidate. The comparison keys differ. Protocol 2 did not probe the version before/after each trial, so the exact runtime version of individual trials is unobserved. The cause and timing of the version change are unobserved. These groups are **not a matched baseline/candidate comparison** and do not establish a causal improvement or regression in speed, completion or reliability. No extra native calls were spent to replace these records.

| Harness | Batch-start CLI | Task fulfilled | Initial prompt complete | Median seconds, all attempts | Min–max seconds | Usage observed |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 1.2.7 | 1/3 | 1/3 | 592.43 | 440.94–600.33 | 2/3 |
| candidate | 1.3.2 | 0/3 | 0/3 | 600.34 | 600.30–600.35 | 0/3 |

| Harness | Trial | AC pass count | Structured report | Initial prompt complete | Failure kind | Wall seconds |
| --- | --- | --- | --- | --- | --- | --- |
| baseline | 1 | 0/3 | unavailable | no | response_contract | 440.94 |
| baseline | 2 | 2/3 | unavailable | no | timeout | 600.33 |
| baseline | 3 | 3/3 | complete | yes | none | 592.43 |
| candidate | 1 | 2/3 | unavailable | no | timeout | 600.30 |
| candidate | 2 | 0/3 | unavailable | no | timeout | 600.34 |
| candidate | 3 | 1/3 | unavailable | no | timeout | 600.35 |

Per-AC pass counts across the three requested trials:

- baseline: AC-1 2/3, AC-2 2/3, AC-3 1/3.
- candidate: AC-1 2/3, AC-2 1/3, AC-3 0/3.

A native CLI `SUCCESS` is a terminal status, not evidence of task fulfillment. Baseline trial 1 returned a successful terminal envelope but no source changes, no valid completion report and 0/3 passing ACs. Independent checks rejected it. A timeout can still have partial source work; the AC matrix records those observed outcomes without claiming completion.

`false_complete` grades supported structured completion claims; an unavailable report is not proof that the model made no false claim in prose. Missing usage stays null and is excluded from observed totals. Permission grants, MCP connections, native worker scheduling, human interventions and interruption/resume have no stable observed trace here. Disk plugin and managed global policy provenance were verified; this does not authenticate the model's review record or runtime tool sequence. Three repeats on one compact fixture are not a general reliability guarantee. Fixed run order, service load, caches and the CLI version change further limit inference.

Protocol 3 was added after this finding. It probes the CLI immediately before/after each call, refuses pre-call drift without a model invocation, preserves actual outcomes after drift, and nulls invalid comparison keys. Fake-client regressions and independent source checks passed. This pilot was not rerun under protocol 3; no matched native effectiveness claim is made.

Raw response-free records: [baseline](eval-results/2026-10-09-baseline-protocol2.ndjson), [candidate](eval-results/2026-10-09-candidate-protocol2.ndjson). No model responses, conversation IDs, credentials or raw diagnostics are included.
