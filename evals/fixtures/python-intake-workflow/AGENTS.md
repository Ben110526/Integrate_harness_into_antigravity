# Workflow fixture instructions

- Implement one intake workflow through three dependent milestones: validated
  parsing, atomic persistence, then the public import summary. Preserve AC-1–AC-3.
- Source ownership is limited to `parser.py`, `store.py`, and `service.py`.
  `operator_notes.md` contains a preexisting uncommitted user change: preserve it
  byte-for-byte. Do not change tests, instructions, manifests, or git history.
- Run the existing named tests after each milestone and the full suite at the
  stable integration boundary. Use the discovered installed harness
  `scripts/verify_tests.py unittest` adapter with the native test arguments so
  empty runs cannot count as behavioral evidence. Commands remain subject to normal runtime
  permission review; do not bypass sandbox/permissions to obtain evidence.
- Continue to the next ready milestone without asking for a new prompt. Follow
  the harness research, subagent implementation, independent review and
  verification contracts. Report blocked or skipped checks honestly.
- Use native progress artifacts when available; do not add workspace state files.
