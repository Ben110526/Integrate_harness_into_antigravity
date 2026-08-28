# Fixture instructions

- This fixture changes a public authorization contract, a security boundary, and
  persistence behavior; route it through `COMPLEX_IMPLEMENT`.
- Use independent researcher, implementer, reviewer, and verifier roles exactly as
  the installed harness requires. Reviewer and verifier branches stay read-only.
- Do not run terminal commands from the headless agent. The smoke runner executes
  `node --test` independently after the turn; inspect source and tests instead.
- Preserve the exported function/class names and do not weaken the tests.
