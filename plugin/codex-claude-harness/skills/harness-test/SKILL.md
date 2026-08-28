---
name: harness-test
description: Discover and run the right verification ladder for a change or repository, then explain failures precisely.
---

# Test workflow

1. Discover existing project commands from manifests, CI configuration, and repository instructions.
2. Build a verification ladder: reproduction or focused test, affected package suite, lint/type check, build, then broader integration checks as justified.
3. Run independent long checks concurrently when safe and when they do not compete for the same mutable resources.
4. Record exact commands and exit results; preserve the useful failure excerpt.
5. Separate product regressions from environment failures or known pre-existing failures using evidence.
6. Do not edit product code unless the user asked for fixes; never conceal a failed check.
7. Return a compact pass/fail/skipped matrix and residual risk.
