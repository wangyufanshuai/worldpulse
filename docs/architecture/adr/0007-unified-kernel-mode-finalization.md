# ADR-0007: unified Kernel mode finalization before report projection

Status: accepted implementation contract; production formulas and HTTP APIs unchanged

## Context

Phase 2 requires deterministic, hybrid and negotiation runs to pass through one
Simulation Kernel interface without collapsing the authority boundary between
the deterministic engine and controlled Agent behavior.

The current implementation has strong but separate chains:

- `SimulationKernelApplicationPort` compiles, applies, branches and replays
  deterministic state, but has no mode-completion contract;
- deterministic lifecycle execution uses the public Simulation Runtime port;
- hybrid execution verifies Consistency decisions, a deterministic Action
  Adapter bundle, a Projection Audit and provider-free replay, but does so
  outside the Kernel port;
- negotiation stores six rounds, message and state hash chains, Commitment
  Ledger snapshots, Action Adapter bundles and provider-free replay. The
  admission Consistency report is stored, but the current second, projection
  Consistency report is transient. Persisting and version-binding both reports,
  and closing per-tick Projection Audit cardinality, are implementation work
  required by this contract;
- `report_projection_manifest` proves only the final result hash and workspace
  compatibility. It does not state which governed authority path admitted that
  result.

A dispatch function that merely calls the three existing engines would be a
false unification: it would move Agent/provider and storage dependencies into
the deterministic Kernel. A post-hoc record that can be skipped before report
projection would be equally weak.

## Decision

Add a mandatory, pure `SimulationKernelApplicationPort.finalize_execution()`
gate. Every new lifecycle run must pass this gate after mode-specific execution
and governance, but before report generation and projection into
`research_runs`.

### Job-pinned execution contract and seed

The v2 contract is pinned at job creation inside the existing canonical
`runtime_profile` payload as
`execution_contract_version = "kernel-mode-execution.v2"`. The same payload
contains `effective_seed`, and both fields participate in the existing
`runtime_profile` hash. They are not new job columns, may not be rewritten when
a job is retried or recovered, and are checked before mode dispatch and again
before report persistence.

Job creation resolves the seed exactly once. It selects the top-level request
seed when that value is not `None` (so `0` is valid), otherwise
`scenario.seed` when that value is not `None`, otherwise the integer `42`.
Creation writes that one integer to both the stored job seed and the stored
scenario seed as well as to `runtime_profile.effective_seed`. Every mode,
Provider invocation, Run Control adapter, replay, Kernel request and projection
uses that pinned integer. Implementations must remove truthiness fallbacks such
as `seed or 42`; no later layer resolves or substitutes the seed independently.

### Pure Kernel contracts

Introduce immutable, versioned contracts:

- `KernelModeProofReference`: a complete typed Artifact envelope containing
  `proof_schema`, `artifact_type`, `schema_version`, `artifact_id`, `run_id`,
  `attempt`, nullable schema-governed `ordinal` and `tick`, the outer
  stored-Artifact `artifact_sha256`, the inner canonical-payload
  `content_hash`, immutable schema-specific `claims`, `claims_hash`, and an
  ordered `relationships` tuple. Each relationship is limited to the
  canonical `relationship_type`, `target_artifact_id`, `target_content_hash`
  and nullable `target_attempt` needed to connect that proof to its governed
  parent or subject. `target_attempt` is required only for the negotiation
  retry relationship `supersedes` and is forbidden for every other
  relationship; arbitrary metadata is not part of this contract;
- `KernelModeExecutionProof`: an ordered tuple of
  `KernelModeProofReference` values for Agent observations, Consistency audits,
  Action Adapter bundles, Commitment Ledgers, Projection Audits and
  provider-free replay manifests. Each proof schema fixes the exact category
  cardinalities and canonical reference order. Missing, duplicated, surplus or
  out-of-order references, invalid `ordinal`/`tick` sequences, and undeclared
  relationships are rejected;
- `KernelModeExecutionRequest`: the exact engine mode, normalized Kernel mode,
  pinned run/effective-seed/Rule Pack identity, the existing baseline and final
  `WarRoomProjection` envelopes, and the proof. It does not accept bare
  `WorldState` values or separately asserted result/state hashes;
- `KernelModeExecutionRecord`: the admitted compact lineage, authority path,
  projection hashes, proof hash and record hash.

`claims` is not a caller-selected metadata map. `proof_schema` selects one
closed record shape from the registry below, unknown or additional claim keys
fail validation, and every collection is an immutable tuple in the stated
order. Claim records use only strings, integers, booleans, `null` and tuples;
floating-point values are prohibited. IDs within a set-valued claim are
unique and ascending by UTF-8 byte order. Hashes are lowercase 64-character
SHA-256 values.

For this contract, canonical JSON is UTF-8 JSON with object keys sorted by
Unicode code point, no insignificant whitespace, no ASCII escaping and no
NaN/Infinity. `claims_hash` is exactly:

```text
sha256(canonical_json({"claims": claims, "proof_schema": proof_schema}))
```

`content_hash` applies the same canonical encoding to the complete parsed
Artifact payload. `artifact_sha256` remains the current Artifact-store digest
over the exact stored `content_json` UTF-8 bytes. These two hashes can be equal
when the stored representation is already canonical, but equality is neither
required nor used as a substitute for checking both scopes.

