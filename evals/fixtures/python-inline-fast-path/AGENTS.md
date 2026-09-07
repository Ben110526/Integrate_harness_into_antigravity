# Fixture instructions

- This fixture is an internal, deterministic, one-file source bug with an existing
  focused behavioral test.
- Edit only `normalize.py`, keep the change to the private helper, and do not add,
  remove, rename, or reformat files.
- After the final write, run only
  `test_normalize.NormalizeTests.test_collapses_internal_spaces` through the
  discovered installed harness `scripts/verify_tests.py unittest` adapter with
  the project's Python interpreter; do not repeat the same test via plain unittest.
- Use the exact final line shape:
  `Harness: IMPLEMENT; mode: inline-fast-path; passed: ...; failed/skipped: ...`.
