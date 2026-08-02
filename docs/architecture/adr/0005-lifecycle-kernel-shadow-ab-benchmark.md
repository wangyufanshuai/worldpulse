# ADR-0005: temporary-SQLite Lifecycle A/B gate for Kernel shadow processing

Status: accepted measurement contract; production path unchanged

## Context

ADR-0004 proves that the legacy deterministic timeline can be represented as a
provider-free, append-only Kernel Event Log and replayed to the existing final
`WorldState` hash. Its microbenchmark measures pure in-memory work, but it does
not establish the cost relative to a real Run Control Plane lifecycle. The
multi-tick shadow path therefore remains ineligible for production persistence
or executor integration.

The next decision needs representative evidence without changing the behavior
being measured. WorldPulse already has the required public and compatibility
boundaries:

- `RunControlApplicationPort.create_job()` creates a job with a pinned seed and
  Rule Pack hash;
- `RunControlApplicationPort.process_one_queued_job()` executes the existing
  deterministic lifecycle and SQLite Artifact writes;
- `RunArtifactStorePort.get_latest_artifact_content()` exposes the stored
  `war_room_result` through the Run Control boundary;
- `WorldModelApplicationPort.war_room_presets()` supplies the public day-zero
  World Model input required by the shadow adapter.

Measuring through those boundaries is stronger evidence than another engine
microbenchmark while keeping the production executor untouched.

## Decision

Add a standalone Lifecycle A/B benchmark with the following precommitted
methodology.

1. Every invocation creates a new temporary directory and SQLite database,
   applies the real migrations and restores the caller's configured database
   path on exit. It must never read or write the normal WorldPulse database.
2. The benchmark creates one project and interleaves control and treatment jobs
   with the same deterministic scenario, seed and pinned Rule Pack. Only one job
   is queued when the worker is invoked, so the timed execution is unambiguous.
3. Each control sample measures only
   `process_one_queued_job()` from worker claim through completed lifecycle.
4. Each treatment sample separately measures the same lifecycle call and the
   in-memory `build_war_room_shadow_run()` post-processing of its stored
   `war_room_result`. The paired combined sample is the sum of those two timed
   segments. Artifact lookup, validation and benchmark assertions are excluded
   from the timed shadow segment.
5. Control-first and treatment-first pair order alternates to reduce systematic
   warm-cache and database-growth bias. Three unreported pairs warm the runtime;
   the default evidence run contains 30 measured pairs.
6. Median and p95 use the raw per-job samples. p95 is the nearest-rank value
   `ceil(0.95 * n)` after ascending sort; ratios are computed from unrounded
   values and only presentation is rounded.
7. Before and after shadow construction, the treatment run's complete Artifact
   identity, type, schema, content hash and count must be identical. The shadow
   result must replay to its declared final state and use the job's pinned
   run id, seed and Rule Pack hash.
8. The benchmark emits machine-readable JSON containing environment metadata,
   methodology, sample counts, median/p95 measurements, absolute and relative
   overhead, gate outcomes and an overall pass/fail decision. It exits non-zero
   only for contract/integrity failures; a correctly measured performance-gate
   miss is evidence, not a broken benchmark.

The performance gate is fixed before measurement:

- shadow post-processing p95 must be at most **15 ms**; and
- combined lifecycle p95 must be at most **1.15 times** the control lifecycle
  p95.

Both conditions must pass. The limits must not be relaxed after observing a
result. A later threshold change requires a new ADR with independent product or
capacity evidence, not merely a failing measurement.

## Compatibility and validation gates

This slice is accepted only when:

- the benchmark proves it used an isolated temporary SQLite path;
- every measured control and treatment lifecycle completes successfully;
- every job pins the requested seed and a non-empty Rule Pack hash;
- treatment Artifact manifests are byte-for-byte unchanged by shadow work;
- the stored final result and shadow replay retain the existing deterministic
  hash lineage;
- the benchmark itself has focused tests for statistics, isolation, Artifact
  invariance and performance-gate reporting;
- existing lifecycle, Kernel, Golden, HTTP, migration, OpenAPI, frontend and
  release gates remain unchanged.

No Kernel Artifact, schema, API, lifecycle event or database migration may be
added in this measurement slice.

## Consequences

Positive:

- the integration decision will be based on the real lifecycle and storage
  shape rather than a pure engine ratio;
- the benchmark is repeatable, non-destructive and explicit about which costs
  are and are not timed;
- a performance miss cannot silently alter production persistence or public
  contracts.

Costs:

- local SQLite p95 is development-host evidence, not a PostgreSQL production
  capacity claim;
- control and treatment are separate jobs, so alternating order and multiple
  samples reduce but cannot remove host scheduling noise;
- Artifact retrieval is validated but excluded from combined timing because an
  eventual in-executor integration already owns the in-memory deterministic
  result. Any out-of-process design would need its own end-to-end gate.

## Follow-up decision

If both precommitted limits pass, the next slice may propose a separate ADR for
an opt-in shadow Artifact and lifecycle integration, including rollback and
storage budgets. Passing this benchmark does not itself authorize persistence.

If either limit fails, production behavior remains unchanged. The next work is
profiling and optimization of the in-memory shadow adapter, followed by a rerun
under this unchanged contract.

## Rejected alternatives

- Timing only `run_war_room()`: it does not represent the lifecycle against
  which the overhead budget is defined.
- Patching `executor.py` before measuring: it changes the production path and
  Artifact behavior before the gate is known.
- Persisting the Event Log to obtain a “realistic” number: storage schema and
  write amplification are separate decisions that require their own ADR.
- Comparing a single baseline run with a single shadow run: it is too sensitive
  to migration, import, cache and scheduler noise.
- Adjusting the ratio after observing local results: that would invalidate the
  precommitment and turn the gate into a post-hoc justification.