Run Control first recomputes `artifact_sha256` over the exact stored bytes,
validates the stored `artifact_type` and `schema_version`, parses and validates
the payload, and recomputes `content_hash`. It then runs the extractor selected
by `proof_schema`, compares the extracted record field-for-field with
`claims`, recomputes `claims_hash`, and checks every ordinary relationship
target against another outer-SHA-verified reference in the current proof. It
may not fill a missing payload fact from the Artifact envelope or from another
Artifact. A `supersedes` target is instead an outer-SHA-verified historical
Artifact from the same run and semantic round coordinate; Run Control checks
its exact `target_content_hash` and `target_attempt` before constructing the
current reference, but does not admit that historical Artifact into the final
proof. If an older payload version cannot expose a required claim, it is
insufficient for v2
finalization and Run Control must persist a versioned replacement under the
same generic `artifact_type`.

The pure Kernel receives no Artifact payload. It still recomputes every
`claims_hash` and validates claim types, tuple order, uniqueness, counts,
cross-reference relationships and their agreement with the baseline/final
projections. It does not infer proposal acceptance from an `audit_hash`, ledger
cardinality from a `ledger_hash`, modifier membership from a `bundle_hash`, or
replay semantics from a `replay_hash`. Those semantic facts must be explicit
claims authenticated against the canonical payload by Run Control; the Kernel
only compares the resulting typed facts and their hashes.

### Normative proof-schema registry

The `kp.*.v1` names below are new internal proof-extractor identifiers, not
claims that identically named payload schemas already exist. The
`artifact_type` column uses the current generic Artifact names exactly. The
stored `schema_version` is independently retained in the reference and must be
one of the listed, pinned source versions. Where the current source payload
lacks a required field, implementation must introduce an additive internal
payload version under that same `artifact_type`; it must not silently treat the
new `kp.*.v1` identifier as an existing stored schema.

| Token / proof schema | Exact `artifact_type`; pinned source-schema scope | Required claims extracted from the canonical payload |
|---|---|---|
| `AR` / `kp.agent-runtime.v1` | `agent_runtime_audit`; `agent-runtime-result.v1` or a reviewed additive successor | `run_id`, `runtime_hash`, ascending `proposal_ids`, `proposal_count`, ascending `invocation_ids`, `invocation_count` |
| `PB` / `kp.proposal-batch.v1` | `agent_action_proposals`; `mock-agent-batch.v1` for `mock_agent`, `agent-action-batch.v1` for the controlled/hybrid modes, or a reviewed additive successor | `run_id`, `source_kind`, `batch_hash` or `runtime_hash`, ascending `proposal_ids`, per-proposal canonical `proposal_hashes` in the same order, `proposal_count` |
| `FC` / `kp.final-consistency.v1` | `consistency_audit`; `consistency-audit.v1`, `consistency-audit.v2`, or a reviewed additive successor | `run_id`, fixed role `final`, `audit_hash`, `deterministic_result_hash`, ascending `proposal_ids`, ascending `accepted_proposal_ids`, `decision_count` |
| `RR` / `kp.negotiation-round.v1` | `negotiation_round`; `negotiation-round.v1` or the required additive successor | `run_id`, `session_id`, `round_id`, `tick`, `input_hash`, `output_hash`, `before_result_hash`, `after_result_hash`, ascending `proposal_ids`, ascending `accepted_proposal_ids`, `admission_audit_hash`, nullable `projection_consistency_hash`, nullable `modifier_bundle_hash`, `diffusion_hash`, `ledger_hash`, nullable `projection_audit_hash`, nullable `no_projection_reason` |
| `AC` / `kp.negotiation-admission-consistency.v1` | `consistency_audit`; a pinned `consistency-audit.v1`/`.v2` source only when it losslessly supplies these claims, otherwise an additive successor | `run_id`, fixed role `admission`, `tick`, `audit_hash`, `deterministic_result_hash`, ascending `proposal_ids`, ascending `accepted_proposal_ids`, `decision_count` |
| `PC` / `kp.negotiation-projection-consistency.v1` | `consistency_audit`; a pinned `consistency-audit.v2` source only when it losslessly supplies these claims, otherwise an additive successor | `run_id`, fixed role `projection`, `tick`, `audit_hash`, `deterministic_result_hash`, ascending `candidate_proposal_ids`, ascending `accepted_proposal_ids`, `decision_count` |
| `MB` / `kp.action-modifier-bundle.v1` | `deterministic_action_modifiers`; `hybrid-modifier-bundle.v1` or a reviewed additive successor | `run_id`, nullable `tick`, `bundle_hash`, `consistency_audit_hash`, ascending `accepted_proposal_ids`, uniquely lexicographically ordered by UTF-8 bytes of `(proposal_id, modifier_id, modifier_hash)` `modifier_tuples`, `modifier_count` |
| `ND` / `kp.narrative-diffusion.v1` | `narrative_diffusion`; `narrative-diffusion.v1` or a reviewed additive successor | `run_id`, `tick`, `attempted`, `diffusion_hash`, `application_count`, ascending `proposal_ids`, `before_result_hash`, `after_result_hash` |
| `CL` / `kp.commitment-ledger.v1` | `commitment_ledger`; `commitment-ledger.v1` or a reviewed additive successor | `run_id`, nullable `tick`, `ledger_hash`, `ledger_entry_count`, ascending `(commitment_id, commitment_hash, status)` tuples |
| `PA` / `kp.projection-audit.v1` | `agent_action_projection_audit` outside negotiation and `negotiation_projection_audit` in negotiation; `agent-action-projection-audit.v1` or a reviewed additive successor | `run_id`, nullable `tick`, `projection_mode`, `audit_hash`, `consistency_audit_hash`, nullable `modifier_bundle_hash`, ascending `proposal_ids`, ascending `projected_proposal_ids`, immutable `modifier_tuples` uniquely lexicographically ordered by UTF-8 bytes of `(proposal_id, modifier_id, modifier_hash)` (always present and possibly empty; required empty for `audit_only`), `modifier_count`, `record_count`, `before_result_hash`, `final_result_hash` |
| `HR` / `kp.hybrid-replay.v1` | `hybrid_replay_record`; `hybrid-replay-record.v1` only when it losslessly supplies these claims, otherwise a reviewed additive successor | `run_id`, `replay_hash`, `baseline_result_hash`, pre-`hybrid_trace` `final_result_hash`, persisted traced `full_source_run_hash`, `consistency_audit_hash`, `modifier_bundle_hash`, `projection_audit_hash`, `ledger_hash`, ascending `accepted_proposal_ids` |
| `NR` / `kp.negotiation-replay.v1` | `negotiation_replay`; `negotiation-replay.v1` or a reviewed additive successor | `run_id`, `session_id`, `replay_hash`, `baseline_result_hash`, `final_result_hash`, ordered `round_hashes`, ordered `admission_audit_hashes`, ordered nullable `projection_consistency_hashes`, ordered `diffusion_hashes`, ordered `ledger_hashes`, ordered nullable `projection_audit_hashes`, `message_chain_head`, `provider_calls_required` |

