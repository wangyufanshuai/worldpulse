# ADR-0004: provider-free multi-tick Kernel shadow event log

Status: accepted for Phase 2 contract implementation

## Context

Kernel V2 can project a completed War Room run, compile a canonical terminal
transition and replay it. It does not yet expose an append-only multi-tick event
chain or checkpoint cadence. The legacy deterministic engine already emits a
versioned timeline, but it does not retain country or supply-chain snapshots at
every timeline point. Inventing or interpolating those numeric values would
create a second authority and violate the V2 program.

The existing public boundaries provide the required truthful inputs:

- `WorldModelApplicationPort.war_room_presets()` returns the initial country and
  supply-chain catalog;
- `SimulationRuntimeApplicationPort.run_war_room()` returns the authoritative
  resolved scenario, deterministic timeline and final numeric state.

## Decision

Add a provider-free, post-execution shadow event-chain adapter without changing
the production runtime.

1. The initial `WorldState` uses the public World Model preset bundle, the
   resolved scenario, the pinned run/seed/Rule Pack metadata and the existing
   day-zero deterministic timeline observation.
2. Intermediate ticks append only the timeline prefix already emitted by the
   legacy engine. Country risk and supply-chain pressure remain at their initial
   catalog values. WorldPulse does not interpolate or infer missing per-tick
   numeric-authority values.
3. The final tick atomically transitions to the existing `WarRoomRun` projection.
   Its final `WorldState` hash must equal the standalone projection hash exactly.
4. A `KernelEventLog` stores ordered compiled transitions. It validates contiguous
   event sequence, strictly increasing tick, run id, input/output state-hash
   chaining, delta hash linkage and the declared final state hash.
5. An initial checkpoint is always created. Additional checkpoints are created
   only at the legacy timeline's declared turning points. Each checkpoint pins
   the prior checkpoint hash and event cursor; the final checkpoint must pin the
   final projected state.
6. Replay consumes the stored initial snapshot and event/delta pairs only. It
   never invokes a Provider, World Model connector, database or wall clock.

The chain is explicitly a shadow trace of the current deterministic engine, not
a claim that WorldPulse already has country-level reducers for every timeline
tick. Future native reducers must introduce their own versioned Delta contracts
and Golden gates.

## Compatibility and gates

The slice is accepted only when:

- all existing Golden Scenario hashes remain byte-for-byte unchanged;
- every Golden fixture produces a valid Event Log whose replay hash equals its
  standalone final projection hash;
- event ids, Event Log hash and Checkpoint hashes are deterministic across runs;
- malformed day-zero, duplicate/non-monotonic ticks, preset topology mismatch,
  event sequence gaps and checkpoint-parent mismatches fail closed;
- Agent/Provider/storage imports are absent from the shadow adapter;
- numeric-authority changes occur only in the final deterministic reducer Delta;
- the existing HTTP, lifecycle, artifact, database and frontend contracts remain
  unchanged;
- measured multi-tick build and replay latency is reported as diagnostic evidence,
  not promoted to a production performance claim.

## Consequences

Positive:

- Event Log and checkpoint behavior become executable contracts rather than a
  future architecture diagram;
- the existing timeline gains provider-free, hash-linked replay semantics;
- missing per-tick authority data remains explicit instead of being fabricated.

Costs:

- the final Delta is intentionally larger because the legacy engine exposes only
  a terminal country/supply-chain snapshot;
- the event chain is built after deterministic execution and is not yet persisted;
- lifecycle and persistence integration remain gated behind compatibility and
  representative performance evidence.

## Rejected alternatives

- Interpolating country risk or supply-chain pressure between day zero and final:
  this would introduce unapproved numeric formulas.
- Reading private `war_room.data` catalogs from the Kernel: the public World Model
  port already owns that boundary.
- Persisting shadow artifacts in this slice: Event Log correctness and cost must
  be proven before production lifecycle writes change.
- Calling an Agent Provider during replay: replay remains stored-only and
  fail-closed.
