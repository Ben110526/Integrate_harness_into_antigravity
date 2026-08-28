# Fixture instructions

- Do not run terminal commands from the headless agent. The smoke runner executes
  `python3 -m unittest -q` independently after the agent turn; use source and test
  inspection for the in-turn verification report.
- Keep changes limited to the requested calculator behavior and regression test.