For all `*_hashes` tuples, "ordered" means tick order, preserving a `null`
slot for a tick at which that proof category is forbidden. `proposal_count`,
`decision_count`, `modifier_count`, `application_count`,
`ledger_entry_count`, `record_count` and `invocation_count` must equal the
length of their corresponding tuple, not merely repeat a payload counter. For
`PA`, `modifier_count` must equal the length of its immutable
`modifier_tuples` claim (zero when that tuple is empty, including every
`audit_only` PA), and `record_count` must
equal the length of `proposal_ids`. The extractor recomputes each
payload-defined `audit_hash`, `bundle_hash`,
`ledger_hash`, `diffusion_hash` or `replay_hash` over that source schema's
declared preimage before exposing it as a claim.

### Normative six-mode proof matrix

Let `N` be `PB.proposal_count`; let `A = 1` when `N > 0` and `0` otherwise.
For negotiation, `T = 6`, and `p[t] = 1` exactly when tick `t` contains at
least one accepted proposal or a narrative-diffusion projection attempt;
otherwise `p[t] = 0`. Let `P = sum(p[1..T])`. Brackets denote references in
ascending tick order, and a filtered bracket contains only ticks for which the
predicate is true.

`ordinal` is the zero-based position of a reference in the complete sequence
shown below, with no gaps or reset between categories. Non-negotiation
references have `tick = null`. Negotiation `RR`, `AC`, `PC`, `MB`, `ND`, `CL`
and `PA` references have the indicated integer tick in `1..6`; `FC` and `NR`
have `tick = null`. Here `attempt` means the exact `attempt_id` of the current
successful job attempt, not a retry count or an earlier attempt from which work
was recovered. Every reference in the final proof has that current attempt
identity. A missing, duplicated, surplus or out-of-order reference, including
a valid reference placed in the wrong category, fails finalization.

