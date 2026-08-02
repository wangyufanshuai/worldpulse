# ADR-0006: opt-in Kernel shadow Artifact with pinned rollout and rollback

Status: accepted implementation contract; production default remains off

## Context

ADR-0004 establishes a provider-free, hash-linked Kernel shadow run over the
legacy deterministic timeline. ADR-0005 then passes the precommitted local
Lifecycle gate: shadow construction p95 is below 15 ms and the combined
temporary-SQLite lifecycle p95 remains within 1.15 times the control p95.

That evidence is necessary but not sufficient for persistence. A production
Artifact adds serialization, storage, recovery, Replay Pack and rollout
semantics. Integrating it without a versioned envelope would leave the stored
`war_room_result`, Kernel Event Log and final `WorldState` related only by
convention. Reading a process-wide feature flag at execution time would also
allow retry behavior to change after a worker restart.

The existing Run Control Plane already supplies the required compatible
mechanisms:

- jobs pin a seed, Rule Pack hash and `runtime_profile_hash`;
- the generic Artifact store supports versioned, content-addressed payloads
  without a database migration;
- completed step checkpoints retain Artifact references and validate their
  storage SHA-256 before recovery;
- Replay Pack can carry a verified map of lifecycle Artifacts without invoking
  a Provider.

## Decision

Introduce one default-off, opt-in Artifact named `kernel_shadow_run` with
schema `kernel-shadow-artifact.v1`.

### Versioned envelope and lineage

The Artifact envelope contains:

- `baseline_scope = deterministic_pre_agent`;
- lifecycle run id, seed and pinned Rule Pack hash;
- source Artifact type, schema version and storage SHA-256;
- canonical deterministic source-run hash;
- the immutable `WarRoomShadowRun` payload;
- shadow-run, Event Log and final WorldState hashes.

Construction must verify the complete chain:

```text
war_room_result Artifact SHA-256
  -> canonical deterministic source-run hash
  -> KernelShadowArtifact
  -> WarRoomShadowRun hash
  -> KernelEventLog hash
  -> final WorldState hash
```

The envelope is a Simulation Kernel contract and contains no Run Control
repository, database or Provider dependency. Run Control owns feature-policy
pinning and persistence.

For `hybrid` and `negotiation` jobs the Artifact describes only the
deterministic result produced before Agent proposals, negotiation or Action
Adapter processing. It must never claim to be the post-Agent final result.

### Pinned opt-in policy

`WORLDPULSE_KERNEL_SHADOW_ARTIFACTS` accepts strict boolean values. Missing,
empty or false values leave current behavior unchanged; an unrecognized value
fails job creation rather than silently enabling or disabling persistence.

When enabled, job creation writes a versioned internal policy containing the
enabled state, Artifact schema and fixed byte limit into the existing
`runtime_profile`. The existing `runtime_profile_hash` therefore pins the
decision before queueing. Callers cannot set or override the reserved policy
key. Jobs created before enablement remain off; jobs already pinned on remain on
across retries and worker restarts.

This pinning deliberately favors reproducibility over an instantaneous global
kill switch. Emergency rollback disables new opt-ins and cancels or drains
already-pinned queued jobs before workers restart.

### Lifecycle integration

When the pinned policy is on, the existing `deterministic_run` step performs the
following actions after storing `war_room_result` and before any Agent work:

1. build and internally replay the provider-free shadow run;
2. verify source Artifact SHA, source-run hash, run id, seed, Rule Pack hash,
   Event Log hash, final state hash and envelope hash;
3. serialize the envelope and enforce the fixed size limit before writing;
4. persist exactly one `kernel_shadow_run` Artifact;
5. append one `SNAPSHOT` lifecycle event containing only hashes, Artifact id,
   byte size and measured integration duration.

Any enabled-path configuration, construction, lineage, size or persistence
failure fails the active attempt before consistency evaluation, report
generation or projection into `research_runs`. Retry uses normal Run Control
semantics. Failed-attempt Artifacts cannot become the latest trusted input.

Checkpoint recovery must revalidate the internal Kernel envelope and its source
`war_room_result`, not merely the outer database SHA-256.

### Replay Pack behavior

For an opt-in run, Replay Pack may add the verified `war_room_result` and
`kernel_shadow_run` to its existing lifecycle Artifact map. Export must verify
both storage hashes, the envelope source link and stored-only Event Log replay.
Default-off deterministic Replay Packs and all existing public response schemas
remain unchanged.

### Storage and performance budgets

The limits are fixed before implementation measurement:

- serialized UTF-8 `kernel_shadow_run` content must be at most **524,288
  bytes** per lifecycle run;
- Kernel build, envelope validation, serialization and SQLite Artifact write
  p95 must be at most **100 ms**;
- stored envelope validation plus provider-free replay p95 must be at most
  **20 ms**;
- opt-in combined lifecycle p95 must be at most **1.15 times** the default-off
  control lifecycle p95;
- the opt-in path adds exactly one Artifact and one audit event, with no table,
  migration or OpenAPI change.

