# ADR-0003: deep-immutable Kernel state and safe hash memoization

Status: accepted for Phase 2 contract optimization

## Context

The first Kernel V2 shadow transition is correct and provider-free, but its
local diagnostic shows that transition compilation is dominated by repeated
canonical serialization and defensive deep copies. The current Pydantic
`frozen=True` setting prevents field reassignment but does not freeze nested
`dict` or `list` values. Caching a content hash while those values remain
mutable could return a stale hash and would violate replay integrity.

The measured 2026-08-02 baseline uses 100 iterations across 7 repeats on the
Windows Python 3.11 development runtime. The existing run plus Kernel shadow
median was about 2.6 times the legacy deterministic run. This is diagnostic
evidence only; the production path remains unchanged.

## Decision

Kernel contracts will make their entire value graph deeply immutable before
memoizing any content hash.

1. Dependency-free frozen mapping and sequence value objects recursively wrap
   every nested Kernel contract `dict` and `list`. Their JSON representation,
   equality behavior and canonical ordering remain compatible with the current
   contracts, while all mutating operations fail immediately.
2. Kernel `model_copy(update=...)` revalidates updated data instead of relying
   on Pydantic's unchecked update path. A changed copy receives a fresh private
   hash cache; an unchanged deep copy may reuse immutable values safely.
3. Content hashes are memoized only in private, non-serialized contract state.
   The canonical payload, SHA-256 algorithm, schema versions and public model
   dumps do not change. Concurrent duplicate computation is harmless because
   the result is deterministic.
4. `WorldState.apply_delta()` uses copy-on-write structural sharing. Unchanged
   immutable `Entity` instances are reused, changed entities receive new frozen
   component mappings, and the parent state remains byte-for-byte unchanged.
5. No cache or structural-sharing optimization may bypass run id, parent hash,
   tick, numeric-authority, topology, output-state or replay verification.

## Compatibility and gates

The optimization is accepted only when all of these hold:

- attempts to mutate top-level and deeply nested Kernel mappings/sequences fail;
- an updated model copy cannot reuse the source content hash;
- `model_dump(mode="json")` retains ordinary JSON dictionaries and lists;
- all existing Golden Scenario hashes remain unchanged;
- the shadow benchmark retains these pre-optimization lineage values:
  - source run: `a3ab67f74a9c8058f15ad96ac99c989f63471cb0b2eed5928f0eaee621ba0082`;
  - target WorldState: `64f037a297a81dda526808cbdd182e2b3d640426c84eb94eab7ce434a31751c5`;
  - compiled transition: `42431a1dfad849e3fc50002e3bf446a674495ea71ed3a83e27d5378f19c9c61c`;
- provider-free replay and checkpoint-parent immutability still pass;
- a repeated local diagnostic reports the measured result without converting a
  microbenchmark improvement into a production performance claim.

The Phase 2 production performance gate remains separate. It requires a
representative lifecycle/multi-tick budget after this in-memory hotspot is
addressed.

## Consequences

Positive:

- cached hashes become safe integrity data rather than an unsafe speed shortcut;
- copy-on-write transitions avoid repeated copying of unchanged state;
- Kernel objects better match the immutable snapshot semantics already stated
  by ADR-0002.

Costs:

- direct mutation of Kernel container values becomes a contract error; callers
  must create a new model or apply a verified Delta;
- custom frozen containers require focused serialization, deepcopy and typing
  tests;
- the optimization does not by itself prove lifecycle-scale performance.

## Rejected alternatives

- Memoizing hashes on shallow-frozen Pydantic models: nested mutation can make
  the cache stale.
- Removing defensive copies without freezing values: a branch could mutate its
  checkpoint parent.
- Changing canonical JSON, float precision or SHA-256 to gain speed: this would
  invalidate Golden, replay and evidence lineage.
- Adding a persistent-collection dependency before the contract is proven: the
  small dependency-free value objects are sufficient for this phase.