| Existing engine mode | Canonical reference sequence and exact count | Required relationship targets, in tuple order | Zero-proposal / no-audit rule |
|---|---|---|---|
| `deterministic` | `FC` (1) | `FC`: none | No `PB`, `AR`, `MB`, `CL`, `PA` or replay reference is allowed. `FC.proposal_ids` and accepted IDs are empty; baseline and final source/state hashes are identical. |
| `mock_agent` | `PB, FC, PA[if A]` (`2 + A`) | `PB`: none; `FC`: `evaluates -> PB`; `PA`: `covers -> PB`, `governed_by -> FC` | `N = 0` requires `FC.decision_count = 0` and forbids `PA`. `N > 0` requires exactly one audit-only `PA`, with `record_count = N`, no projected IDs and baseline equal to final. |
| `controlled_agent` | `AR, PB, FC, PA[if A]` (`3 + A`) | `AR`: none; `PB`: `generated_by -> AR`; `FC`: `evaluates -> PB`; `PA`: `covers -> PB`, `governed_by -> FC` | `AR.proposal_ids = PB.proposal_ids`. `N = 0` requires zero decisions and forbids `PA`; `N > 0` requires exactly one audit-only `PA`, with no projected IDs and baseline equal to final. |
| `hybrid` | `AR, PB, FC, MB, CL, PA, HR` (7) | `AR`: none; `PB`: `generated_by -> AR`; `FC`: `evaluates -> PB`; `MB`: `maps -> PB`, `admitted_by -> FC`; `CL`: `ledger_for -> MB`; `PA`: `covers -> PB`, `governed_by -> FC`, `audits -> MB`, `ledger_snapshot -> CL`; `HR`: `observations -> PB`, `governed_by -> FC`, `replays -> MB`, `ledger_snapshot -> CL`, `audit -> PA` | All seven references remain required when `N = 0` or no proposal is accepted, and `CL.ledger_entry_count` is always zero. When `N = 0`, all proposal/decision/modifier/audit-record tuples are empty. When proposals exist but none is accepted, `PB`, `FC` and `PA` still cover those proposals while accepted/projected/modifier tuples are empty, `MB.modifier_count = 0`, and baseline equals final. A `PA` numeric no-op is still required. |
| `hybrid_recorded` | `AR, PB, FC, MB, CL, PA, HR` (7) | Exactly the `hybrid` target list; `HR` must additionally be the stored-only replay selected by this engine mode, as stated by its source payload and replay claim | Exactly the `hybrid` zero-proposal rule. An online execution transcript or a recomputed digest cannot replace `HR`. |
| `negotiation` | `RR[1..T], AC[1..T], PC[t where p[t]=1], FC, MB[t where p[t]=1], ND[1..T], CL[1..T], PA[t where p[t]=1], NR` (`4T + 3P + 2 = 26 + 3P`) | `RR[t]`: `previous_round -> RR[t-1]` only for `t > 1`; `AC[t]`: `evaluates -> RR[t]`; `PC[t]`: `filters -> AC[t]`, `evaluates -> RR[t]`; `FC`: `evaluates -> RR[T]`; `MB[t]`: `maps -> RR[t]`, `admitted_by -> PC[t]`; `ND[t]`: `bounded_by -> MB[t]` when `p[t]=1`, otherwise `no_projection_for -> RR[t]`; `CL[t]`: `snapshot_for -> RR[t]`; `PA[t]`: `round -> RR[t]`, `governed_by -> PC[t]`, `audits -> MB[t]`, `diffusion -> ND[t]`, `ledger_snapshot -> CL[t]`; `NR`: `replays -> RR[1..T]`, `admission -> AC[1..T]`, `final_audit -> FC`, `projection -> PC[t]`, `modifiers -> MB[t]`, `diffusion -> ND[1..T]`, `ledgers -> CL[1..T]`, `audits -> PA[t]`, with every repeated target in ascending tick order | `AC`, `ND` and `CL` are always one per tick, including zero-proposal ticks. When `p[t]=0`, `PC[t]`, `MB[t]` and `PA[t]` are forbidden; `ND[t].attempted` is false, `RR[t].no_projection_reason` is the canonical `no_projection`, and all before/after hashes are identical. When `p[t]=1`, all three are required even for a numeric no-op, `RR[t].no_projection_reason` is null, and the audit final hash equals the tick after-hash. |

Each ordinary relationship uses the target reference's exact `artifact_id` and
`content_hash`. The prose arrow labels above are the only allowed ordinary
`relationship_type` values for that source token and mode. Repeated targets
expand into separate relationship records. No extra relationship is allowed,
except the retry-only `supersedes` relationship defined below; when present it
is last in the source reference's relationship tuple.

On a negotiation retry, Run Control validates every already-completed round
provider-free from its stored payloads and chains. It then re-emits and persists
the complete proof Artifacts for those rounds under the new `attempt_id` before
continuing. Each re-emitted Artifact carries a final `supersedes` relationship
to the authenticated original Artifact's `content_hash` and `attempt_id` (and
its `artifact_id`); its other governed relationships are rebuilt against the
new-attempt Artifacts. `supersedes` is allowed only for this negotiation retry
copy path. Artifacts belonging to a failed attempt are never directly admitted
to finalization, even if their bytes validate, and the completed execution's
proof references only Artifacts carrying the current successful `attempt_id`.

After structural validation, the Kernel applies these semantic equalities over
claims rather than over opaque hashes alone:

- every referenced `run_id` and attempt agrees with the request; every count
  equals its tuple length and every ID set is unique;
- in deterministic and audit-only modes, `FC.deterministic_result_hash` equals
  both projections' `source_run_hash`. In hybrid modes it equals the baseline
  source hash, and in negotiation it equals the final source hash;
- for hybrid modes, accepted IDs agree across `FC`, `MB`, `PA` and `HR`; the
  exact invariant is `MB.modifier_tuples == PA.modifier_tuples`, including the
  valid empty-tuple numeric no-op; `HR`'s audit, modifier,
  ledger and baseline hashes agree with the corresponding claims. Stored replay
  reproduces `HR.final_result_hash`, which is the final canonical result before
  `hybrid_trace` is attached. Run Control then derives that replay result's
  deterministic source payload and projected WorldState and verifies their
  hashes against the final projection's `deterministic_source_hash` and
  `world_state_hash`. The persisted full source `WarRoomRun` includes
  `hybrid_trace`; its separately computed hash must equal both
  `HR.full_source_run_hash` and the final projection's `source_run_hash`.
  `CL.ledger_entry_count` is exactly zero with a recomputed canonical
  empty-ledger hash;
- for negotiation, `RR[1].before_result_hash` equals the baseline projection,
  each later before-hash equals the prior tick's after-hash, and
  `RR[T].after_result_hash` equals the final projection. Per tick, proposal and
  accepted-ID sets agree with `AC`, and, when `p[t]=1`, with `PC`, `MB` and
  `PA`; for each such tick the exact invariant is
  `MB[t].modifier_tuples == PA[t].modifier_tuples`, including the valid
  empty-tuple numeric no-op. The round's
  audit/modifier/diffusion/ledger hashes equal those typed claims. `NR`
  reproduces all tick-ordered hash tuples including `null` slots,
  has `provider_calls_required = 0`, and binds the baseline/final projection
  hashes;
