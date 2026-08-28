# Fixture instructions

- Do not run terminal commands from the headless agent. The smoke runner executes
  `go test ./...` independently after the turn; inspect source and tests instead.
- Preserve the public `Retry` signature and keep the fix focused on attempt count.
