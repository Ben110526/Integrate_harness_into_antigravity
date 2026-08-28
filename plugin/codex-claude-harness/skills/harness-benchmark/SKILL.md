---
name: harness-benchmark
description: Design and run reproducible latency, throughput, CPU, or memory benchmarks with a correctness baseline, controlled environment, repeated measurements, and honest before-and-after reporting.
---

# Benchmark workflow

1. Define the optimization hypothesis, workload, metric and unit, success threshold, expected bottleneck, and non-goals. A benchmark measures a specific claim; it is not a general proof of performance.
2. Establish correctness with the relevant tests before measuring. Validate benchmark outputs so a faster result cannot come from skipped work, changed semantics, caching mistakes, or error paths. Benchmarks never replace correctness, integration, or regression tests.
3. Prefer the project's established benchmark or profiler framework. If a new harness was requested, keep it deterministic, representative, reviewable, and isolated from production systems and sensitive data.
4. Record the environment needed for comparison: commit or diff state, runtime and dependency versions, build mode and flags, hardware or resource limits, operating system, concurrency, dataset shape and size, cache state, and important services. Do not compare results collected under materially different environments without labeling the limitation.
5. Separate setup from the measured region. Include warm-up appropriate to the runtime, then enough independent repetitions to expose variability. Avoid hidden network dependencies, background load, debug builds, dead-code elimination, unrealistic microbenchmarks, and reuse of mutated state between samples.
6. Capture raw samples or a repository-appropriate reproducible artifact. Report sample count, central tendency, dispersion or range, outliers and handling, and absolute as well as relative change. Do not claim statistical or practical significance beyond the evidence.
7. For memory work, distinguish peak resident memory, allocations, retained memory, and leaks. For concurrency or throughput, state queueing, saturation, error rate, and latency percentiles rather than reporting throughput alone.
8. Compare baseline and candidate with the same harness and environment, re-run correctness checks, and report regressions and tradeoffs alongside gains. Never load-test production, install profilers, change external systems, commit, push, or deploy unless separately authorized.