- `p[t]` is recomputed from the explicit accepted-ID and diffusion-attempt
  claims. Thus a no-projection tick cannot suppress a required audit, and a
  surplus audit cannot be hidden on a no-projection tick.

The three hashes in each `WarRoomProjection` are distinct and are never
interchangeable: `source_run_hash` hashes the complete canonical source
`WarRoomRun`; `deterministic_source_hash` hashes only the deterministic source
payload admitted by the projection boundary; and `world_state_hash` hashes the
canonical projected `WorldState`. Run Control recomputes the first two from
their canonical source payloads before constructing the request. The Kernel
recomputes `world_state_hash` from the enclosed state and compares each
remaining proof claim only with the identically scoped projection field. It
does not infer a hash's scope, preimage or semantic meaning from the digest;
supplying the same digest under different field names is not proof.

The existing public lifecycle request's nullable seed remains compatible. Job
creation resolves it by the algorithm above and pins the resulting integer in
the job, normalized scenario, runtime profile, Kernel request and both
projections. The pure Kernel receives that integer and never invents a
replacement for `null`.

The Kernel mode vocabulary is:

| Existing engine mode | Kernel mode | Numeric-state meaning |
|---|---|---|
| `deterministic` | `deterministic` | baseline equals final |
| `mock_agent`, `controlled_agent` | `deterministic` | Agent output is observation/audit only; baseline equals final |
| `hybrid` | `hybrid` | accepted proposals map through Action Adapter and deterministic rerun |
| `hybrid_recorded` | `hybrid` | accepted proposals map through Action Adapter and hybrid stored replay |
| `negotiation` | `negotiation` | admitted round actions and diffusion map through deterministic reruns |

`hybrid_recorded` is currently accepted by the input contract but is not routed
through lifecycle mode execution. That is a migration gap, not an existing
offline-input or stored-transcript behavior. The implementation of this ADR
MUST route it through the same controlled Agent invocation and hybrid
deterministic projection path as `hybrid`, persist the complete `AR, PB, FC,
MB, CL, PA, HR` Artifact set, and then perform provider-free replay from those
stored Artifacts before finalization. The replay's current optional Projection
Audit parameter is another migration gap: it becomes mandatory and non-null on
both v2 hybrid paths, and missing it fails closed.

The internal `AgentActionProjectionAudit.projection_mode` vocabulary adds
`negotiation`. This is an internal Artifact-payload extension only; the OpenAPI
contract and all public response models remain unchanged.

`finalize_execution()` performs no storage, Provider, network or wall-clock
access. It verifies:

1. baseline/final `WarRoomProjection` schema, run id, effective integer seed,
   Rule Pack hash and entity topology agree;
2. `source_run_hash`, `deterministic_source_hash` and `world_state_hash` retain
   their distinct meanings and cross-field projection relationships;
3. authoritative country risk and supply-chain pressure components retain the
   deterministic engine owner;
4. every proof is a complete `KernelModeProofReference` in canonical order,
   with exact mode/category cardinality, coordinate sequence and relationship
   structure; arbitrary digests without their complete typed envelopes fail;
5. projection and proof references agree on run, attempt, tick, governed
   subject, final state and deterministic authority path;
6. deterministic/audit-only modes do not change numeric `WorldState`;
7. hybrid and negotiation changes cannot be admitted without their governed
   deterministic authority paths; and
8. hybrid supplies exactly one canonical, versioned Commitment Ledger proof
   whose ledger has zero entries. A missing or non-empty hybrid ledger is
   invalid.

These are structural, cardinality, cross-field projection and authority checks.
The pure Kernel neither reads nor authenticates storage and therefore does not
claim that `artifact_sha256` came from a stored Artifact.

### Mode-specific Run Control adapter

Run Control owns a `ModeExecutionAdapter`. It may read verified lifecycle
Artifacts and invoke existing provider-free mode replay functions, then passes
only immutable typed projections and proof references into the pure Kernel
gate.

Run Control authenticates each stored Artifact and its outer
`artifact_sha256`, canonicalizes the payload, checks the inner `content_hash`,
and constructs the complete typed reference. The pure Kernel then validates
that reference's structure and relationship to the projections and authority
path. Neither layer accepts a bag of caller-provided digest strings as a
substitute for authenticated typed envelopes.

The adapter rules are:

- deterministic: verify stored baseline/final identity and final Consistency
  Audit;
- mock/controlled Agent: additionally verify observation/proposal hashes and an
  audit-only Projection Audit when proposals exist; no Action Adapter hash is
  allowed;
- hybrid and `hybrid_recorded`: verify stored proposals, Consistency Audit,
  modifier bundle, Projection Audit and hybrid stored replay, plus exactly one
  canonical versioned empty Commitment Ledger; a non-empty ledger is invalid,
  before requesting Kernel finalization;
- negotiation: verify message, round, state and Commitment chains through
  stored-only negotiation replay, the two distinct Consistency reports and
  their bindings, the required per-tick Commitment Ledger snapshot, and every
  Projection Audit required by the tick cardinality below.

The adapter is fail-closed. A missing, duplicated, corrupt, cross-run or
mode-incompatible proof prevents report generation and research-run
projection.

### Negotiation Projection Audit closure

