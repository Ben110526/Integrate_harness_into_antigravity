# Fixture instructions

- Do not run terminal commands from the headless agent. The smoke runner executes
  `cargo test --quiet` independently after the turn; inspect source and tests.
- Preserve the public function signature and keep the fix localized.
