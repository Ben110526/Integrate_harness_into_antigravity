---
name: harness-adr
description: Create or update an Architecture Decision Record from verified context, considered alternatives, consequences, and the repository's existing ADR convention.
---

# ADR workflow

1. Determine whether the user asked for an ADR artifact or only architectural advice. Remain read-only unless writing or updating an ADR was explicitly requested.
2. Read repository instructions and discover the existing ADR directory, template, numbering, filename, status vocabulary, date format, and cross-link conventions. Follow them rather than imposing a new standard.
3. Gather evidence for the decision context: the problem and constraints, decision drivers, relevant system boundaries, chosen option, credible alternatives actually considered, and known operational, security, data, cost, and migration implications. Do not invent debate or consensus that did not occur.
4. Draft the smallest complete record. Preserve the local structure; when none exists, use `docs/adr/` and a concise title plus `Status`, `Context`, `Decision`, `Options considered`, and `Consequences`, separating positive, negative, and unresolved consequences where helpful.
5. Mark proposals as proposed and accepted decisions as accepted only when the user or repository evidence establishes that status. Do not silently supersede, renumber, or rewrite an existing decision; link and explain supersession when explicitly authorized.
6. Keep implementation detail proportional to the durable decision. Link to stable repository evidence when useful, avoid transient chat history, and never include credentials, private data, or unsupported future guarantees.
7. If writing was requested, select the next identifier only after rechecking current files, write only the ADR and explicitly assigned index links, and run available documentation checks. Do not commit, push, publish, or notify stakeholders implicitly.
8. Report the path, status, decision and alternatives captured, evidence or assumptions, and any unresolved owner decision.
