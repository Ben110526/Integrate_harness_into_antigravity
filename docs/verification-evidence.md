# Verification evidence: scope and test counts

The Stop hook is a bounded reminder, not a proof that a product requirement is
complete. It retries once and respects interruption/cancellation. A later allowed
stop with missing evidence must still be reported as incomplete or skipped.

## Execution scope

Checks need an explicit absolute `Cwd` inside a declared workspace. The hook
follows literal `cd` steps in success-preserving `&&` chains, including bounded
nested shell commands. An existing workspace subdirectory is valid. Outside
directories, targets/configuration paths, symlink escapes, missing cwd, shell
substitutions, and unverified location changes do not close verification debt.
Unresolved glob, brace, extglob, and tilde syntax is also declined. Since command
tokenization loses quoting, this includes quoted pattern selectors such as
`-p 'test_*.py'`: use default discovery, a literal pattern, or a named test for
automatic credit. The command is not blocked from execution.
Earlier writes in a rejected check chain still invalidate previous evidence.

Prefer setting `Cwd` directly to the package directory and passing literal test
paths over shell wrappers or environment-derived paths. This is conservative
command analysis, not a shell interpreter or a sandbox: arbitrary script internals,
runtime configuration, aliases, imports, and semantic module-to-test coverage still
require the verifier's inspection. No normal command permission is bypassed.

## Counted unittest runs

Python's normal `python -m unittest -q` can exit zero after running no tests.
The same problem exists for empty doctest input. These uncounted entry points,
including recognized coverage wrappers, no longer satisfy behavioral hook debt.
They can still be run and supply static/diagnostic information.

For a unittest project, use the bundled adapter with the same native selection:

```bash
# From this source checkout; set Cwd to the project when invoking the tool.
python3 /absolute/path/to/plugin/codex-claude-harness/scripts/verify_tests.py unittest discover -s tests -q
# Or one existing test:
python3 /absolute/path/to/plugin/codex-claude-harness/scripts/verify_tests.py unittest test_example.ExampleTests.test_result -q
```

Replace the example absolute path with the actual source/installed plugin path.
The adapter is copied with the existing plugin installer; no MCP, package, or new
dependency is needed. Use the project's Python interpreter with its dependencies.
On Windows, use `python` and quote the discovered absolute Windows adapter path.

The adapter uses unittest's native result object. Exit 0 requires native success
and a positive non-skipped executed count; failures return 1, and empty/all-skipped
runs, help, or invalid invocations return nonzero. Expected failures retain native
unittest semantics. Unsupported runners are rejected, not silently mapped to
unittest. Its stderr summary is diagnostic only, never an authenticated receipt.
Class/module fixture skips do not subtract successful tests from other fixtures;
methods with skipped subtests are conservatively excluded from the executed count.

The public [PostToolUse contract](https://antigravity.google/docs/hooks/) contains
tool arguments and an optional error, not guaranteed stdout/stderr or test counts.
The hook therefore recognizes the absolute bundled adapter plus its successful
tool outcome rather than parsing invented `toolResult` fields or a model-written
JSON file. Run checks in the foreground and verify completion: the hook cannot
prove an asynchronous command finished from an incomplete tool envelope.

Other recognized test runners retain existing command/exit-based behavior for
compatibility. State labels their count `unverified`; only a direct bundled
adapter invocation has `testCountStatus: runner-enforced`. This label describes
the runner contract, not semantic test coverage or an authenticated runtime
receipt. Explicit supported no-test opt-out flags are rejected as behavioral
evidence. There is **no universal zero-test guarantee** for arbitrary scripts,
package scripts, runner configuration, or asynchronous completion. The verifier
must inspect real results, disclose unavailable counts, and never call skipped
or irrelevant checks a pass. Adding another counted runner requires its own
native result contract and empty/failing/successful regression tests.

## Checkpoints are not source changes

The current workflow uses genuine native artifacts outside the workspace, not a
custom task-state engine. Such artifact writes leave source evidence and retry
state untouched. Ordinary workspace files, including `.harness/**` JSON or
scripts, still create debt even if a caller sets `IsArtifact=True`. No blanket
metadata exemption exists. See [the milestone and resume contract](long-running-workflow.md).

Local tests cover scope rejection, valid subdirectories, real empty unittest
execution, adapter success/failure, and artifact-versus-source debt. They do not
establish real Antigravity scheduling, account entitlement, or live resume;
those remain gated pilot checks.
