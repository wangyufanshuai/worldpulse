# ADR-0002: deterministic Simulation Kernel V2 contracts behind the existing runtime

Status: accepted for Phase 2 contract implementation

## Context

WorldPulse now has a stable World Model and Simulation Runtime application
boundary, but the deterministic engine still represents a run as a single
function call. Phase 2 needs explicit state transitions so that checkpoint
branching, control/treated experiments and provider-free replay can be added
without changing the V1.12 numeric authority or the V1-v11 HTTP contracts.

The design may learn from the public concepts in Concordia, LEAN and OASIS:
explicit entities and components, a tick-based environment, event history,
checkpointable execution and separate Agent/social behavior. WorldPulse uses a
clean-room contract design only. No AGPL source, model prompt, provider
integration or implementation is copied into this MIT project.

## Decision

Introduce a small, provider-free Kernel contract behind the existing
`SimulationRuntimeApplicationPort`. The first implementation is additive and
must not replace the current engine formulas until the gates below pass.

### Canonical kernel objects

- `EntityId`: stable, opaque identifier for a country, supply chain, policy or
  other modeled participant.
- `Component`: versioned, typed value owned by one deterministic subsystem.
  Numeric authority components are written only by deterministic reducers.
- `WorldState`: immutable snapshot of sorted entities/components plus the
  pinned scenario, Rule Pack, evidence manifest and seed metadata.
- `StateDelta`: a typed set of deterministic changes with parent state hash,
  reducer version, allowed component paths and a canonical delta hash.
- `EventEnvelope`: append-only event with sequence, deterministic tick,
  event type, input/output hashes and artifact references.
- `Checkpoint`: immutable state plus event cursor, parent checkpoint hash,
  branch manifest and integrity hash. A branch never mutates its parent.
- `ReplayRequest`: checkpoint/branch identifier, event range, Rule Pack hash
  and provider policy. Replay fails closed if any pinned hash or event is
  missing or changed.

### Determinism rules

1. `DeterministicClock` is an integer tick/phase clock. Wall-clock time is
   metadata only and never enters a numeric result or a replay hash.
2. Every random operation uses a namespaced seed derived from the run seed,
   branch id, tick and reducer version. Iteration order is canonical and
   sorted by entity id/component key/event sequence.
3. State, delta, event and checkpoint hashes use the repository canonical JSON
   and SHA-256 primitives. Floats are normalized at the contract boundary;
   reducers retain their existing precision rules.
4. Agent proposals are observations/commands, not state writes. A proposal
   must pass the existing Consistency Evaluator and Action Adapter before a
   deterministic reducer can emit an admitted `StateDelta`.
5. Replay loads stored snapshots, deltas, events and artifacts only. It never
   invokes an Agent Provider, network connector or wall-clock-dependent code.

### Transition sequence

```text
prepare immutable WorldState
  -> emit run/branch event
  -> Agent/social observation (optional, untrusted)
  -> Consistency admission + Action Adapter
  -> deterministic reducer emits StateDelta
  -> apply delta and verify next state hash
  -> append EventEnvelope
  -> checkpoint at configured tick boundary
```

The existing Run Control lifecycle remains the orchestration boundary while
the Kernel contracts are introduced. Hybrid and negotiation continue to use
the mandatory Consistency, Commitment Ledger and Projection Audit paths.

### Branching and experiments

- A branch references an immutable parent Checkpoint and records the treatment
  manifest, control/treated label, seed namespace and scenario diff.
- Control and treated runs share an input/evidence manifest but receive
  distinct branch ids and seeds; no result is overwritten in place.
- Multi-seed execution is an orchestration concern. Each seed produces a
  separately hash-addressed replayable branch; aggregate metrics belong to
  Evaluation & Governance, not to the Kernel reducer.

## Invariants and gates

The contract implementation is accepted only when all of these hold:

- existing Golden Scenario hashes are byte-for-byte unchanged;
- deterministic, hybrid and negotiation paths can expose the same Kernel
  transition contract without changing their public responses;
- provider-free replay verifies state/event/checkpoint hashes and never calls a
  provider (a spy provider test is mandatory);
- attempts by Agent data to write numeric-authority component paths fail closed;
- a checkpoint branch can be created and replayed without mutating its parent;
- a measured performance test shows no material regression against the current
  production path.

## Consequences

Positive:

- Counterfactuals and replay become explicit data contracts rather than
  conventions hidden inside JSON blobs.
- Deterministic authority remains isolated from Agent behavior and providers.
- Kernel work can land in reversible slices while V1-v11 and current workers
  keep operating.

Costs:

- Transitional mappers will duplicate some existing run/artifact structures.
- The first contract layer does not by itself provide distributed execution;
  scale remains evidence-driven under ADR-0001.
- Existing Golden fixtures and replay artifacts become stricter compatibility
  gates, so malformed historical data must fail closed rather than be guessed.

## Rejected alternatives

- Replacing the current engine with a new simulator before hash/performance
  comparison: this would obscure numeric regressions.
- Letting Agent outputs mutate `WorldState` directly: it violates the existing
  authority and governance boundary.
- Importing Concordia/OASIS/LEAN implementation code or licenses: clean-room
  contracts and compatible concepts are sufficient and safer.
- Introducing Ray, Temporal, Redis or microservices at this stage: no measured
  bottleneck requires a deployment-model change.
