---
name: harness-migration
description: Plan or execute a major framework, language, runtime, build-tool, or dependency migration using compatibility evidence, staged change slices, rollback points, and verification gates.
---

# Migration workflow

1. Read repository instructions and inventory the current and target versions, runtime and platform constraints, package managers and lockfiles, public interfaces, deployment topology, and existing verification commands.
2. Establish a passing pre-migration baseline. Record unrelated failures separately; do not let a version change hide them.
3. Consult version-matched authoritative release notes, migration guides, and compatibility tables when local evidence is insufficient. Build a compatibility matrix covering the runtime, framework, compiler or bundler, direct dependencies, plugins, test tools, deployment images, and supported clients. Mark unknowns explicitly.
4. Enumerate breaking changes and classify them as source, behavior, data/schema, build, configuration, deployment, or operational compatibility risks. Identify deprecated bridges, minimum-version changes, and irreversible steps.
5. Produce ordered, independently verifiable change slices. Each slice names its scope, prerequisites, observable acceptance checks, compatibility with the preceding and following state, rollback point, and whether it can be a separate PR. Prefer preparatory compatibility changes before the version bump and cleanup only after the new path is proven.
6. If implementation was requested, execute only the currently authorized slice with the repository's normal tools and the smallest coherent diff. Do not create branches, PRs, commits, tags, pushes, releases, dependency updates, or deployments implicitly.
7. At every slice, run targeted correctness checks before broader lint, type, build, integration, and deployment-equivalent checks. Verify both upgraded behavior and any promised compatibility path.
8. Finish with the completed slices, remaining matrix gaps, exact verification evidence, rollback instructions, and the next safe slice. Never claim a migration complete while required runtime, data, or deployment checks remain untested.