The target negotiation contract retains two distinct Consistency reports: the
read-only admission report that decides which proposals may proceed, and the
projection report that governs the deterministic projection inputs. Current
code does not yet satisfy that storage contract: its second report is
transient. This ADR requires the implementation to persist both reports as
versioned Artifacts, keep their hashes distinct, and bind both identities into
the hash-addressed round chain so replay detects replacement of either one.
They cannot be substituted for or deduplicated into one another. The modifier
bundle and `AgentActionProjectionAudit` both bind the persisted projection
report.

Per-tick proof cardinality is exact:

1. A rejected or empty tick with no accepted proposal and no narrative
   diffusion projection attempt is a no-projection tick. It carries an explicit
   canonical `no_projection` reason and identical before/after state hashes; it
   must not imply that a deterministic projection occurred.
2. Every tick with at least one accepted proposal or a narrative diffusion
   projection attempt has exactly one `AgentActionProjectionAudit`, even when
   deterministic execution produces no numeric change. A diffusion-only tick
   therefore also requires exactly one Projection Audit.
3. Every tick has exactly one versioned Commitment Ledger snapshot proof,
   including rejected, empty and otherwise no-projection ticks and including an
   empty ledger. Its snapshot hash is retained in the round chain.

For a projection attempt, the implementation will build the deterministic
modifier bundle, run the deterministic engine and bounded diffusion adapter,
and build and verify `AgentActionProjectionAudit` against the resulting final
tick-state hash. The round output will embed the two persisted,
version-bound Consistency-report references, modifier binding and Projection
Audit reference. The audit is persisted with
`artifact_type = negotiation_projection_audit`, a new allowed value in the
existing generic Artifact store. It is not a new storage type or public model:
no table, Artifact storage schema, OpenAPI schema or public Artifact model is
added.

Negotiation replay verifies both Consistency-report hashes and their round-chain
links, the projection-report bindings from the modifier bundle and Projection
Audit, the Projection Audit hash, projected proposal ids, tick result hash,
canonical no-projection reason and unchanged-state proof when applicable, and
the Commitment Ledger snapshot proof for every tick.

### Report and recovery contract

Upgrade the internal report step to `report-generate.v2` and the Artifact to
`report-projection-manifest.v2`. Embed the compact
`KernelModeExecutionRecord`, not Agent text or full WorldState, in that existing
Artifact.

The persistence boundary is also mandatory. If
`persist_war_room_result()` receives a non-null `lifecycle_job_id`, its internal
contract also requires a validated `KernelModeExecutionRecord` that matches
that lifecycle job's run id, current successful `attempt_id`, pinned
`runtime_profile` hash, execution-contract version, effective seed, engine mode
and final projection. The function validates that match before any Artifact or
`research_runs` write; a missing, stale or mismatched record fails closed.
Legacy synchronous deterministic callers with `lifecycle_job_id = null` remain
on the v1 compatibility path. That exception cannot persist hybrid or
negotiation lifecycle outputs and cannot be used to bypass v2 job pinning.

This uses the existing generic Artifact store and adds no table, Artifact
storage schema or public Artifact model. Existing v1 report steps that have not
projected are invalidated by the step-version change and safely rerun. Already
projected historical jobs remain readable. New v2 report checkpoints must
revalidate their execution record against the referenced mode Artifacts before
recovery can continue.

In `replay_archive`, checkpoint validation is not sufficient by itself. The v2
execution record and every referenced Artifact must be revalidated immediately
before `persist_war_room_result()` performs the `research_runs` write. The
existing-projection early-return path must also revalidate the v2 execution
record and its referenced Artifacts before returning success. Any tampering
fails closed. That failure must not rewrite, repair or delete an immutable
historical projection that already exists.

### Rollout

Deployment is worker-first. All workers that can receive these lifecycle jobs
must support `kernel-mode-execution.v2`, its seed normalization and its
finalization/persistence gate before job creation is allowed to pin new jobs to
v2. Only then is the creation switch enabled. A worker lease validates the
job-pinned marker in the hashed `runtime_profile` and refuses the lease when
the worker does not declare support for that exact marker. V2-capable workers
continue to execute jobs pinned to the v1 contract through the existing v1
compatibility path; those jobs are not rewritten or opportunistically upgraded.

A job pinned to `kernel-mode-execution.v2` must never be processed by an old
worker, including during rollback. Rollback first disables creation of new v2
pins, then lets v2-capable workers drain active and queued v2-pinned jobs to a
terminal state or explicitly cancels the remaining jobs. Only after no
processable v2-pinned job remains may the worker/report implementation be
reverted. Lease refusal is a safety boundary, not a retryable invitation to an
older worker.

### Performance gates

The thresholds and protocol are fixed before implementation measurement. They
must not be relaxed after any result is observed. The benchmark runs with
network access denied and a Provider seam that counts and fails every call,
against an isolated temporary SQLite database. Each control/treatment member
starts from a byte-identical copy of a fixed, prebuilt stored fixture. Fixture
bytes, row identities and the database-file SHA-256 are committed before
measurement and are reported with the results.

The fixture is an exact post-`consistency_audit` checkpoint, not a queued job
that would execute an engine or Provider path. For each representative mode,
every clone contains:

- one `run_jobs` row with the fixed canonical scenario, pinned Rule Pack id and
  hash, normalized integer job/scenario seed, and a matching
  `runtime_profile.effective_seed`; its hashed runtime profile pins
  `execution_contract_version = "kernel-mode-execution.v2"`. The row has
  `status = "running"`, `current_phase = "consistency_audit"`, the production
  post-audit progress value, `result_run_id = null`, and
  `current_attempt_id = A` for the fixture's sole attempt, plus the fixed worker
  owner and an unexpired lease. The referenced fixture Rule Pack row contains
  the committed bytes matching that id and hash;