The representative evidence run uses a new temporary SQLite database, 3
unreported warmup pairs and 30 alternating control/opt-in pairs with identical
scenario, seed and Rule Pack inputs. p95 uses nearest rank. Thresholds may not
be relaxed after observing results.

## Compatibility and acceptance gates

This slice is accepted only when:

- default-off lifecycle Artifact types/counts, events, result hashes and Replay
  Pack behavior remain unchanged;
- enabled jobs pin the policy in `runtime_profile_hash` and cannot be changed by
  later environment edits or caller-supplied reserved keys;
- deterministic, mock-agent, controlled-agent, hybrid and negotiation jobs all
  identify the Artifact as `deterministic_pre_agent`;
- corrupt source links, nested hashes, Event Logs, checkpoints, oversized
  payloads and invalid configuration fail closed;
- checkpoint recovery and Replay Pack perform stored-only validation without a
  Provider call;
- existing Golden Scenario hashes remain byte-for-byte unchanged;
- the precommitted storage/performance budgets pass;
- backend, frontend, migration, OpenAPI, E2E, boundary, security and release
  gates pass.

No database migration, new HTTP route, response-model field, numeric formula,
Agent capability or default deployment behavior is authorized by this ADR.

## Implementation and measurement evidence

The implementation keeps the environment default off and pins an enabled
policy into the existing hashed job runtime profile. The stored envelope links
the exact `war_room_result` storage SHA-256 to the canonical deterministic run,
Event Log and final WorldState hashes. Checkpoint recovery and Replay Pack both
execute the stored-only verifier. The optimized verifier checks the raw
checkpoint snapshots against Event Log output hashes, applies every stored
deterministic Delta and constructs the final immutable WorldState once. All 11
Golden fixtures prove that this replay result equals the full Kernel contract
replay.

The accepted precommitted evidence run used 3 unreported warmup pairs and 30
alternating default-off/opt-in pairs on Windows Python 3.11.15 with SQLite
3.53.1:

| Segment | Median | p95 | Fixed limit |
|---|---:|---:|---:|
| Default-off lifecycle | 1578.15515 ms | 1931.9307 ms | reference |
| Opt-in lifecycle | 1610.82965 ms | 1865.8637 ms | 1.15x control p95 |
| Build, serialize and persist | 44.31165 ms | 70.2519 ms | 100 ms |
| Stored validation and replay | 8.0143 ms | 11.6471 ms | 20 ms |

The serialized Artifact was exactly `89,772` bytes in every sample, below the
`524,288` byte limit. Opt-in/control lifecycle p95 was `0.965803`, below
`1.15`. As in ADR-0005, a ratio below one reflects independent cohort tail
variance and is not a performance-improvement claim. The opt-in path added
exactly one Artifact and one event; migrations remained 10 and tables remained
83; the temporary database was removed and configured paths and flags were
restored.

Earlier runs were deliberately rejected rather than rounded or used to relax
the gate. Stored validation/replay p95 was first `28.1638 ms`, then `20.1830
ms`, and then `25.6598 ms`. Those failures drove checkpoint-state
deduplication and exposed a benchmark defect: `repository.get_job()` was being
evaluated after the replay timer started even though the methodology excluded
stored lookups. Moving that lookup before the timer aligned implementation with
the precommitted segment definition; the threshold and validation work did not
change.

This evidence accepts the default-off opt-in implementation for local SQLite.
It does not enable the feature by default and is not PostgreSQL capacity
evidence.

## Rollback

1. Set `WORLDPULSE_KERNEL_SHADOW_ARTIFACTS=0` so newly created jobs retain the
   historical seven-Artifact deterministic profile.
2. Drain or cancel jobs whose hashed runtime policy already pins the feature on.
3. Existing `kernel_shadow_run` rows remain immutable audit evidence and are
   readable through the generic Artifact and Replay Pack paths; rollback never
   deletes lineage.
4. Reverting the integration code requires no schema downgrade. Older code
   ignores the additive generic Artifact type.

## Consequences

Positive:

- Kernel replay becomes a durable, source-linked research Artifact rather than
  an in-memory diagnostic;
- rollout decisions remain reproducible across worker leases and retries;
- default behavior and database contracts remain reversible without migration;
- deterministic baseline state stays distinct from controlled Agent outcomes.

Costs:

- one opt-in Artifact duplicates some deterministic result data to make replay
  self-contained;
- already-pinned queued jobs must drain or be cancelled during emergency
  rollback;
- local SQLite evidence still does not establish PostgreSQL capacity.

## Rejected alternatives

- Enabling persistence by default after ADR-0005: the earlier gate does not
  measure serialization, storage, recovery or Replay Pack behavior.
- Reading the environment only inside the worker: retries could change behavior
  after deployment configuration drift.
- Storing only an Event Log hash: offline replay would not be self-contained.
- Treating hybrid or negotiation final state as deterministic Kernel authority:
  that would collapse the Agent/Action Adapter boundary.
- Adding a dedicated table: the generic versioned Artifact store already owns
  this lifecycle data and provides rollback without migration.
- Deleting Artifacts on rollback: immutable lineage is evidence, not disposable
  cache.
