---
name: harness-test
description: Discover and run the right verification ladder for a change or repository, then explain failures precisely.
---

# Test workflow

1. Discover existing project commands from manifests, CI configuration, and repository instructions.
2. Build a verification ladder: reproduction or focused test, affected package suite, lint/type check, build, then broader integration checks as justified. Map each supplied `AC-*` to at least one check or mark it `[UNRESOLVED]` with the missing evidence.
3. Run independent long checks concurrently when safe and when they do not compete for the same mutable resources.
4. Record exact commands and exit results; preserve the useful failure excerpt.
   Use an explicit in-workspace `Cwd` and literal in-scope test/config targets;
   shell substitutions and unverified directory changes cannot close hook debt.
   For unittest, run `python3 /absolute/path/to/this-plugin/scripts/verify_tests.py unittest <native arguments>`
   with the discovered installed plugin path. It returns nonzero for empty or
   all-skipped suites. Plain `python -m unittest`/`doctest` may pass with zero
   tests and are not behavioral hook evidence. For other runners, inspect their
   real results and disclose unavailable counts; name/exit recognition alone
   does not prove nonempty tests or coverage of the changed module. Never invent
   the adapter path or treat a printed summary/model-written receipt as proof.
5. Separate product regressions from environment failures or known pre-existing failures using evidence.
6. Do not edit product code unless the user asked for fixes; never conceal a failed check.
7. For bug fixes with a red-state command, rerun that exact command unchanged after the fix and record both results. If red-state execution was unsafe or infeasible, record the reason and the alternate falsification evidence.
8. Use `HARNESS_NO_RUNNABLE_CHECK: <specific reason>` only after confirming from repository instructions and tooling that no relevant safe check can run. Record it as a disclosed waiver and skipped evidence, never as a pass.
9. Return a compact `AC-ID -> command/evidence -> pass/fail/skipped` matrix and residual risk.