- one `run_attempts` row for `A`, with attempt number 1 and `status = "running"`.
  Its worker id matches the job owner and its declared resume step is
  `report_generate`;
- exactly four completed, current-attempt `run_steps` rows, in production order,
  for `scenario_compile`, `environment_prepare`, `deterministic_run` and
  `consistency_audit`, using their production step versions. Their stored input
  chain contains the exact prior step id, prior `output_hash` and prior
  `artifact_refs`. For each row, `input_hash` and `output_hash` are recomputed
  from the stored canonical input and output, and the row's sorted
  `artifact_refs` is exactly the sorted list in its output and exactly the set of
  fixture Artifacts produced by that step;
- current-attempt `run_artifacts` rows for the scenario, environment, baseline
  result, mode-specific final result where distinct, and every proof-source
  Artifact required by the matrix above: `FC` for `deterministic`; `AR, PB, FC,
  MB, CL, PA, HR` for `hybrid`; and the complete
  `RR[1..T], AC[1..T], PC[p[t]=1], FC, MB[p[t]=1], ND[1..T], CL[1..T],
  PA[p[t]=1], NR` sequence for `negotiation`. Every Artifact row has
  `attempt_id = A`, its producing `step_id`, the pinned schema version, canonical
  payload bytes and the exact outer SHA-256 authenticated by the checkpoint;
- no `report_generate` or `replay_archive` step row, report Artifact, projection
  Artifact, active partial step, earlier attempt, or unreferenced mode Artifact.

Before starting either timer, the harness loads the job through the production
repository and calls `load_verified_checkpoint(job)`. It asserts that the four
completed step keys and all selected step and Artifact attempt identities are
exactly those above, that `checkpoint.next_step_key == "report_generate"`, and
that the Provider call counter is still zero. The benchmark then invokes the
same production `process_job(run_id)` resume/process entry that a worker invokes
after claim; it must not call a report or finalization helper directly. Timing
instrumentation records the specified internal boundaries while that production
entry continues normally, and the Provider counter must remain zero after the
member completes.

The control and treatment differ only at the pending report step over that same
stored checkpoint. The control selects the production v1 compatibility report
step and writes no v2 finalization record; the treatment selects the production
v2 report step, including `ModeExecutionAdapter`, `finalize_execution()` and the
v2 record. The harness must declare and report the production selection seam it
uses; it may not rewrite the v2 pin, seed, checkpoint rows or Artifact bytes. If
the production resume/process entry requires a different non-terminal status in
that harness, the exception, entry name and exact status must be declared in the
results, and both members must prove before timing that
`load_verified_checkpoint()` accepts the row and returns `report_generate`.

The p95 benchmark covers the three representative normalized Kernel modes
`deterministic`, `hybrid` and `negotiation`. The engine aliases `mock_agent`,
`controlled_agent` and `hybrid_recorded` are covered by functional integration
tests of their normalization, proof requirements and v2 report checkpoint, not
by separate p95 gates.

For each representative mode, run three unreported warmup **pairs**, followed
by 30 measured control/treatment **pairs**. A pair uses two fresh copies of the
same stored fixture. Number the 33 pair rounds from zero, without resetting
after warmup. Within each mode's pair, run control then treatment on even
rounds, and treatment then control on odd rounds. Across a pair round, use this
fixed six-round cycle of mode orders, then repeat it:

1. `deterministic`, `hybrid`, `negotiation`;
2. `hybrid`, `negotiation`, `deterministic`;
3. `negotiation`, `deterministic`, `hybrid`;
4. `negotiation`, `hybrid`, `deterministic`;
5. `hybrid`, `deterministic`, `negotiation`;
6. `deterministic`, `negotiation`, `hybrid`.

Use a monotonic high-resolution clock and retain raw, unrounded durations. For
30 values, nearest-rank p95 is the value at one-based rank
`ceil(0.95 * 30) = 29` after ascending sort. Compute the combined-lifecycle
ratio by dividing the treatment p95 by the control p95 using their raw,
unrounded values; do not average per-pair ratios or divide rounded display
values.

The timers have these exact boundaries:

- Artifact and job-row lookup is timed and reported separately, and is excluded
  from the stored-finalization timer and its p95 gate.
- The stored-finalization timer starts with already-loaded,
  outer-SHA-verified stored payloads. It includes Pydantic and canonical-payload
  validation, stored-only replay, baseline/final projection construction,
  `ModeExecutionAdapter` proof construction, the pure Kernel
  `finalize_execution()` call and execution-record serialization. It stops
  before report Artifact persistence.
- The combined-lifecycle timer starts from the same stored checkpoint state and
  ends when its report checkpoint is complete. It includes the normal Artifact
  and job-row lookup, validation, mode execution/replay, report generation and
  report-projection-manifest persistence. The control follows the same
  mode-specific lifecycle but omits construction, validation, serialization
  and persistence of the v2 finalization record; the treatment adds exactly
  that v2 finalization work.

Under that protocol:

- deterministic stored finalization p95 must be at most **20 ms**;
- hybrid stored finalization p95 must be at most **50 ms**;
- negotiation stored finalization p95 must be at most **100 ms**;
- adding finalization must keep each mode's combined lifecycle p95 at most
  **1.15 times** its control lifecycle p95;
