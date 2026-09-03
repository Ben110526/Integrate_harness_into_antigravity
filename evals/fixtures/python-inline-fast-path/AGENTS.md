# Fixture instructions

- This fixture is an internal, deterministic, one-file source bug with an existing
  focused behavioral test.
- Edit only `normalize.py`, keep the change to the private helper, and do not add,
  remove, rename, or reformat files.
- After the final write, run exactly
  `python3 -m unittest -q test_normalize.NormalizeTests.test_collapses_internal_spaces`.
