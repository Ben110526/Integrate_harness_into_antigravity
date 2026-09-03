---
name: harness-clarify
description: Resolve a genuinely blocking, material engineering decision through evidence first and one bounded user choice when the answer cannot be discovered safely.
---

# Clarification workflow

1. State the exact decision and why different answers would materially change product behavior, architecture, security, data, cost, or an irreversible action. Do not manufacture ambiguity or ask about a preference that existing evidence can resolve.
2. Exhaust the smallest relevant evidence set first: the user's request; repository instructions and public contracts; tests and types; call sites and current behavior; version-matched authoritative documentation; then the cheapest safe discriminating check. Record what remains `[UNRESOLVED]`.
3. Ask only when the material choice is still undiscoverable. The parent or main agent uses native `ask_question`; background subagents never call it, ask the user directly, or wait for an answer.
4. Present one concise decision at a time, normally with two or three mutually exclusive options phrased as direct answers. Put an evidence-backed recommendation first and prefix it `(Recommended)`; otherwise do not claim a recommendation. Do not number options or add an `Other` option when the runtime already provides numbering and write-in. Default to single-select; use multi-select only when the choices are genuinely independent and may safely be combined.
5. Never use this workflow for tool permissions, OAuth or authentication, requesting or exposing credentials or secrets, or approval of a destructive action. Use the platform's dedicated approval or authentication flow instead.
6. If `ask_question` is unavailable, the session is headless, or the prompt is cancelled, ask the same decision once in the normal final response. Do not loop, rephrase repeatedly, infer consent, or silently choose an irreversible or materially different outcome.

When a background subagent encounters such a blocker, it returns this compact handoff to the parent and continues any work that does not depend on the answer:

```text
[UNRESOLVED] <decision>
Evidence: <what was checked and why it does not decide the issue>
Options: <2-3 mutually exclusive choices with concrete tradeoffs>
Recommendation: <evidence-backed option, or "none">
```