- the embedded record must be at most **32,768 UTF-8 bytes**;
- migration files, the committed OpenAPI snapshot and all public response
  models must remain unchanged.

## Compatibility and acceptance gates

This slice is accepted only when:

- all existing Golden Scenario hashes remain byte-for-byte unchanged;
- every new v2 lifecycle report for `deterministic`, `mock_agent`,
  `controlled_agent`, `hybrid`, `hybrid_recorded` and `negotiation` has one
  valid execution record; legacy synchronous deterministic v1 reports are
  outside that statement;
- job creation pins the v2 marker and the one normalized effective seed inside
  the hashed `runtime_profile`; seed `0` survives unchanged and no execution or
  replay path uses a truthiness fallback;
- creation of v2-pinned jobs stays disabled until every eligible worker is
  v2-capable, unsupported workers refuse such leases, and v1-pinned jobs remain
  executable without profile mutation;
- functional integration tests exercise all six engine names, including alias
  normalization and their required v2 report checkpoint, while the p95 gates
  use only the three representative normalized Kernel modes;
- all three Kernel modes call the same public `finalize_execution()` method;
- a spy proves the pure Kernel contract cannot call an Agent Provider or
  storage;
- Agent observations cannot appear as numeric-authority StateDelta sources;
- hybrid cannot finalize without Consistency, Action Adapter, Projection Audit,
  hybrid stored replay and exactly one canonical versioned empty Commitment
  Ledger proof;
- `hybrid_recorded` exercises the controlled Agent plus hybrid deterministic
  projection path, persists the complete hybrid proof set, and completes a
  provider-free stored replay with a mandatory Projection Audit; it is never
  treated as an offline-input mode;
- hybrid replay proves the pre-`hybrid_trace` result hash, separately proves the
  traced full-source hash, and verifies the deterministic-source and
  WorldState hashes against the final projection;
- negotiation cannot finalize without round Consistency, Projection Audit,
  Commitment Ledger and replay proofs, with distinct admission and projection
  reports bound into the round chain;
- a negotiation retry revalidates completed rounds without a Provider,
  re-emits their complete proof Artifacts under the successful `attempt_id`
  with authenticated `supersedes` lineage, and admits no failed-attempt
  Artifact directly;
- every rejected or empty no-projection negotiation tick records the canonical
  `no_projection` reason, proves identical before/after state and has exactly
  one Commitment Ledger snapshot proof;
- every accepted-proposal, narrative-diffusion and diffusion-only projection
  attempt has exactly one Projection Audit even when it is a numeric no-op, and
  every negotiation tick, including an empty one, has exactly one Commitment
  Ledger snapshot proof;
- negotiation Projection Audits use the internal `negotiation` projection mode
  and `artifact_type = negotiation_projection_audit` without changing OpenAPI
  or public responses;
- stored hybrid and negotiation replay produce the exact final result and
  WorldState hashes admitted by the record;
- report checkpoint recovery rejects nested proof tampering even if an outer
  Artifact SHA is recomputed;
- `replay_archive` revalidates v2 records and referenced Artifacts immediately
  before the `research_runs` write and on the existing-projection early return;
  tampering fails closed without rewriting or deleting an immutable historical
  projection;
- every non-null `lifecycle_job_id` persistence call supplies and validates the
  matching execution record before any write, while the null-id v1 exception
  accepts only legacy synchronous deterministic output;
- precommitted performance and size budgets pass;
- backend, frontend, E2E, migration, OpenAPI, boundary, security and release
  gates pass.

## Rollback

1. Disable new `kernel-mode-execution.v2` job pinning while v2-capable workers
   remain deployed.
2. Drain active and queued v2-pinned jobs to completion on those workers, or
   explicitly cancel the remainder. Confirm that no processable v2-pinned job
   remains; an old worker is never allowed to consume one.
3. Revert the worker, report-step and adapter commits. No schema downgrade is
   required.
4. Historical `report-projection-manifest.v2` payloads remain valid generic
   Artifacts; older code ignores additive fields.
5. V1-pinned jobs continue through the v1 compatibility path. A cancelled or
   otherwise non-terminal v2-pinned job is not reinterpreted as v1 and may run
   again only after v2-capable workers are restored.
6. Already projected research runs are immutable and remain readable through
   V1-v11, Run Diff and Replay Pack.

## Consequences

Positive:

- `unified Kernel interface` becomes an executable projection gate rather than
  a naming convention;
- Agent society stays outside the deterministic Kernel while its effects must
  carry complete governance proof;
- reports gain compact mode-aware lineage without a database or API expansion;
- checkpoint recovery cannot silently bypass mode-specific replay.

Costs:

- hybrid and negotiation finalization perform additional stored verification;
- negotiation round payloads gain explicit Consistency and Projection Audit
  evidence;
- the first unified interface finalizes existing engine outputs; it does not
  yet replace legacy formulas with native per-tick Kernel reducers.

## Rejected alternatives

- Moving Agent/provider orchestration into Simulation Kernel: this violates
  deterministic authority and provider-free replay.
- A common enum with three direct dispatch branches: shared naming is not a
  shared integrity boundary.
- Trusting existing mode Artifact presence without replay: presence does not
  prove lineage or numeric authority.
- Treating negotiation Consistency evaluation as Projection Audit: admission
  and proof of deterministic projection are separate governance claims.
- Persisting a new top-level execution table or API: the existing report
  manifest and generic Artifact store are sufficient for this migration slice.
