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

### Job-pinned resolver contract and seed

The v2 contract is pinned at job creation inside the existing canonical
`runtime_profile` payload as
`execution_contract_version = "kernel-mode-execution.v2"`. The same payload
contains `effective_seed`, `minimum_worker_generation`,
`agent_pack_resolver_version`,
`constraint_context_resolver_version` and `evaluator_version`; those
creation-known values, the canonical scenario identity and the existing Rule
Pack ID/hash all participate in
`runtime_profile_hash = H(complete_runtime_profile)`. Job creation pins only
these creation-known execution inputs and implementation versions. It MUST NOT populate
`agent_pack_id`, `agent_pack_hash` or `constraint_context_hash`: those are
outputs derived from the deterministic baseline, which does not yet exist at
job creation, and they are not members of the runtime profile. Each pinned
version selects one installed provider-free deterministic implementation; an
unknown or unavailable version is an error, not a reason to substitute another
implementation. None of these values are caller overrides or defaults. They
are not new job columns, may not be rewritten when a job is retried or
recovered, and are checked before mode dispatch and again before report
persistence.

For a v2 profile, `minimum_worker_generation` is the strict positive integer
deployment generation authorized by GOV-WORKER-1. It is immutable for the
life of the job and has no missing-value or coercing default. Its absence still
belongs only to the key-absent legacy-v1 profile defined by GOV-RECOVERY-1; an
explicit v2 marker without this key is malformed and fails before dispatch or
claim.

Job creation resolves the seed exactly once. It selects the top-level request
seed when that value is not `None` (so `0` is valid), otherwise
`scenario.seed` when that value is not `None`, otherwise the integer `42`.
Creation writes that one integer to both the stored job seed and the stored
scenario seed as well as to `runtime_profile.effective_seed`. Every mode,
Provider invocation, Run Control adapter, replay, Kernel request and projection
uses that pinned integer. Implementations must remove truthiness fallbacks such
as `seed or 42`; no later layer resolves or substitutes the seed independently.

Immediately after `deterministic_run` has persisted the deterministic baseline,
and before any Agent Provider invocation or any FC/AC/PC Consistency
evaluation, Run Control resolves the mode context. It invokes the pinned Agent
Pack resolver and then the pinned constraint-context resolver with only the
outer-SHA-verified complete baseline, normalized scenario, complete verified
Rule Pack and effective seed; the second resolver additionally receives the
complete Agent Pack returned by the first. Both resolvers are provider-free,
deterministic functions. They return one complete immutable Agent Pack with a
deterministic ID and
`agent_pack_hash = H(complete_agent_pack)`, and one closed complete constraint
context with
`constraint_context_hash = H({"schema_version":"agent-constraint-context.v1",
"context":complete_constraint_context})`.

#### Resolver payload and completed-step contract (ADR-0007 amendment)

The resolver Artifact payloads are closed and deterministic. This amendment
removes the ambiguity in “complete Agent Pack” without changing the legacy
`agent-pack-manifest.v1` model or its `manifest_hash` meaning.

The Agent Pack Artifact content is exactly the following object, with no
wrapper fields and no additional members:

```json
{
  "schema_version": "agent-pack-resolver-payload.v1",
  "agent_pack_id": "...",
  "status": "active",
  "seed": 42,
  "profiles": [
    {
      "agent_id": "...",
      "actor_type": "...",
      "country_code": "...",
      "country_name": "...",
      "capabilities": ["..."],
      "action_budget": 6,
      "profile_hash": "..."
    }
  ],
  "legacy_manifest_hash": "...",
  "created_at": "2000-01-01T00:00:00.000Z"
}
```

`profiles` is ordered by UTF-8 `agent_id` and contains unique IDs. Every
profile object is closed, `capabilities` contains unique action types in UTF-8
order, and `profile_hash` remains the legacy profile-core hash. The resolver
payload's `agent_pack_hash` is exactly `H(the complete object above)`; the
`agent_pack_hash` field is not embedded in that object. `legacy_manifest_hash`
is retained for compatibility and is never used as the V2 authority hash.
The fixed timestamp is deterministic and is not a wall-clock value.

The constraint-context Artifact content is exactly this closed object:

```json
{
  "schema_version": "agent-constraint-context.v1",
  "actor_capabilities": [["agent-id", ["action-type"]]],
  "action_budgets": [["agent-id", 6]],
  "known_entities": ["..."],
  "known_evidence_refs": ["..."],
  "source_label": "..."
}
```

`actor_capabilities` and `action_budgets` are ordered by UTF-8 agent ID;
their IDs must match exactly. Action lists, `known_entities`, and
`known_evidence_refs` are unique and UTF-8 ordered. The context hash is exactly
`H({"schema_version":"agent-constraint-context.v1",
"context":the complete context object without its schema_version member})`.
The context hash is not embedded in the Artifact payload.

Neither payload contains organization, project, lifecycle-job, run, session,
attempt, or tick coordinates. Those coordinates are authenticated by the
Artifact row, completed-step row, and the closed resolver `artifact_refs`
tuple. A resolver is shared across Agent-capable modes, so `session_id` and
`tick` are null at this boundary; negotiation reuses the same pair without
re-resolving it per tick.

The completed `deterministic_run` step output is the closed object below, with
exactly these keys:

```json
{
  "schema_version": "deterministic-run-resolver-output.v1",
  "run_id": "...",
  "attempt": "...",
  "agent_pack_resolver_version": "...",
  "constraint_context_resolver_version": "...",
  "effective_seed": 42,
  "baseline_result_hash": "...",
  "scenario_hash": "...",
  "rule_pack_hash": "...",
  "agent_pack_id": "...",
  "agent_pack_hash": "...",
  "constraint_context_hash": "...",
  "artifact_refs": [
    ["resolver", "agent-artifact", "...", "...", "agent-pack-resolver-output.v1", "..."],
    ["resolver", "context-artifact", "...", "...", "constraint-context-resolver-output.v1", "..."]
  ]
}
```

The two refs occur in fixed Agent Pack then constraint-context order. The
step-output hash is computed from this complete object, including ordered
refs, but no hash field is self-included. The Agent Pack ref's `content_hash`
equals `agent_pack_hash`; the context ref's `content_hash` equals
`constraint_context_hash`. All resolver versions and input hashes above are
job-pinned values or verified deterministic-baseline outputs, never caller
overrides. Unknown resolver versions, missing or duplicate refs,
cross-attempt refs, schema mixing, payload substitution, or any field drift
fail closed before Provider or Consistency work.

For every Agent-capable mode, the current attempt persists those two complete
payloads through the existing generic Artifact store as `agent_pack` and
`agent_constraint_context` Artifacts; their canonical content is respectively
the complete Agent Pack and the closed `agent-constraint-context.v1` object.
The completed `deterministic_run` step output and `artifact_refs` bind both
Artifact IDs, `agent_pack_id`, `agent_pack_hash` and
`constraint_context_hash` using the closed resolver checkpoint variant defined
below. This adds no
table, Artifact storage schema, public API or public model. The payloads are
resolver-input Artifacts, not caller-supplied Kernel proof references. On every
resume or recovery, Run Control reruns both pinned resolvers from the verified
baseline and pinned inputs before any Provider/Consistency work, recomputes all
IDs/hashes, and compares both complete regenerated payloads field-for-field
with the stored Artifacts and step bindings. Missing, duplicate, cross-attempt
or different output fails closed; recovery never repairs or adopts it.

The mode nullability is closed and explicit:

- `deterministic` does not invoke either context resolver and permits no Agent
  Pack or constraint-context Artifact. Its request, record and FC carry the
  required keys `agent_pack_id`, `agent_pack_hash` and
  `constraint_context_hash` with explicit `null` values;
- `mock_agent` and `controlled_agent` resolve exactly one non-null pair after
  the baseline and use it for their audit-only Agent/FC path;
- `hybrid` and `hybrid_recorded` resolve exactly one non-null pair and use that
  same pair for controlled Agent invocation, FC, deterministic adapter replay
  and finalization; and
- `negotiation` resolves exactly one non-null pair and reuses it unchanged for
  every Agent invocation, AC, PC, terminal FC, stored replay and finalization
  at every tick.

No other nullable combination is valid. In particular, a non-deterministic
mode requires all three values to be non-null, while deterministic requires all
three to be null.

### Pure Kernel contracts

Introduce immutable, versioned contracts:

- `KernelModeProofReference`: a complete typed Artifact envelope containing
  `proof_schema`, `artifact_type`, `schema_version`, `artifact_id`, `run_id`,
  nullable `session_id`, `attempt`, nullable schema-governed `ordinal` and `tick`, the outer
  stored-Artifact `artifact_sha256`, the inner canonical-payload
  `content_hash`, immutable schema-specific `claims`, `claims_hash`, and an
  ordered `relationships` tuple. Each relationship is limited to the
  canonical `relationship_type`, `target_artifact_id`, `target_content_hash`
  and nullable `target_attempt` needed to connect that proof to its governed
  parent or subject. `target_attempt` is required only for the retry
  relationship `supersedes` in any mode and is forbidden for every other
  relationship; arbitrary metadata is not part of this contract;
- `KernelModeExecutionProof`: an ordered tuple of
  `KernelModeProofReference` values for Agent observations, Consistency audits,
  negotiation eligibility decisions, Action Adapter bundles, narrative
  diffusion evidence, Commitment Ledgers, Projection Audits and provider-free
  replay manifests. Each proof schema fixes the exact category cardinalities
  and canonical reference order. Missing, duplicated, surplus or out-of-order
  references, invalid `ordinal`/`tick` sequences, and undeclared relationships
  are rejected;
- `KernelModeExecutionRequest`: the exact engine mode, normalized Kernel mode,
  exact organization/project/lifecycle-job/run/session/current-attempt
  ownership, pinned effective-seed/Rule Pack/runtime-profile identity, the verified
  post-baseline Agent Pack/context identity where mode-applicable, the
  existing baseline and final `WarRoomProjection` envelopes, the proof and a
  request hash. It does not accept bare `WorldState` values or separately
  asserted result/state hashes;
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
NaN/Infinity. On every Artifact-consuming path, including persistence,
recovery and a terminal-completed-job duplicate GET, the declared Artifact type
and source `schema_version` are untrusted registry selectors only. The one
mandatory validation order is: (1) read `content_json` as opaque raw bytes and
recompute/compare the outer `artifact_sha256` over exactly those bytes; (2) only
then strictly decode UTF-8 and parse JSON while retaining number lexemes; (3)
only then validate the storage-envelope selector and the selected closed source
schema; (4) only then recompute/compare `content_hash`; and (5) only then
extract and validate claims, `claims_hash` and relationships. A later stage may
not supply facts to, or excuse failure of, an earlier stage. No Pydantic model
or other coercing validator may run before the strict parse, and no claims
extractor may run before closed-schema and content-hash validation. The strict
parser rejects non-UTF-8 bytes, a BOM,
duplicate object keys at any depth, invalid Unicode or unpaired surrogates,
non-finite numbers, top-level scalars where an object is required, and any
scalar coercion. Thus a quoted number is not a number, a boolean is not an
integer and a numeric token is not a string. Unknown, missing or additional
keys then fail the selected closed source schema. No storage field or decoded
payload fact is trusted merely because the raw-byte digest matches.

The parser retains every raw JSON number lexeme until schema validation and
hash verification finish. The new canonical-Decimal rule applies only to
schema-declared non-integer quantitative fields: their raw token must equal the
ordinary base-10, no-exponent rendering of its arbitrary-precision `Decimal`,
with no leading `+`, redundant leading or trailing zero, or negative zero.
Consequently `1e0`, `01`, `1.0` where the canonical value is `1`, and `-0` are
rejected rather than normalized before hashing. Every schema-declared integer
token must match exactly `0|-?[1-9][0-9]*`: the integer lexeme `0` is accepted,
whereas the integer lexeme `-0` is rejected before numeric conversion and may
not be reclassified as a Decimal negative zero. Nonzero integers have no
leading zero. `tick`,
message/event `seq`, every `*_count`, seed and other integer coordinates use
those strict JSON integer tokens and are never parsed through Decimal.
Fixed-point claim values use strict signed int64 integers. Legacy v1 inner payloads retain their own pinned
numeric and digest rules; this exception does not relax the enclosing v2/v3
wrapper parser.

`claims_hash` is exactly:

```text
sha256(canonical_json({"claims": claims, "proof_schema": proof_schema}))
```

`content_hash` applies the same canonical encoding to the complete parsed
Artifact payload. `artifact_sha256` remains the current Artifact-store digest
over the exact stored `content_json` UTF-8 bytes. These two hashes can be equal
when the stored representation is already canonical, but equality is neither
required nor used as a substitute for checking both scopes.

Run Control first recomputes and successfully compares `artifact_sha256` over
the exact stored raw bytes, and only then performs that strict UTF-8/JSON parse,
validates the storage envelope's
`artifact_type`/`schema_version` against the registry selection, validates the
closed payload, and recomputes `content_hash`. It then runs the extractor
selected by `proof_schema`, compares the extracted record field-for-field with
`claims`, recomputes `claims_hash`, and checks every ordinary relationship
target against another outer-SHA-verified reference in the current proof. It
may not fill a missing payload fact from the Artifact envelope or from another
Artifact. A `supersedes` target is instead an outer-SHA-verified historical
Artifact selected by the retry rule below. Its `target_attempt` is the
historical row's opaque stored `attempt_id`, and its content hash must equal
both `target_content_hash` and the re-emitted current Artifact's
`content_hash`. Run Control resolves the historical and current attempt IDs
through `run_attempts` and compares their integer `attempt_number` values; the
stored IDs' format or lexical order is never evidence of an earlier attempt.
The historical Artifact is authenticated only as the
`supersedes` target and is not admitted into the final proof. If an older
payload version cannot expose a required claim, it is
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

The central proof, request and record hash scopes are closed. A canonical
reference dump has exactly these keys:

```text
{"proof_schema":proof_schema,"artifact_type":artifact_type,
 "schema_version":schema_version,"artifact_id":artifact_id,"run_id":run_id,
 "session_id":session_id,"attempt":attempt,"ordinal":ordinal,"tick":tick,
 "artifact_sha256":artifact_sha256,"content_hash":content_hash,
 "claims":claims,"claims_hash":claims_hash,
 "relationships":[{"relationship_type":relationship_type,
   "target_artifact_id":target_artifact_id,
   "target_content_hash":target_content_hash,
   "target_attempt":target_attempt},...]}
```

Every relationship field, including a required `null` `target_attempt`, is
present. `KernelModeExecutionProof` has exactly `schema_version` and
`references`, and its digest is:

```text
proof_hash = H({"schema_version":"kernel-mode-execution-proof.v1",
                "references":[complete_reference_dump,...]})
```

`KernelModeExecutionRequest` has exactly `schema_version`,
`execution_contract_version`, `organization_id`, `project_id`,
`lifecycle_job_id`, `run_id`, nullable `session_id`, `attempt`,
`engine_mode`, `kernel_mode`,
`effective_seed`, `rule_pack_id`, `rule_pack_hash`, nullable `agent_pack_id`,
nullable `agent_pack_hash`, nullable `constraint_context_hash`, `evaluator_version`,
`runtime_profile_hash`, `fencing_epoch_hash`,
`baseline_projection`, `final_projection`, `proof`, `proof_hash` and
`request_hash`. Both projections and `proof` are their complete canonical
objects, not hash summaries. The request digest is exactly:

```text
request_hash = H({"schema_version":"kernel-mode-execution-request.v1",
 "execution_contract_version":"kernel-mode-execution.v2",
 "organization_id":organization_id,"project_id":project_id,
 "lifecycle_job_id":lifecycle_job_id,"run_id":run_id,
 "session_id":session_id,"attempt":attempt,"engine_mode":engine_mode,
 "kernel_mode":kernel_mode,
 "effective_seed":effective_seed,"rule_pack_id":rule_pack_id,
 "rule_pack_hash":rule_pack_hash,"agent_pack_id":agent_pack_id,
 "agent_pack_hash":agent_pack_hash,
 "constraint_context_hash":constraint_context_hash,
 "evaluator_version":evaluator_version,
 "runtime_profile_hash":runtime_profile_hash,
 "fencing_epoch_hash":fencing_epoch_hash,
 "baseline_projection":complete_baseline_projection,
 "final_projection":complete_final_projection,"proof":complete_proof,
 "proof_hash":proof_hash})
```

`KernelModeExecutionRecord` has exactly `schema_version`,
`execution_contract_version`, `request_hash`, `organization_id`, `project_id`,
`lifecycle_job_id`, `run_id`, nullable `session_id`, `attempt`,
`engine_mode`, `kernel_mode`, `effective_seed`, `rule_pack_id`,
`rule_pack_hash`, nullable `agent_pack_id`, nullable `agent_pack_hash`,
nullable `constraint_context_hash`, `evaluator_version`, `runtime_profile_hash`, the three scoped baseline
fields `baseline_source_run_hash`, `baseline_deterministic_source_hash` and
`baseline_world_state_hash`, the corresponding three `final_*` fields,
`fencing_epoch_hash`, `authority_path`, `proof_hash` and `record_hash`.
`authority_path` is a closed, mode-derived discriminator with this exact
six-row mapping; it is never caller-selected and is included in the record
hash so that two execution modes cannot share an ambiguous lineage value:

| `engine_mode` | exact `authority_path` |
|---|---|
| `deterministic` | `deterministic_audit_only` |
| `mock_agent` | `mock_action_adapter_deterministic` |
| `controlled_agent` | `controlled_action_adapter_deterministic` |
| `hybrid` | `hybrid_action_adapter_replay` |
| `hybrid_recorded` | `hybrid_recorded_action_adapter_replay` |
| `negotiation` | `negotiation_governed_deterministic` |

The value must equal the row selected by the authenticated `engine_mode`; any
other value, including a value from another row, fails closed. Its digest has
this one exact preimage:

```text
record_hash = H({"schema_version":"kernel-mode-execution-record.v1",
 "execution_contract_version":"kernel-mode-execution.v2",
 "request_hash":request_hash,"organization_id":organization_id,
 "project_id":project_id,"lifecycle_job_id":lifecycle_job_id,
 "run_id":run_id,"session_id":session_id,
 "attempt":attempt,
 "engine_mode":engine_mode,"kernel_mode":kernel_mode,
 "effective_seed":effective_seed,"rule_pack_id":rule_pack_id,
 "rule_pack_hash":rule_pack_hash,"agent_pack_id":agent_pack_id,
 "agent_pack_hash":agent_pack_hash,
 "constraint_context_hash":constraint_context_hash,
 "evaluator_version":evaluator_version,
 "runtime_profile_hash":runtime_profile_hash,
 "fencing_epoch_hash":fencing_epoch_hash,
 "baseline_source_run_hash":baseline_source_run_hash,
 "baseline_deterministic_source_hash":baseline_deterministic_source_hash,
 "baseline_world_state_hash":baseline_world_state_hash,
 "final_source_run_hash":final_source_run_hash,
 "final_deterministic_source_hash":final_deterministic_source_hash,
 "final_world_state_hash":final_world_state_hash,
 "authority_path":authority_path,"proof_hash":proof_hash})
```

These are all the record fields except `record_hash`; no timestamp, caller
metadata, omitted default or additional key participates. The nullable fields
are always present in both hash preimages: deterministic hashes explicit JSON
`null` values, and every other mode hashes the non-null post-baseline resolver
outputs. `runtime_profile_hash` binds the resolver versions and inputs, while
these fields bind their regenerated outputs.

For every v2 lifecycle finalization, `organization_id`, `project_id`,
`lifecycle_job_id`, `run_id` and `attempt` are non-null. `session_id` is present
and may be null. Run Control derives this exact ownership tuple from the
canonical job and current attempt, never from a caller record or Artifact
payload:

```text
(organization_id, project_id, lifecycle_job_id, run_id,
 nullable session_id, current attempt)
```

The Kernel requires exact field-for-field equality of that tuple between the
request and returned record and compares its `run_id`, nullable `session_id`
and current `attempt` with every proof reference. Run Control has already
authenticated each reference's Artifact row and producing roots under the
same organization, project and lifecycle job before constructing the request;
a matching run ID alone is insufficient.

### Normative proof-schema registry

The `kp.*.v1` names below are internal proof-extractor identifiers, not source
payload versions. The `artifact_type` column uses the current generic Artifact
names exactly, while the stored `schema_version` is independently retained in
the reference. For `kernel-mode-execution.v2`, every source version listed
below is the one exact implementation contract in every mode named by the
matrix. Run Control accepts no alternative version. These payloads remain rows
in the existing generic Artifact store.

| Token / proof schema | Exact `artifact_type`; pinned source-schema scope | Required claims extracted from the canonical payload |
|---|---|---|
| `AR` / `kp.agent-runtime.v1` | `agent_runtime_audit`; exactly `agent-runtime-result.v1` | `run_id`, `runtime_hash`, ascending `proposal_ids` and aligned `proposal_hashes`, `proposal_count`, ascending `invocation_ids` and aligned `invocation_hashes`, `invocation_count` |
| `PB` / `kp.proposal-batch.v1` | `agent_action_proposals`; exactly `kernel-proposal-batch.v1` in `mock_agent`, `controlled_agent`, `hybrid` and `hybrid_recorded` | `run_id`, `source_kind`, nullable `source_runtime_hash`, nullable `source_mock_batch_hash`, `batch_hash`, ascending `proposal_ids` and aligned `proposal_hashes`, `proposal_count` |
| `FC` / `kp.final-consistency.v1` | `consistency_audit`; exactly `consistency-audit.v3` with an exact `consistency-audit.v2` inner report | `run_id`, fixed role `final`, null `tick`, `evaluator_version`, nullable mode-governed `agent_pack_id`, `agent_pack_hash`, `constraint_context_hash`, wrapper `audit_hash`, `inner_audit_hash`, `deterministic_result_hash`, ascending `proposal_ids` and aligned `proposal_hashes`, ascending `accepted_proposal_ids`, ordered `decision_tuples`, `decision_count` |
| `RR` / `kp.negotiation-round.v1` | `negotiation_round`; exactly `negotiation-round.v2` | `run_id`, `session_id`, `round_id`, `tick`, `input_hash`, `output_hash`, `round_hash`, `before_result_hash`, `after_result_hash`, ordered `(seq, message_id, message_hash)` tuples, `messages_hash`, `message_count`, ascending current-message `proposal_ids`, ascending `accepted_proposal_ids`, ascending canonical `eligible_proposal_ids`, `proposal_batch_hash`, `admission_audit_hash`, `ledger_hash`, `eligibility_hash`, nullable `projection_consistency_hash`, nullable `modifier_bundle_hash`, `diffusion_evidence_hash`, nullable `projection_audit_hash`, nullable `no_projection_reason` |
| `NP` / `kp.negotiation-proposal-batch.v1` | `negotiation_proposal_batch`; exactly `negotiation-proposal-batch.v1` | `run_id`, `session_id`, `tick`, fixed `source_hashes` tuple `(messages_hash, admission_audit_hash, ledger_hash)`, immutable `proposal_claim_tuples` ordered by `proposal_id` UTF-8 bytes, `proposal_count`, `batch_hash` |
| `AC` / `kp.negotiation-admission-consistency.v1` | `consistency_audit`; exactly `consistency-audit.v3` with an exact `consistency-audit.v2` inner report | `run_id`, fixed role `admission`, integer `tick`, `evaluator_version`, non-null `agent_pack_id`, `agent_pack_hash`, `constraint_context_hash`, wrapper `audit_hash`, `inner_audit_hash`, `deterministic_result_hash`, ascending current-message `proposal_ids` and aligned `proposal_hashes`, ascending `accepted_proposal_ids`, ordered `decision_tuples`, `decision_count` |
| `EL` / `kp.negotiation-eligibility.v1` | `negotiation_eligibility`; exactly `negotiation-eligibility.v1` | `run_id`, `session_id`, `tick`, immutable ordered `decision_tuples`, `decision_count`, ascending `eligible_proposal_ids`, `eligible_proposal_count`, `eligibility_hash` |
| `PC` / `kp.negotiation-projection-consistency.v1` | `consistency_audit`; exactly `consistency-audit.v3` with an exact `consistency-audit.v2` inner report | `run_id`, fixed role `projection`, integer `tick`, `evaluator_version`, non-null `agent_pack_id`, `agent_pack_hash`, `constraint_context_hash`, wrapper `audit_hash`, `inner_audit_hash`, `deterministic_result_hash`, ascending `candidate_proposal_ids` and aligned `proposal_hashes`, ascending `accepted_proposal_ids`, ordered `decision_tuples`, `decision_count` |
| `MB` / `kp.action-modifier-bundle.v1` | `deterministic_action_modifiers`; exactly `hybrid-modifier-bundle.v2` in hybrid and negotiation | `run_id`, nullable `tick`, `bundle_hash`, `inner_bundle_hash`, `consistency_audit_hash`, ascending `accepted_proposal_ids`, uniquely lexicographically ordered by UTF-8 bytes of `(proposal_id, modifier_id, modifier_hash)` `modifier_tuples`, `modifier_count` |
| `ND` / `kp.narrative-diffusion.v1` | `narrative_diffusion`; exactly `narrative-diffusion.v2` | `run_id`, `session_id`, `tick`, `attempted`, ascending `input_proposal_ids` and aligned `input_proposal_hashes`, `narrative_diffusion_audit_hash`, `diffusion_request_hash`, `before_result_hash`, `after_result_hash`, ordered fixed-point `tone_delta_tuples`, `country_delta_tuples` and `application_tuples`, `application_count`, `diffusion_evidence_hash` |
| `CL` / `kp.commitment-ledger.v1` | `commitment_ledger`; exactly `commitment-ledger.v2` in negotiation and both hybrid modes | `run_id`, nullable `session_id`, nullable `tick`, `ledger_hash`, `ledger_entry_count`, immutable entries ordered by `commitment_id` UTF-8 bytes, each exactly `(commitment_id, commitment_hash, status, action_type, party_agent_ids, terms_hash, source_proposal_id, source_proposal_hash, source_message_id, source_message_hash, source_admission_tick, source_admission_audit_hash)`; the hybrid v2 wrapper has the canonical run ID, null `session_id`/`tick`, empty entries and count zero |
| `PA` / `kp.projection-audit.v1` | outside negotiation, `agent_action_projection_audit`; exactly `agent-action-projection-audit.v2`. In negotiation, `negotiation_projection_audit`; exactly `negotiation-projection-audit.v2` | One common closed claim shape: `run_id`, nullable `session_id`, nullable `tick`, `projection_mode`, `audit_hash`, `consistency_audit_hash`, nullable `modifier_bundle_hash`, ascending `proposal_ids` and aligned `proposal_hashes`, `proposal_count`, aligned `record_input_hashes`, immutable `record_claim_tuples`, `record_count`, ascending `projected_proposal_ids` and aligned `projected_semantic_key_hashes`, `projected_count`, immutable `modifier_tuples`, `modifier_count`, `before_result_hash` and `final_result_hash` |
| `HR` / `kp.hybrid-replay.v1` | `hybrid_replay_record`; exactly `hybrid-replay-record.v2` | `run_id`, `engine_mode`, fixed `replay_source_kind = stored_only`, fixed `provider_calls_required = 0`, `replay_hash`, `proposal_batch_hash`, `baseline_result_hash`, pre-`hybrid_trace` `final_result_hash`, persisted traced `full_source_run_hash`, `consistency_audit_hash`, `modifier_bundle_hash`, `projection_audit_hash`, `ledger_hash`, ascending `accepted_proposal_ids` |
| `NR` / `kp.negotiation-replay.v1` | `negotiation_replay`; exactly `negotiation-replay.v2` | `run_id`, `session_id`, `replay_hash`, `baseline_result_hash`, `final_result_hash`, ordered `round_hashes`, `proposal_batch_hashes`, `admission_audit_hashes`, `ledger_hashes`, `eligibility_hashes`, nullable `projection_consistency_hashes`, nullable `modifier_bundle_hashes`, `diffusion_evidence_hashes`, nullable `projection_audit_hashes`, nullable `message_chain_head`, fixed `provider_calls_required = 0` |

The complete `negotiation-replay.v2` payload is closed and has exactly these
top-level keys (all are required): `schema_version`, `run_id`, `session_id`,
`baseline_result_hash`, `final_result_hash`, `round_hashes`,
`proposal_batch_hashes`, `admission_audit_hashes`, `ledger_hashes`,
`eligibility_hashes`, `projection_consistency_hashes`,
`modifier_bundle_hashes`, `diffusion_evidence_hashes`,
`projection_audit_hashes`, `message_chain_head`, `provider_calls_required`,
and `replay_hash`. The first two fields are the exact request coordinates;
all nine vectors have length `T` and the null rules in the registry row apply;
`message_chain_head` is nullable only when the authenticated six-tick message
chain is empty; `provider_calls_required` is the JSON integer `0`; and
`replay_hash` is the only digest field. Unknown or omitted keys fail before
any claim extraction or replay.

Only the nine `NR` vectors explicitly listed in its registry row are tick
vectors. Each has length `T`, is in ascending tick order and preserves a
`null` slot exactly for a tick where its conditional proof category is
forbidden; the six unconditional vectors contain no null. No other field
ending in `*_hashes` is implicitly a tick vector. A proposal-aligned ID/hash
pair has equal length, preserves the stated proposal-ID order and permits no
null, and every proposal-aligned ID is unique. Every named count equals the
length of its corresponding tuple. In particular, `RR.message_count`,
`EL.decision_count`, `EL.eligible_proposal_count`, `NP.proposal_count`,
`PB.proposal_count`, every Consistency `decision_count`,
`ND.application_count`, `CL.ledger_entry_count`, `MB.modifier_count`, and all
four PA counts are recomputed from their corresponding tuples; they are not
trusted payload counters. Every count equality applies even when the tuple is
empty. `PA.record_input_hashes`, `PA.record_claim_tuples`, `PA.proposal_ids`
and `PA.proposal_hashes` have the same length and positional order;
`PA.projected_semantic_key_hashes` has exactly the length and positional order
of `projected_proposal_ids`. The extractor recomputes every payload hash over
the source schema's declared canonical preimage before exposing it.

`agent-runtime-result.v1` already contains the required complete proposals,
invocations, `run_id` and `runtime_hash`, so AR pins that exact v1 source rather
than introducing a wrapper. `proposal_hashes` are `H(complete_proposal)` and
`invocation_hashes` are `H(complete_invocation)` after exact v1 validation;
their IDs and counts are extracted from those complete vectors. A missing
`run_id`, even on an empty runtime result, cannot be supplied by its Artifact
envelope.

`kernel-proposal-batch.v1` is the one PB wrapper for all four PB-producing
engine modes. Its complete fields are `schema_version`, `run_id`,
`source_kind`, nullable `source_runtime_hash`, nullable
`source_mock_batch_hash`, `proposal_ids`, `proposal_hashes`, `proposals`,
`proposal_count` and `batch_hash`; additional fields fail. `source_kind` is
exactly `mock_batch` for `mock_agent` and `agent_runtime` for
`controlled_agent`, `hybrid` and `hybrid_recorded`. Exactly one source hash is
non-null: the mock path has only the recomputed complete
`mock-agent-batch.v1` source hash, while the runtime path has only the
outer-verified AR `runtime_hash`. The aligned vectors are derived from the
complete canonical proposals, each `proposal_hash = H(complete_proposal)`, and
`proposal_count` is their common length. An empty batch still contains its
actual `run_id`, source kind and one source hash. Its exact digest is:

Before deriving those vectors or invoking FC, Run Control requires every
complete PB proposal's strict `proposal.run_id` to equal the wrapper `run_id`
and the canonical lifecycle run `R`. This check occurs before any proposal is
passed to FC or an adapter. A Provider-supplied run coordinate is not authority:
a mismatch fails closed and is never rewritten from the Artifact envelope,
request or another proposal.

```text
PB.batch_hash = H({"schema_version":"kernel-proposal-batch.v1",
 "run_id":run_id,"source_kind":source_kind,
 "source_runtime_hash":source_runtime_hash,
 "source_mock_batch_hash":source_mock_batch_hash,
 "proposal_ids":proposal_ids,"proposal_hashes":proposal_hashes,
 "proposals":complete_proposals,"proposal_count":proposal_count})
```

`hybrid-modifier-bundle.v2` is the one MB wrapper in both hybrid modes and
negotiation. Its complete fields are `schema_version`, `run_id`, nullable
`tick`, `consistency_audit_hash`, complete `inner_bundle`,
`inner_bundle_hash`, `accepted_proposal_ids`, complete `modifiers`, complete
`scenario_patch`, `modifier_tuples`, `modifier_count` and `bundle_hash`.
`inner_bundle` is exactly a `hybrid-modifier-bundle.v1`; its unchanged v1 hash
is recomputed and equals both `inner_bundle.bundle_hash` and
`inner_bundle_hash`. The inner v1 accepted-ID and modifier sequences retain
their unchanged legacy `(turn, id)` order. The outer v2
`accepted_proposal_ids` tuple is instead unique and sorted by proposal-ID UTF-8
bytes. Across the two layers, only the accepted-ID sets and the unique per-ID
complete-modifier mappings must be equal; their sequence order is deliberately
not compared field-for-field. The outer `scenario_patch` still equals the
inner scenario patch field-for-field. Outer modifier order and tuples are
derived from the complete modifiers, not accepted from parallel caller lists.
The outer digest is exactly:

```text
MB.bundle_hash = H({"schema_version":"hybrid-modifier-bundle.v2",
 "run_id":run_id,"tick":tick,
 "consistency_audit_hash":consistency_audit_hash,
 "inner_bundle":complete_inner_v1_bundle,
 "inner_bundle_hash":inner_bundle_hash,
 "accepted_proposal_ids":accepted_proposal_ids,"modifiers":modifiers,
 "scenario_patch":scenario_patch,"modifier_tuples":modifier_tuples,
 "modifier_count":modifier_count})
```

Both PA source schemas expose the same closed claim superset. Each
`record_claim_tuple` has exactly `(proposal_id, proposal_hash, input_hash,
decision, rule_version, outcome, rejection_reason, projection_status,
projection_hash, modifier_id, final_result_hash)` in that order. Each complete
v2 source record has exactly those eleven named keys in that order-independent
JSON object shape; every key is present, and `proposal_id`, `proposal_hash`,
`input_hash`, `decision`, `rule_version`, `outcome`, `projection_status` and
`final_result_hash` are always non-null. The other three keys obey this complete truth table (`non-null`
means a value is required; `null` means the key is required with JSON null):

| `outcome` | `projection_status` | Pair | `projection_hash` | `modifier_id` | `rejection_reason` |
|---|---|---|---|---|---|
| `accepted` | `projected` | allowed | non-null | non-null | null |
| `accepted` | `not_projected` | allowed | null | null | null |
| `rejected` | `blocked` | allowed | null | null | non-null |
| `constrained` | `constrained` | allowed | null | null | non-null |
| `expired` | `expired` | allowed | null | null | non-null |
| `accepted` | `constrained`, `blocked` or `expired` | forbidden | forbidden record | forbidden record | forbidden record |
| `rejected` | `not_projected`, `projected`, `constrained` or `expired` | forbidden | forbidden record | forbidden record | forbidden record |
| `constrained` | `not_projected`, `projected`, `blocked` or `expired` | forbidden | forbidden record | forbidden record | forbidden record |
| `expired` | `not_projected`, `projected`, `constrained` or `blocked` | forbidden | forbidden record | forbidden record | forbidden record |

There are no other `outcome` or `projection_status` values. After FC or PC has
been recomputed, PA aligns only the pre-projection decision fields shared with
that Consistency decision: `proposal_id`, `proposal_hash`, `input_hash`,
`decision`, `rule_version`, `outcome` and `rejection_reason`. PA's
`projection_status`, `projection_hash` and `modifier_id` are not equal to, and
are never copied from, any FC/PC fields; Consistency has no authoritative
`modifier_id` at all. Run Control next recomputes MB where the mode requires
one and reconstructs Projection Audit records from that verified decision and
bundle. An accepted decision with a unique recomputed MB modifier derives
`projected`, that modifier's `modifier_hash` and its `modifier_id`; an accepted
audit-only decision with no bundle derives `not_projected` and two nulls. A
rejected, constrained or expired decision derives respectively `blocked`,
`constrained` or `expired`, null projection hash/modifier ID and the aligned
non-null rejection reason. The constructor and verifier enforce the complete
truth table above, reject any MB membership inconsistent with it and recompute
the PA audit hash from these derived complete records.

A projected record's proposal ID appears in the aligned projected vectors and
its `modifier_id` identifies that proposal's unique PA/MB modifier tuple; a
non-projected record appears in neither projected vector nor a modifier tuple.
For a projected record, `projection_hash` equals the `modifier_hash` in that
unique tuple; it is not an independently asserted projection digest. Every
record's `final_result_hash` equals the enclosing PA payload's top-level
`final_result_hash`. A mismatch in a pre-projection equality, the truth table,
or an MB-derived projection field fails even when PA, Consistency and modifier
payloads have each been locally rehashed.
The source payload keeps the aligned complete `records`, and Run Control
recomputes each tuple.
`input_hash` and `proposal_hash` both equal `H(complete_source_proposal)` for
that ID. `record_input_hashes` is the aligned tuple of those exact extracted
`input_hash` values, so every record authenticates one and only one PB or NP
proposal. Every PA has one record per `proposal_ids` entry in the same order
and no other record.

The complete keys of both PA v2 payloads are `schema_version`, `run_id`,
nullable `session_id`, nullable `tick`, `projection_mode`,
`consistency_audit_hash`, nullable `modifier_bundle_hash`, `proposal_ids`,
`proposal_hashes`, `proposal_count`, `projected_proposal_ids`,
`projected_semantic_key_hashes`, `projected_count`, `modifier_tuples`,
`modifier_count`, `records`, `record_count`, `before_result_hash`,
`final_result_hash` and `audit_hash`. Their common digest formula is:

```text
PA.audit_hash = H({"schema_version":schema_version,"run_id":run_id,
 "session_id":session_id,"tick":tick,"projection_mode":projection_mode,
 "consistency_audit_hash":consistency_audit_hash,
 "modifier_bundle_hash":modifier_bundle_hash,"proposal_ids":proposal_ids,
 "proposal_hashes":proposal_hashes,"proposal_count":proposal_count,
 "projected_proposal_ids":projected_proposal_ids,
 "projected_semantic_key_hashes":projected_semantic_key_hashes,
 "projected_count":projected_count,"modifier_tuples":modifier_tuples,
 "modifier_count":modifier_count,"records":complete_records,
 "record_count":record_count,"before_result_hash":before_result_hash,
 "final_result_hash":final_result_hash})
```

For `agent-action-projection-audit.v2`, `session_id` and `tick` are always
present and null. `mock_agent` and `controlled_agent` fix
`projection_mode = "audit_only"`, require a null modifier-bundle hash, and use
empty projected-ID, semantic-hash and modifier tuples with zero corresponding
counts. `hybrid` and `hybrid_recorded` fix `projection_mode = "hybrid"`, require
a non-null modifier-bundle hash and use aligned projected semantic hashes. For
`negotiation-projection-audit.v2`, `session_id` and integer `tick` are non-null,
`projection_mode = "negotiation"`, and the modifier-bundle hash is non-null. A
hybrid or negotiation projection that accepts nothing still has empty
projected-ID, semantic-hash and modifier tuples and zero counts, never null
tuples. `proposal_ids`, `proposal_hashes`, `record_input_hashes`, records and
record claim tuples are likewise always arrays, including when empty. No proof
schema changes shape between these cases.

For each projected ID in a `hybrid` or `hybrid_recorded` PA, Run Control finds
the unique complete proposal with that ID in authenticated `PB.proposals` and
recomputes the semantic-key hash from exactly the same preimage used by NP:
`H({"actor_id":actor_id,"action_type":action_type,
"target_ids":ascending_target_ids,"parameters":validated_parameters})`.
The result must equal the positionally aligned
`PA.projected_semantic_key_hashes` value. A missing or duplicate PB lookup, an
invalid proposal, a target-order mismatch or a semantic-hash mismatch fails
closed even when the PB, PA and enclosing proof hashes have been recomputed.
No stored semantic hash supplies authority; the complete PB proposal is the
sole semantic-preimage source.

The two top-level result hashes of every non-negotiation PA are
mode-governed state coordinates, not caller descriptions. In `mock_agent` and
`controlled_agent`, `PA.before_result_hash = PA.final_result_hash =
baseline_projection.source_run_hash = final_projection.source_run_hash`; the
baseline and final projections therefore authenticate the same complete
source result. In `hybrid` and `hybrid_recorded`,
`PA.before_result_hash = HR.baseline_result_hash` and
`PA.final_result_hash = HR.final_result_hash`, where the latter is the
canonical final result before `hybrid_trace` is attached. These are value
equalities against the independently reconstructed replay coordinates; PA
does not obtain numeric authority by restating either HR field.

`hybrid-replay-record.v2` has exactly the fields in its registry row plus
`schema_version`; `engine_mode` is `hybrid` or `hybrid_recorded`,
`replay_source_kind` is `stored_only`, and `provider_calls_required` is strict
integer zero. Its exact digest is:

```text
HR.replay_hash = H({"schema_version":"hybrid-replay-record.v2",
 "run_id":run_id,"engine_mode":engine_mode,
 "replay_source_kind":"stored_only","provider_calls_required":0,
 "proposal_batch_hash":proposal_batch_hash,
 "baseline_result_hash":baseline_result_hash,
 "final_result_hash":final_result_hash,
 "full_source_run_hash":full_source_run_hash,
 "consistency_audit_hash":consistency_audit_hash,
 "modifier_bundle_hash":modifier_bundle_hash,
 "projection_audit_hash":projection_audit_hash,"ledger_hash":ledger_hash,
 "accepted_proposal_ids":accepted_proposal_ids})
```

This digest has one acyclic construction order. Run Control first reconstructs
the canonical pre-`hybrid_trace` result and recomputes the unchanged
`hybrid-replay-record.v1.replay_hash`. It then attaches the legacy
`hybrid_trace`; the only replay digest permitted in that trace is that legacy
v1 `replay_hash`. In particular, the trace contains neither `HR.replay_hash`
nor `full_source_run_hash`, nor any value derived from the v2 HR. Run Control
next canonicalizes the complete traced source result and computes
`full_source_run_hash`, and only after that constructs and hashes the complete
HR v2 payload above. The trace is never rewritten after HR v2 construction, so
neither digest's preimage contains itself, directly or transitively.

`consistency-audit.v3` is one closed wrapper, used for FC, AC and PC. Its
complete fields are `schema_version`, `run_id`, `role`, nullable `tick`,
`evaluator_version`, nullable mode-governed `agent_pack_id`,
`agent_pack_hash`, `constraint_context_hash`, `proposal_ids`, aligned `proposal_hashes`, complete
`inner_audit`, `inner_audit_hash` and wrapper `audit_hash`; additional fields
fail validation. The inner report is exactly `consistency-audit.v2`, including
when its proposal vector is empty; v1 is never accepted inside this wrapper.
`role` is exactly `final`, `admission` or `projection`; only `final` has a null
tick, while `admission` and `projection` require the outer integer tick. The
inner source is always exactly `consistency-audit.v2`. Its `run_id` is exactly
outer `run_id` for `final`, exactly
`{run_id}:tick:{t}` for admission and exactly
`{run_id}:projection:{t}` for projection. Its evaluator version equals the
outer version and the runtime-profile pin; the outer Agent Pack ID/hash and
constraint-context hash equal the same post-baseline resolver outputs used for
that inner evaluation. They are all null only for deterministic FC and all
non-null otherwise. The outer role/tick pair, inner run coordinate, evaluator
version and context identity are jointly checked and may not be caller-restated
or mixed across reports.

The complete inner report's `created_at` is synthetic contract data, never a
wall-clock read: FC uses exactly `2000-01-01T00:00:00.000Z`; AC at integer tick
`t` uses the same UTC epoch plus `2t - 1` seconds; and PC at tick `t` uses it
plus `2t` seconds. The initial persisted evaluation and every recovery, retry
or finalization recomputation pass the identical derived string to the v2
evaluator. That `created_at` remains a field of `complete_inner_audit` and thus
participates in the v3 wrapper audit preimage below; it may not be removed,
replaced by the stored Artifact timestamp or ignored during field-for-field
comparison. `inner_audit_hash` is the inner report's own
`audit_hash`, recomputed by the unchanged v2 algorithm. The wrapper vectors are
made from the complete authenticated proposals evaluated by that inner report
and may not be reconstructed from its decisions.
`decision_tuples` are extracted from the complete inner decisions in proposal
order as `(proposal_id, proposal_hash, decision, input_hash, rule_version,
outcome, rejection_reason, projection_status, projection_hash)`; their
proposal hash and input hash both equal `H(complete_proposal)`. The wrapper
digest is exactly:

```text
FC/AC/PC.audit_hash = H({"schema_version":"consistency-audit.v3","run_id":run_id,
   "role":role,"tick":tick,"evaluator_version":evaluator_version,
   "agent_pack_id":agent_pack_id,"agent_pack_hash":agent_pack_hash,
   "constraint_context_hash":constraint_context_hash,
   "proposal_ids":proposal_ids,
   "proposal_hashes":proposal_hashes,"inner_audit":inner_audit,
   "inner_audit_hash":inner_audit_hash})
```

Here and below, `H(value) = sha256(canonical_json(value))`; the displayed
objects fix the complete object keys and values in each hash preimage, and the
canonical JSON key-sort rule, not display order, fixes bytes. Arrays preserve
the specified order. `schema_version` participates everywhere it is displayed
and may not be omitted. The exact new source hashes are:

`negotiation-proposal-batch.v1` is a closed top-level object with exactly these
fields: `schema_version`, `run_id`, `session_id`, `tick`, `source_hashes`,
`proposal_claim_tuples`, `proposal_count`, `proposals` and `batch_hash`.
`schema_version` is the exact JSON string
`"negotiation-proposal-batch.v1"`; `run_id` and `session_id` are non-empty
canonical ID strings; `tick` is a strict JSON integer in `1..6`;
`source_hashes` is a three-element JSON array of non-null lowercase SHA-256
strings in the fixed order defined below; `proposal_claim_tuples` is a JSON
array of the closed `NegotiationProposalSource` items defined below, ordered by
unique `proposal_id` UTF-8 bytes; `proposal_count` is a strict non-negative
JSON integer; `proposals` is a JSON array of complete canonical
`AgentActionProposal` objects in the same positional order; and `batch_hash` is
a non-null lowercase SHA-256 string. Every field is required and non-null;
both proposal arrays remain present when empty, while `source_hashes` always
has exactly three elements. Additional keys, duplicate keys,
coercions and omitted keys fail validation. The stored `proposal_count` must
equal both array lengths, and each claim tuple's ID and `proposal_hash` must
equal its aligned complete proposal's ID and recomputed hash. The stored
`batch_hash` is always recomputed from the following complete preimage; neither
stored counter nor stored digest is trusted.

- `RR.messages_hash = H({"schema_version":"negotiation-round.v2",
  "run_id":run_id,"session_id":session_id,"tick":tick,
  "message_tuples":[[seq,message_id,message_hash],...]})`;
- `NP.batch_hash = H({"schema_version":"negotiation-proposal-batch.v1",
  "run_id":run_id,"session_id":session_id,"tick":tick,
  "source_hashes":[RR.messages_hash,AC.audit_hash,CL.ledger_hash],
  "proposal_claim_tuples":proposal_claim_tuples,
  "proposal_count":proposal_count,
  "proposals":aligned_complete_proposals})`;
- `negotiation-round.v2` has exactly `schema_version`, `run_id`, `session_id`,
  `round_id`, `tick`, `input`, `input_hash`, `output`, `output_hash` and
  `round_hash`. `complete_input` has exactly `before_result_hash`,
  `message_tuples`, `messages`, `messages_hash`, `message_count`,
  `proposal_ids`, `accepted_proposal_ids`, `proposal_batch_hash`,
  `admission_audit_hash`, `ledger_hash`, `eligibility_hash` and
  `eligible_proposal_ids`. `messages` contains the complete canonical message
  objects aligned one-for-one with `message_tuples`. `complete_output` has
  exactly `projection_consistency_hash`, `modifier_bundle_hash`,
  `diffusion_evidence_hash`, `projection_audit_hash`, `no_projection_reason`
  and `after_result_hash`. All nullable output keys are present even when null;
  unknown or omitted input/output keys fail. `RR.input_hash` is
  `H({"schema_version":"negotiation-round.v2","run_id":run_id,
  "session_id":session_id,"round_id":round_id,"tick":tick,
  "input":complete_input})`; `RR.output_hash` uses the same fixed outer keys
  with `"output":complete_output` in place of `"input":complete_input`, and
  `RR.round_hash = H({"schema_version":"negotiation-round.v2",
  "run_id":run_id,"session_id":session_id,"round_id":round_id,"tick":tick,
  "input_hash":RR.input_hash,"output_hash":RR.output_hash})`. Digest fields
  are not members of their own `complete_input` or `complete_output` object;
- `CL.ledger_hash` uses the exact v2 preimage defined by the CL state machine
  below, including complete entries and their complete event chains;
- negotiation PA uses the one common complete `PA.audit_hash` preimage above
  with `schema_version = "negotiation-projection-audit.v2"`; no reduced,
  count-omitting negotiation preimage exists;
- `NR.replay_hash = H({"schema_version":"negotiation-replay.v2",
  "run_id":run_id,"session_id":session_id,
  "baseline_result_hash":baseline_result_hash,
  "final_result_hash":final_result_hash,"round_hashes":round_hashes,
  "proposal_batch_hashes":proposal_batch_hashes,
  "admission_audit_hashes":admission_audit_hashes,
  "ledger_hashes":ledger_hashes,"eligibility_hashes":eligibility_hashes,
  "projection_consistency_hashes":projection_consistency_hashes,
  "modifier_bundle_hashes":modifier_bundle_hashes,
  "diffusion_evidence_hashes":diffusion_evidence_hashes,
  "projection_audit_hashes":projection_audit_hashes,
  "message_chain_head":message_chain_head,"provider_calls_required":0})`;
- `ND.narrative_diffusion_audit_hash` and `ND.diffusion_evidence_hash` use the
  exact preimages in the fixed-point subsection below.

The six RR coordinates are derived, not accepted labels. For each exact
`t in 1..6`, `RR[t].tick = t` and
`RR[t].round_id = "round_" +
H({"session":session_id,"tick":t})[0:20]`. All six derived round IDs must be
pairwise unique, use the same `session_id` as the negotiation request and NR,
and occur in ascending-tick RR order. The suffix is exactly the first 20
lowercase hexadecimal characters of the displayed digest. A collision,
caller-selected ID, wrong tick or different session fails closed even if every
RR-local hash is recomputed.

`negotiation-round.v2` retains the complete canonical message wrappers aligned
one-for-one with its message tuples. Each wrapper has exactly `message_id`,
`session_id`, `round_id`, `tick`, `seq`, `sender_agent_id`,
`recipient_agent_ids`, `message_type`, `visibility`, nullable
`parent_message_id`, nullable `proposal_id`, `narrative`, `payload`, `provider`,
`model`, `latency_ms`, `estimated_tokens`, `fallback_used`, nullable
`previous_hash`, `message_hash` and `created_at`; unknown or omitted wrapper
keys fail. `payload` is exactly `{}` when there is no proposal and exactly
`{"proposal":complete_canonical_proposal}` otherwise, and `proposal_id` is null
in the first case and equals that complete proposal's ID in the second. Run
Control validates the complete wrapper, all closed message domains and strict
integer fields, not merely the subset used by the message digest.

The existing message identity digest is closed and is recomputed as:

```text
message_hash = H({"tick":tick,"seq":seq,
 "sender_agent_id":sender_agent_id,
 "recipient_agent_ids":recipient_agent_ids,"message_type":message_type,
 "visibility":visibility,"parent_message_id":parent_message_id,
 "proposal":complete_canonical_proposal_or_null,"narrative":narrative,
 "previous_hash":previous_hash})
message_id = "msg_" + message_hash[0:20]
```

The message-ID suffix is exactly the first 20 lowercase hexadecimal characters
of the recomputed message hash. Every message stored in `RR[t]` has
`message.session_id = RR[t].session_id`,
`message.round_id = RR[t].round_id` and `message.tick = RR[t].tick`; these
wrapper-coordinate equalities are checked before the message may authorize a
proposal or CL transition. Each aligned tuple is exactly the wrapper's
`(seq, message_id, message_hash)` and is ordered by its session-global `seq`.

Across the union of all six RR message arrays for one session, global `seq` is
unique and contiguous `1..n`. In that global order the first message has
`previous_hash = null`, and each later message's `previous_hash` equals the
immediately preceding message's authenticated `message_hash`, including across
a tick boundary. A per-tick message tuple retains that global sequence number;
it is never reset or renumbered from one within the tick. Each session message
occurs in exactly one RR array, so a duplicate, omission, gap, reordered tuple,
broken predecessor or coordinate mismatch fails the complete RR wrapper even
if `messages_hash`, `input_hash`, `round_hash` and the Artifact hashes are all
recomputed. Sender, recipient, parent and response authorization may be read
only from these authenticated complete wrappers, never from an unbound
database lookup. Global `seq` order governs only message-chain
authentication/authorization and the CL transition walk; it does not govern
the proposal vector passed to AC, NP or any later proposal consumer.

`NR.message_chain_head` is nullable: it is null if and only if the complete
six-tick authenticated message set is empty. Otherwise it is the authenticated
`message_hash` of the unique message with the greatest strict-integer global
`seq`; it is not the last message in artifact order, tick order or caller input.

Only schema-declared non-integer quantitative fields in a new v2 or v3 payload
use the canonical arbitrary-precision Decimal rule above; binary float tokens
and non-canonical decimal lexemes fail instead of being normalized. Integer
coordinates and counters, including tick, message/event `seq` and every
`*_count`, remain strict JSON integers, while fixed-point units remain strict
signed int64 integers. An embedded legacy v1 object's own digest is still
recomputed with that v1 schema's unchanged numeric serialization; the enclosing
v2/v3 representation does not change its legacy digest. Existing v1 and Golden
Scenario hash algorithms and bytes remain unchanged.

`NegotiationProposalSource` is the closed immutable item type inside
`NP.proposal_claim_tuples`. Its fields, in this exact order, are `proposal_id`,
`proposal_hash`, `source_message_id`, `source_message_hash`, `action_type`,
`action_class`, `semantic_key_hash`, `source_kind`, nullable `commitment_id`,
`source_admission_tick` and `source_admission_audit_hash`. `source_kind` is
exactly `current_message` or `active_commitment_origin`. A `current_message`
tuple has `commitment_id = null`, `source_admission_tick = t` and
`source_admission_audit_hash = AC[t].audit_hash`. An
`active_commitment_origin` tuple has a non-null `commitment_id`,
`source_admission_tick < t`, and an action class exactly
`bilateral_commitment`; no other class may use that discriminator. The fixed
positions of `NP.source_hashes` are `RR[t].messages_hash`, `AC[t].audit_hash`
and `CL[t].ledger_hash`. NP claims contain no map, list, float or complete
proposal object: their only composite values are the fixed tuples allowed by
the Kernel claim contract.

The authenticated NP Artifact, and only that Artifact within this proof
contract, retains the complete canonical `AgentActionProposal` object aligned
with every claim tuple. `proposal_hash` is SHA-256 over that complete object.
`semantic_key_hash` is SHA-256 over canonical JSON of exactly `actor_id`,
`action_type`, ascending `target_ids`, and the validated `parameters` object.
For lifecycle run `R`, every complete proposal retained by `NP[t]` has strict
`proposal.run_id = R`. A `current_message` proposal additionally has strict
`proposal.turn = t`; it must already have those exact coordinates and unique,
ascending UTF-8 `target_ids` before AC is invoked. A Provider mismatch,
duplicate target or out-of-order target fails rather than being rewritten or
silently normalized. AC, NP, PC, MB, the production diffusion adapter and PA
all consume that identical ordered target tuple, so the real application order
and the audited semantic-key preimage cannot diverge. The legacy
`agent-action-proposal.v1` execution path and its hashes are unchanged.

An active commitment origin carries two authenticated coordinates rather than
trusting a Provider turn as the current one. If it was admitted at tick
`s < t`, the immutable source proposal in `RR[s]`, `NP[s]`, `AC[s]`, the
current `NP[t]` entry and the current CL entry has `run_id = R` and
`turn = s = source_admission_tick`; its unchanged hash equals both the current
NP tuple's `proposal_hash` and `CL.source_proposal_hash`, and the CL
`terms`/`terms_hash` bind those exact source bytes. The current injection tick
is stored separately as the authenticated wrapper coordinate `NP[t].tick = t`
and the corresponding RR/proof tick; it is never written into
`proposal.turn`. Only Run Control may inject this verified immutable source;
the rule is not a repair rule for a current Provider proposal.

Run Control is likewise the sole coordinate authority for deterministic
adapters. A negotiation `MB[t]` has `run_id = R` and `tick = t` from the
authenticated request and RR/NP/PC proof coordinates; an `ND[t]` has those same
run/tick values plus the authenticated negotiation `session_id`. Hybrid MB has
`run_id = R` and null tick. The Action Adapter, expiry walk and diffusion
adapter receive these authenticated coordinates explicitly. They never derive
the current run or tick from a Provider proposal, including either a current
message's turn or an active origin's source-admission turn, nor from a message
body, legacy inner bundle or stored application. Any stored wrapper or complete
input that disagrees fails before it can drive expiry, MB or ND construction.

The action classification is closed and versioned here. There is no default
case or substring inference:

| `action_type` | `action_class` |
|---|---|
| `diplomatic_signal` | `deterministic_modifier` |
| `sanction_proposal` | `deterministic_modifier` |
| `trade_reroute_request` | `deterministic_modifier` |
| `alliance_request` | `bilateral_commitment` |
| `humanitarian_offer` | `bilateral_commitment` |
| `deescalation_offer` | `bilateral_commitment` |
| `public_narrative` | `public_narrative` |
| `intelligence_request` | `audit_only` |
| `alliance_response` | `alliance_response` |

The bilateral boundary is closed. Only a proposal whose table-derived class is
`bilateral_commitment` may be a commitment origin. Its authenticated origin
message must have `visibility = "direct"` and exactly one
`recipient_agent_ids` member, hereafter `recipient`, and `recipient` must differ
from `origin.sender_agent_id`. The complete proposal has
`actor_id = origin.sender_agent_id` and identifies exactly one target party.
Using only the regenerated-and-verified complete Agent Pack's actor/country mapping, that target
party must resolve to exactly one Agent ID and that ID must equal `recipient`;
zero, ambiguous or different-Agent resolutions fail closed. No first profile,
role preference, database lookup or caller-supplied mapping is a fallback.
`party_agent_ids` is exactly the two distinct IDs
`(origin.sender_agent_id, recipient)` sorted by ascending UTF-8 bytes. A public
origin, a zero- or multi-recipient origin, a self-recipient, an actor mismatch,
a non-bilateral action class or any other two-party construction fails before
AC is invoked and cannot create a CL entry.

NP construction is deterministic. Run Control first authenticates the tick
messages by `(seq, message_id UTF-8 bytes)`, collects every embedded proposal,
validates canonical run/turn coordinates, proposal-ID uniqueness and the
unique/ascending-target rule before AC, and derives its closed action class and
hashes. It then sorts that complete
current-message proposal vector by proposal-ID UTF-8 bytes before invoking AC;
AC's proposal IDs/hashes and decisions preserve exactly that order. After AC
and the CL transitions below, NP creates one `current_message` candidate for
every such proposal whether AC accepts it or not, in the identical
proposal-ID order. It then walks `CL[t]` by `commitment_id` UTF-8 bytes and creates one
`active_commitment_origin` candidate for every active entry whose admission
tick is earlier than `t`.

For an active origin admitted at tick `s`, Run Control loads the exact
`(seq, source_message_id, source_message_hash)` from `RR[s]`, the exact earlier
NP current-message tuple, the exact aligned proposal ID/hash accepted by
`AC[s]`, and the current `CL[t]` entry. The proposal ID/hash, source message
ID/hash, action type/class, semantic-key hash, admission tick/audit hash, full
source terms/terms hash and immutable source proposal bytes must agree
field-for-field across the four source bindings. The current injected proposal
equals that source proposal field-for-field, including `run_id = R` and
`turn = s = source_admission_tick`, and retains its source proposal hash. Its
current injection coordinate is only `NP[t].tick = t`. The earlier NP
discriminator is `current_message` with a null commitment ID; the current NP
discriminator is `active_commitment_origin` with the current CL commitment ID.

The current-message and active-origin sets must be disjoint by proposal ID.
Any overlap fails closed; there is no first-wins or source-preference
deduplication by ID. Within `NP[t]`, proposal IDs remain unique, but
`semantic_key_hash` values may repeat when and only when their recomputed
canonical semantic-key preimages are equal. Equal hashes with different
preimages are collisions and fail closed. NP performs no semantic grouping,
winner selection, loser classification or eligibility filtering over those
candidates. Its final claim tuple contains every current-message and active-
origin candidate exactly once, sorted only by proposal-ID UTF-8 bytes;
`proposal_count` includes all of them and its exact batch hash is defined
above. There is no NP winner/loser metadata or out-of-band side list. Only EL,
after applying its per-candidate precedence, groups the remaining preliminary
eligible candidates and selects the UTF-8-minimum proposal ID within each such
group.

Duplicate current message IDs, duplicate proposal IDs within or across sources,
multiple active commitments for one source proposal, one ID resolving to
different canonical bytes or hashes at one coordinate, one hash resolving to
different canonical preimages, or one message origin resolving to different
bytes fails closed.
Repetition of an active origin in a later tick is allowed only with exactly the
same immutable source proposal, message, admission and commitment-origin
bindings, including its unchanged source-admission turn and proposal hash; only
the authenticated NP/RR/proof injection tick changes.
Unknown or
mismatched action types/classes, mismatched NP/AC/CL proposal hashes, and any
undeclared duplicate ID/entry/decision or hash collision in RR, NP, AC, CL, EL,
PC, MB, ND or PA also fails closed before Kernel invocation. The only permitted
repeated hash here is an NP `semantic_key_hash` whose recomputed canonical
preimage is equal; its same-tick outcome is governed solely by the EL rule
below.

Each negotiation CL entry has exactly the v2 claim fields and order stated in
the registry. Its authenticated payload additionally retains the complete
proposal in `terms` and the complete event chain. Its claimed `action_type`
must derive `bilateral_commitment`, equal `terms.action_type` and equal the
origin proposal action type. Its claimed `party_agent_ids` must equal the exact
two-member UTF-8-sorted origin pair defined above; validation does not merely
deduplicate or sort an arbitrary stored collection. The immutable origin hashes
and derived ID are exactly:

```text
terms_hash = H({"schema_version":"commitment-ledger.v2","terms":terms})
commitment_hash = H({"schema_version":"commitment-ledger.v2",
  "session_id":session_id,"action_type":action_type,
  "party_agent_ids":party_agent_ids,
  "terms_hash":terms_hash,"source_proposal_id":source_proposal_id,
  "source_proposal_hash":source_proposal_hash,
  "source_message_id":source_message_id,
  "source_message_hash":source_message_hash,
  "source_admission_tick":source_admission_tick,
  "source_admission_audit_hash":source_admission_audit_hash})
commitment_id = "commit_" + commitment_hash[0:20]
```

The `commitment_hash` preimage has exactly those eleven keys and does not contain
`commitment_id`; `commitment_hash` is lowercase hexadecimal and `[0:20]` means
its first 20 hexadecimal characters, so the derived ID is non-recursive. Run Control
recomputes both values and rejects an ID/hash mismatch or a collision in which
one derived ID names different complete preimages. Thus the CL claim tuple and
`commitment_hash` both bind the exact action type, two parties, source proposal
ID/hash, authenticated origin message ID/hash and admission tick/audit hash;
the proposal hash binds the complete terms and the message hash binds the
complete direct-message sender/recipient fields. None of those facts may be
inferred from another proof or repaired after hashing.

For each commitment, event `seq` is contiguous `1..n` with no reused or skipped
integer; event 1 has status
`proposed`, uses the origin proposal message ID/hash and has
`actor_agent_id = origin.sender_agent_id`. Its `event_hash` is exactly
`H({"schema_version":"commitment-ledger.v2","commitment_id":commitment_id,
"tick":tick,"seq":seq,"status":status,"actor_agent_id":actor_agent_id,
"source_message_id":source_message_id,"source_message_hash":source_message_hash,
"previous_event_hash":previous_event_hash})`, where the first previous hash is
null. The proposed event and every response-caused event are message-caused and
use the exact authenticated message ID/hash that caused that event.
Message-caused events require both source-message fields; a deterministic
tick-expiry event requires both to be null, fixes
`actor_agent_id = "run_control"`, and is derived from the authenticated terms
and integer tick, never wall-clock time.

The only legal edges are `proposed -> active`, `proposed -> rejected`,
`proposed -> withdrawn`, `proposed -> expired`, `active -> withdrawn` and
`active -> expired`. `rejected`, `withdrawn` and `expired` are terminal and
have no successor. Reprocessing the same source-message ID/hash and status is
idempotent and adds no event; a changed hash, changed status or any other
same-state event fails closed. The entry status is exactly the last event
status.

A commitment may be created in `proposed` only for a proposal whose closed
class is `bilateral_commitment`, whose complete ID/hash occurs in the aligned
AC proposal vector and whose ID is accepted by that AC. A non-bilateral,
unaccepted or unauthorized source can neither create nor activate a
commitment. For a message-caused transition, the response message ID/hash is
the event source and its sender is the event actor; its `parent_message_id`
equals the origin source message ID and its tick is later. The response sender
must equal the origin's unique `recipient`, the response must have
`visibility = "direct"`, and its `recipient_agent_ids` must be exactly the
one-member tuple containing `origin.sender_agent_id`. A response from a third
party, to a third party, with zero or multiple recipients, or with any broader
membership-only match fails closed and appends no event. `accept`, `reject`,
`withdrawal` and `counteroffer` map respectively to `active`, `rejected`,
`withdrawn` and `rejected`, subject to the legal-edge table. Before activating
an `alliance_request`, the existing conflict policy is executed exactly: an
already-active `alliance_request` with the exact same UTF-8-sorted
`party_agent_ids` pair forces the candidate to `rejected` and records that
response source ID/hash; set coercion, a superset and a pair containing a third
party never match or authorize a transition. Other action types do not use
this policy.

`complete_entries` is ordered by commitment ID UTF-8 bytes, and every element
has exactly these keys and values:

```text
{"commitment_id":commitment_id,"commitment_hash":commitment_hash,
 "status":status,"action_type":action_type,
 "party_agent_ids":party_agent_ids,"terms":terms,"terms_hash":terms_hash,
 "source_proposal_id":source_proposal_id,
 "source_proposal_hash":source_proposal_hash,
 "source_message_id":source_message_id,"source_message_hash":source_message_hash,
 "source_admission_tick":source_admission_tick,
 "source_admission_audit_hash":source_admission_audit_hash,
 "events":[{"tick":tick,"seq":seq,"status":status,"actor_agent_id":actor_agent_id,
   "source_message_id":source_message_id,
   "source_message_hash":source_message_hash,
   "previous_event_hash":previous_event_hash,"event_hash":event_hash},...]}
```

Every `commitment-ledger.v2` source object has exactly `schema_version`,
`run_id`, nullable `session_id`, nullable `tick`, `entries`,
`ledger_entry_count` and `ledger_hash`; the count is recomputed from entries
and does not enter the ledger-hash preimage. `CL[t].ledger_hash` is exactly
`H({"schema_version":"commitment-ledger.v2","run_id":run_id,
"session_id":session_id,"tick":tick,"entries":complete_entries})`. Thus
the exact parties, action type, source message, source proposal and source
admission bindings participate in the CL claims, each entry's commitment hash
and the ledger hash preimage. The extracted non-null `CL.session_id` is that
exact preimage value and must equal the negotiation request/session identity.
The CL snapshot is taken after all tick transitions and before any projection
work.

Hybrid uses one exact `commitment-ledger.v2` empty wrapper:

```text
{"schema_version":"commitment-ledger.v2","run_id":R,"session_id":null,
 "tick":null,"entries":[],"ledger_entry_count":0,
 "ledger_hash":H({"schema_version":"commitment-ledger.v2","run_id":R,
                   "session_id":null,"tick":null,"entries":[]})}
```

Those are all wrapper keys. Run Control obtains `R` only from the canonical
lifecycle/request authority, writes that value into the new v2 wrapper, and on
read requires the closed payload's `run_id` to equal it. It never extracts,
infers or copies a run ID from a legacy ledger, legacy empty payload, Artifact
envelope or relationship. No legacy ledger is an inner object or input to this
hash. Negotiation uses the same exact v2 wrapper shape with non-null
session/tick coordinates and may not use the hybrid null-coordinate wrapper
even when its entries are empty.

The per-tick logical construction order, **GOV-CL-1**, is normative and
distinct from the canonical proof-reference order below. At the start of tick
`t`, before admitting any current message, Run Control walks the prior snapshot
entries in `commitment_id` UTF-8 order. For each entry whose prior status is
`proposed` or `active`, whose `terms.expires_after_turn` is non-null, and for
which strict integer `t > terms.expires_after_turn`, it appends exactly one
`expired` event with the null expiry source defined above. It then authenticates
all current messages and orders them by `(seq, message_id UTF-8 bytes)`, rejects
duplicate or out-of-order targets, collects their proposals, and sorts those
proposals by proposal-ID UTF-8 bytes before building `AC[t]`. It separately
walks the authenticated message `(seq, message_id)` order to create `proposed`
entries for accepted bilateral proposals and to authorize responses, apply the
alliance conflict rule and append legal message-caused transitions. Within each
commitment this message walk fixes event order and the next contiguous event
`seq`; no database iteration order participates, and message order never
reorders the AC/NP proposal vector.
Here `t` is the authenticated current RR/AC/CL proof coordinate and
`expires_after_turn` comes from the authenticated immutable source terms. A
Provider proposal's `turn`, a message payload coordinate or a stored event tick
cannot replace either operand or delay/accelerate expiry.
An entry expired at tick start is already terminal, so a conflicting response
later in the same tick is rejected as an illegal terminal-state response and
appends no event; it cannot reactivate or replace the entry. Run Control then
persists `CL[t]` as the post-transition, pre-projection snapshot, constructs
`NP[t]` and then `EL[t]`, runs `PC[t]` when eligibility requires it, executes and
persists `MB[t]`, invokes `ND[t]`, persists `PA[t]` when required, and seals
`RR[t]` only after all tick facts exist. Provider-free replay uses this same
total order.

`NegotiationEligibilityDecision` is the closed immutable item type inside
`EL.decision_tuples`. Its fields are, in exact order, the complete NP proposal
claim tuple, boolean `prior_projected`, `outcome`, and `decision_hash`; EL may
not restate, normalize or infer any candidate fact from RR, AC, CL, a message
payload or a cache. `outcome` is exactly one of `eligible`, `not_admitted`,
`inactive_commitment`, `audit_only`, `alliance_response`,
`already_projected` or `semantic_duplicate`. `decision_hash` is SHA-256 over
canonical JSON of `{"decision": [proposal_claim_tuple, prior_projected,
outcome]}`. Free-text reasons are forbidden.

The `negotiation-eligibility.v1` source object has exactly `schema_version`,
`run_id`, `session_id`, `tick`, `decisions`, `decision_count`,
`eligible_proposal_ids`, `eligible_proposal_count` and `eligibility_hash`.
`decisions` is the complete ordered array from which `decision_tuples` and the
ordered `decision_hashes` array are extracted; the two count fields are strict
integers recomputed from their arrays. Its exact digest is:

```text
EL.eligibility_hash = H({"schema_version":"negotiation-eligibility.v1",
 "run_id":run_id,"session_id":session_id,"tick":tick,
 "decision_hashes":decision_hashes,
 "eligible_proposal_ids":eligible_proposal_ids})
```

Those six keys are the complete eligibility-hash preimage; neither count nor
the complete decision objects enter it. The stored counts are nevertheless
required and recomputed as registry claims before this digest is accepted.
Each `decision_hash` is computed only after the complete precedence and
preliminary-candidate grouping below has produced the final outcome; EL then
recomputes `eligibility_hash` from that final ordered decision-hash vector and
the final eligible-ID vector. A tentative group winner or pre-filter candidate
can never enter either hash.

EL construction, **GOV-EL-1**, has exactly one decision for every NP proposal
claim tuple and no other candidate. Construction is stable: it walks the
complete NP tuple in stored proposal-ID order, emits one decision in that same
order, and never filters or deduplicates the decision vector. It first applies
this first-match precedence independently to each proposal: a
`current_message` proposal absent from `AC[t].accepted_proposal_ids` or with a
different AC proposal hash is `not_admitted`; an
`active_commitment_origin` without a field-for-field active `CL[t]` match and
the exact earlier accepting AC proof fails the entire EL construction;
`audit_only` and `alliance_response` classes receive their same-named outcomes;
a `bilateral_commitment` without an exact active `CL[t]` match is
`inactive_commitment`; a proposal ID in the prior projected-ID set is
`already_projected`; and a semantic key in the prior
projected-semantic-key set is `semantic_duplicate`.

Only proposals still unclassified after all of those checks are preliminary
eligible candidates. EL groups only that set by the recomputed canonical
semantic-key preimage. Within each group the proposal ID with minimum UTF-8
bytes is `eligible` and every other preliminary candidate is
`semantic_duplicate`. A lower proposal ID that is not admitted, belongs to an
excluded class, has an inactive commitment or was previously projected never
participates in the group and therefore cannot suppress a higher-ID
preliminary eligible proposal. An invalid active origin aborts construction
before grouping and can neither nominate nor suppress a winner. Every proposal,
including every excluded item and same-tick loser in a successfully constructed
EL, remains represented by one complete decision in the original NP order.

For every decision, `prior_projected` is true if and only if that proposal ID is
in the prior-PA projected-ID set; action class, admission, commitment state,
same-tick winner status and semantic-key membership cannot change that boolean.
The `semantic_duplicate` outcome is emitted only at either of its stated
positions: when an otherwise preliminary candidate's semantic key is in the
prior-PA projected-semantic set, or when it is not the UTF-8-minimum ID among
the remaining preliminary candidates with the same current-tick preimage.
Same-tick grouping neither reads nor updates either prior-PA seen set and
creates no extra or incomplete decision side channel. The `source_kind` discriminator
and nullable `commitment_id` are synchronized exactly: `current_message` if and
only if `commitment_id` is null, with admission tick `t` and `AC[t]` hash;
`active_commitment_origin` if and only if `commitment_id` is non-null, with an
earlier admission tick/hash and the exact active CL match. Any other
discriminator/null combination fails before an eligibility outcome is chosen.

At tick `t`, `seen_ids` is rebuilt solely from
`PA[s].projected_proposal_ids` for completed ticks `s < t`. For each such ID,
Run Control finds the unique canonical NP proposal claim tuple from tick `s`
and adds that tuple's `semantic_key_hash` to `seen_semantic_keys`; the value
must also equal the aligned `PA[s].projected_semantic_key_hashes` claim. A
missing or ambiguous NP lookup fails closed. Neither set is updated from NP
presence, AC acceptance, EL eligibility, same-tick winner selection, PC
acceptance, MB, ND, a session cache, an unprojected PA record or a failed
attempt. Thus PC rejection and same-tick duplicate classification never make an
ID or semantic key seen. `EL.eligible_proposal_ids` is the ascending UTF-8
ordering of decision IDs with outcome `eligible`.
`RR.proposal_batch_hash` equals `NP.batch_hash`; RR repeats the EL hash and
eligible IDs, and NR repeats the NP and EL hashes in tick order.

`narrative-diffusion.v2` is one closed authenticated object. Its top-level keys
are exactly, with every key required and no additional key permitted:

```text
schema_version, run_id, session_id, tick, attempted,
input_proposal_ids, input_proposal_hashes, core_audit,
narrative_diffusion_audit_hash, diffusion_request,
diffusion_request_hash, before_result_hash, after_result_hash,
tone_delta_tuples, country_delta_tuples, application_tuples,
application_count, diffusion_evidence_hash
```

`schema_version` is the exact string `"narrative-diffusion.v2"`; `run_id` and
`session_id` are non-empty strings equal to the authenticated negotiation
coordinates; `tick` is a strict JSON integer in `1..6`; and `attempted` is a
JSON boolean. `input_proposal_ids` is an array of unique non-empty strings in
ascending UTF-8 byte order, and `input_proposal_hashes` is an equal-length
positionally aligned array of lowercase 64-hex SHA-256 strings. `core_audit`
and `diffusion_request` are the complete closed objects below. All five named
top-level hashes are lowercase 64-hex strings. The three tuple members are JSON
arrays of the fixed tuple shapes below, and `application_count` is a strict
non-negative JSON integer equal to the length of `application_tuples`. A
missing key, JSON null, additional key, boolean used as an integer, scalar
coercion, wrong tuple width or wrong nested type fails before claims
extraction.

`core_audit` has exactly the five keys `schema_version`, `seed`, `tone_deltas`,
`country_deltas` and `applications`, with no extras at any record-shaped level.
Its schema version is exactly `"narrative-diffusion.v1"`; `seed` is a strict
JSON integer equal to `effective_seed`; `tone_deltas` has exactly the three
canonical-Decimal members `firm = 3`, `informational = -1` and
`stabilizing = -4`; and `country_deltas` is a country-ID-to-canonical-Decimal
map. Every complete application has exactly these keys:

```text
proposal_id, target_country, receiver_country, tone, audience,
base_delta, propagation_multiplier, alliance_multiplier,
effective_multiplier, applied_delta, cumulative_delta
```

The first three values are non-empty strings, `tone` is one of `firm`,
`informational` or `stabilizing`, `audience` is one of `domestic`, `regional`
or `global`, and the remaining six values are schema-declared canonical
Decimals. `applications` is an array of those complete objects in the adapter's
canonical application order. Map keys are data, not undeclared record fields;
duplicate keys and non-canonical Decimal tokens still fail the enclosing
strict parser.

`diffusion_request` is the complete closed `WarRoomScenarioRequest` passed to
the production deterministic engine. It has exactly `scenario_key`,
`duration_days`, `intensity`, `propagation`, `target_countries`,
`target_chains`, `policy_actions`, `country_overrides`, `chain_overrides` and
`seed`. `scenario_key` is a non-empty string; `duration_days` is a strict JSON
integer in `1..365`; `intensity` and `propagation` are canonical Decimals in
`[0,1]`; each target/policy member is an array of strings; each overrides
member is a string-keyed map whose values are string-keyed maps of canonical
Decimals; and `seed` is the strict integer `effective_seed`. Every member is
present even when its array or map is empty. An omitted default, added request
key or nested scalar of another type fails closed rather than being filled or
coerced by the runtime model.

The core-audit hash retains the current adapter algorithm exactly. Its preimage
is that complete closed `core_audit` under the unchanged v1 canonicalizer:

```text
{"schema_version":"narrative-diffusion.v1","seed":effective_seed,
 "tone_deltas":{"firm":3.0,"informational":-1.0,"stabilizing":-4.0},
 "country_deltas":complete_country_deltas,
 "applications":complete_applications}
```

In particular, the empty audit preimage is exactly:

```text
{"schema_version":"narrative-diffusion.v1","seed":effective_seed,
 "tone_deltas":{"firm":3.0,"informational":-1.0,"stabilizing":-4.0},
 "country_deltas":{},"applications":[]}
```

`ND.narrative_diffusion_audit_hash` is the SHA-256 of those exact legacy v1
bytes. The request digest is exactly
`diffusion_request_hash = H({"schema_version":"narrative-diffusion.v2",
"diffusion_request":complete_diffusion_request})`. The before/after result
hashes retain the existing canonical complete-`WarRoomRun` hash scope; a
complete result is not an ND top-level member. Run Control obtains the complete
before/result comparison objects from the authenticated RR/PA state chain and
the deterministic re-execution, never by expanding either stored result hash.

The fixed-point scale is exactly `Q = 10_000`, and every fixed-point value is a
signed int64 in `[-2^63, 2^63 - 1]`. `to_units(x)` parses the canonical token as
an arbitrary-precision `Decimal`, computes `Decimal(x) * Q`, then performs the
single explicit integral `ROUND_HALF_EVEN`. `mul_units(x, y)` computes
`Decimal(x) * Decimal(y) / Q` and then performs that same explicit rounding.
No Decimal context may round or truncate before an explicit conversion. Every
conversion, multiplication, addition, clamp input/output and cumulative update
is checked against the int64 bounds; any overflow at any intermediate step
fails closed.

`tone_delta_tuples` is always exactly `(("firm", 30000),
("informational", -10000), ("stabilizing", -40000))` in UTF-8 key order.
`country_delta_tuples` contains `(country_id, delta_units)` ordered by country
ID UTF-8 bytes. Each `application_tuple` has this exact field order:
`(proposal_id, target_country, receiver_country, tone, audience,
base_delta_units, propagation_multiplier_units, alliance_multiplier_units,
effective_multiplier_units, applied_delta_units, cumulative_delta_units,
application_hash)`. Application tuples are ordered lexicographically by the
UTF-8 bytes of their first five string fields and then `application_hash`.
`application_hash` is exactly
`H({"schema_version":"narrative-diffusion.v2",
"application":complete_canonical_decimal_application})`. A duplicate
application coordinate, conversion or arithmetic mismatch, hash collision or
non-canonical order fails closed.

For each application, the base units equal the fixed tone tuple; effective
multiplier units equal `min(Q, mul_units(propagation, alliance))`; the candidate
delta is `mul_units(base, effective)`; cumulative units are the prior
cumulative units plus that candidate clamped to `[-80000, 80000]`; applied
units are the clamped cumulative value minus the prior value. Country units are
the checked sum of applied units for that tick. These equalities are verified
for every step, not merely at the final country total.

Define `eligible_public_narrative_input[t]` as the subsequence of
`PC[t].accepted_proposal_ids` whose unique aligned NP/EL tuple has outcome
`eligible` and closed class `public_narrative`. ND input IDs preserve that
subsequence order and its hashes are the aligned NP proposal hashes. No tuple
absent from PC, EL or NP may be added. When `p[t]=0`, PC is forbidden and the
subsequence is empty. The deterministic diffusion adapter is nevertheless
called exactly once every tick. `ND[t].attempted` is true if and only if this
subsequence is nonempty.

Empty input has `attempted = false`, empty input ID/hash vectors, empty country
and application tuples, `application_count = 0`, the fixed nonempty tone tuple
above, and equal before/after hashes. Those are the only empty collections: the
closed `core_audit` is the exact empty v1 preimage above, the complete closed
`diffusion_request` is still constructed by the one required production
adapter invocation, both nested objects and both of their hashes remain
non-null, and the evidence hash still covers them. Invocation alone never
makes an attempt. `ND[t].before_result_hash` is the post-MB engine result hash,
or the unchanged RR before hash when MB is forbidden.
`ND[t].after_result_hash` is the hash of the complete deterministically
re-executed result.

The ND claims extractor validates the complete wrapper first and then emits
only the fixed registry claims: coordinates and attempted flag, aligned input
vectors, the two nested-object hashes, before/after hashes, fixed-point tone,
country and application tuples, the recomputed count and evidence hash. It
derives every tuple from the complete closed `core_audit`; it never exposes or
accepts a Decimal, map, complete application, `core_audit` or
`diffusion_request` as a Kernel claim.

Finally, `ND.diffusion_evidence_hash` is exactly `H` of every top-level member
except `diffusion_evidence_hash` itself:

```text
ND.diffusion_evidence_hash = H({
 "schema_version":"narrative-diffusion.v2","run_id":run_id,
 "session_id":session_id,"tick":tick,"attempted":attempted,
 "input_proposal_ids":input_proposal_ids,
 "input_proposal_hashes":input_proposal_hashes,
 "core_audit":complete_core_audit,
 "narrative_diffusion_audit_hash":narrative_diffusion_audit_hash,
 "diffusion_request":complete_diffusion_request,
 "diffusion_request_hash":diffusion_request_hash,
 "before_result_hash":before_result_hash,
 "after_result_hash":after_result_hash,
 "tone_delta_tuples":tone_delta_tuples,
 "country_delta_tuples":country_delta_tuples,
 "application_tuples":application_tuples,
 "application_count":application_count})
```

No top-level member is excluded through an inner digest, and neither ND digest
may substitute for the other.

Ordinary relationships form a directed acyclic target graph. They are proof
index edges, not source-payload fields: no relationship, including
`supersedes`, participates in the source Artifact's `content_hash`, extracted
claims or `claims_hash`. Run Control constructs them only after it has
outer-SHA-verified and canonical-payload-verified every current-proof source
Artifact (and the historical target for `supersedes`). Consequently their
arrow direction does not redefine the logical construction order above. The
relationship graph itself must still be a DAG, and relationships may neither
supply a fact absent from a source payload nor repair a missing payload hash
link. The retry contract below defines "earlier" by `run_attempts.attempt_number`,
never by stored-ID format or lexical order. The exact ordinary edge order is
fixed by the matrix below;
in particular RR has no edge to EL, AC or
CL, so no `RR -> EL/CL -> RR`, `EL <-> CL`, `EL <-> RR` or `CL <-> RR` pair or
chain is possible. Run Control detects and rejects a cycle before Kernel
invocation; a repeated hash does not collapse two nodes or excuse a cycle.

### Normative six-mode proof matrix

Let `N` be `PB.proposal_count`; let `A = 1` when `N > 0` and `0` otherwise.
For negotiation, `T = 6`. `EL[t]` is the canonical, governed eligibility
decision over current admission candidates and proven active-commitment
origins; it is not a bare field asserted by `RR[t]`. Thus admission acceptance
is not itself projection eligibility: `AC[t].accepted_proposal_ids` may be
nonempty while `EL[t].eligible_proposal_ids` is empty. Let
`e[t] = bool(EL[t].eligible_proposal_ids)` and `p[t] = 1` exactly when
`e[t] = true`; therefore `p[t]` is determined solely by EL, not by ND. Let
`P = sum(p[1..T])`. Brackets denote references in ascending tick order, and a
filtered bracket contains only ticks for which the stated predicate is true.
An eligible tick requires a projection attempt even if `PC` subsequently
accepts no candidate and deterministic execution is a numeric no-op. A
narrative-only eligible tick is an eligible tick whose eligible actions are
only `public_narrative`; it follows the same projection-proof requirements.

`ordinal` is the zero-based position of a reference in the complete sequence
shown below, with no gaps or reset between categories. Non-negotiation
references have `tick = null`. Negotiation `RR`, `NP`, `AC`, `CL`, `EL`, `PC`,
`MB`, `ND` and `PA` references have the indicated integer tick in `1..6`; `FC` and `NR`
have `tick = null`. Here `attempt` means the exact `attempt_id` of the current
active job attempt, whose attempt row is still `running` during finalization,
not a retry count or an earlier attempt from which work was recovered. Every
reference in the final proof has that current attempt identity. The attempt is
only successful/completed after the persistence sequence below finishes. A
missing, duplicated, surplus or out-of-order reference, including a valid
reference placed in the wrong category, fails finalization.

| Existing engine mode | Canonical reference sequence and exact count | Required relationship targets, in tuple order | Zero-proposal / no-audit rule |
|---|---|---|---|
| `deterministic` | `FC` (1) | `FC`: none | No `PB`, `AR`, `MB`, `CL`, `PA` or replay reference is allowed. `FC.proposal_ids` and accepted IDs are empty; baseline and final source/state hashes are identical. |
| `mock_agent` | `PB, FC, PA[if A]` (`2 + A`) | `PB`: none; `FC`: `evaluates -> PB`; `PA`: `covers -> PB`, `governed_by -> FC` | `N = 0` requires `FC.decision_count = 0` and forbids `PA`. `N > 0` requires exactly one audit-only `PA`, with `record_count = N`, no projected IDs and baseline equal to final. |
| `controlled_agent` | `AR, PB, FC, PA[if A]` (`3 + A`) | `AR`: none; `PB`: `generated_by -> AR`; `FC`: `evaluates -> PB`; `PA`: `covers -> PB`, `governed_by -> FC` | `AR.proposal_ids = PB.proposal_ids`. `N = 0` requires zero decisions and forbids `PA`; `N > 0` requires exactly one audit-only `PA`, with no projected IDs and baseline equal to final. |
| `hybrid` | `AR, PB, FC, MB, CL, PA, HR` (7) | `AR`: none; `PB`: `generated_by -> AR`; `FC`: `evaluates -> PB`; `MB`: `maps -> PB`, `admitted_by -> FC`; `CL`: `ledger_for -> MB`; `PA`: `covers -> PB`, `governed_by -> FC`, `audits -> MB`, `ledger_snapshot -> CL`; `HR`: `observations -> PB`, `governed_by -> FC`, `replays -> MB`, `ledger_snapshot -> CL`, `audit -> PA` | All seven references remain required when `N = 0` or no proposal is accepted, and `CL.ledger_entry_count` is always zero. When `N = 0`, all proposal/decision/modifier/audit-record tuples are empty. When proposals exist but none is accepted, `PB`, `FC` and `PA` still cover those proposals while accepted/projected/modifier tuples are empty, `MB.modifier_count = 0`, and baseline equals final. A `PA` numeric no-op is still required. |
| `hybrid_recorded` | `AR, PB, FC, MB, CL, PA, HR` (7) | Exactly the `hybrid` target list; `HR` must additionally be the stored-only replay selected by this engine mode, as stated by its source payload and replay claim | Exactly the `hybrid` zero-proposal rule. An online execution transcript or a recomputed digest cannot replace `HR`. |
| `negotiation` | `RR[1..T], NP[1..T], AC[1..T], CL[1..T], EL[1..T], PC[t where p[t]=1], FC, MB[t where p[t]=1], ND[1..T], PA[t where p[t]=1], NR` (`6T + 3P + 2 = 38 + 3P`) | `RR[t]`: `previous_round -> RR[t-1]` only for `t > 1`; `NP[t]`: `source_for -> RR[t]`; `AC[t]`: `evaluates -> NP[t]`; `CL[t]`: `snapshot_after -> AC[t]`; `EL[t]`: `sources -> NP[t]`, `admitted_by -> AC[t]`, `current_ledger -> CL[t]`, then `prior_projection -> PA[s]` for every prior projected audit in ascending tick order, then `origin_admission -> AC[s]` for every distinct earlier admission used by an injected active-commitment origin in ascending `(s, artifact_id)` order; `PC[t]`: `filters -> EL[t]`; `FC`: `evaluates -> RR[T]`; `MB[t]`: `admitted_by -> PC[t]`; `ND[t]`: `inputs -> EL[t]`, then `bounded_by -> MB[t]` when `p[t]=1`; `PA[t]`: `round -> RR[t]`, `governed_by -> PC[t]`, `audits -> MB[t]`, `diffusion -> ND[t]`, `ledger_snapshot -> CL[t]`; `NR`: `replays -> RR[1..T]`, `proposal_sources -> NP[1..T]`, `admission -> AC[1..T]`, `ledgers -> CL[1..T]`, `eligibility -> EL[1..T]`, `projection -> PC[t]`, `final_audit -> FC`, `modifiers -> MB[t]`, `diffusion -> ND[1..T]`, `audits -> PA[t]`, with every repeated or filtered target in ascending tick order | `NP`, `AC`, `CL`, `EL` and `ND` are exactly one per tick, including zero-proposal ticks. When `p[t]=0`, `PC[t]`, `MB[t]` and `PA[t]` are forbidden; `RR[t].no_projection_reason` is the canonical `no_projection`, and the ND empty-input invariants apply: `attempted=false`, empty input/country/application tuples, the fixed tone tuple, and equal ND before/after hashes. Such a tick may contain admission-accepted but ineligible proposals. When `p[t]=1`, `PC[t]`, `MB[t]` and `PA[t]` are all required even for a numeric no-op; `PC[t].candidate_proposal_ids = EL[t].eligible_proposal_ids`, `RR[t].proposal_batch_hash = NP[t].batch_hash`, `RR[t].eligible_proposal_ids = EL[t].eligible_proposal_ids`, `RR[t].eligibility_hash = EL[t].eligibility_hash`, `RR[t].no_projection_reason` is null, and `ND[t].after_result_hash = PA[t].final_result_hash = RR[t].after_result_hash`. |

Each ordinary relationship uses the target reference's exact `artifact_id` and
`content_hash`. The prose arrow labels above are the only allowed ordinary
`relationship_type` values for that source token and mode. Repeated targets
expand into separate relationship records. No extra relationship is allowed,
except the retry-only `supersedes` relationship defined below; when present it
is last in the source reference's relationship tuple.

On every retry, **GOV-RETRY-1**, the new attempt is a hard Artifact boundary.
No proof-source or resolver Artifact row from an earlier attempt is admitted as
a current input or final-proof reference. Run Control revalidates or
deterministically regenerates the required sources and persists a new row for
each under the current `attempt_id`; every Agent-capable mode also reruns both
pinned resolvers and persists new current-attempt `agent_pack` and
`agent_constraint_context` rows. Deterministic persists neither resolver
Artifact. Their producing completed-step outputs, `artifact_refs` hashes and
checkpoint roots are likewise rebuilt under the current attempt; an earlier
attempt's completed-step binding is not reused as the current checkpoint. By
the time `report_generate.v2` runs, the exact current-attempt
proof-source sequence is the corresponding matrix sequence, with no aliases or
generic Artifact-type substitution:

| Existing engine mode | Exact retry/current-attempt proof-source sequence |
|---|---|
| `deterministic` | `FC` |
| `mock_agent` | `PB, FC, PA[if A]` |
| `controlled_agent` | `AR, PB, FC, PA[if A]` |
| `hybrid` | `AR, PB, FC, MB, CL, PA, HR` |
| `hybrid_recorded` | `AR, PB, FC, MB, CL, PA, HR` |
| `negotiation` | `RR[1..T], NP[1..T], AC[1..T], CL[1..T], EL[1..T], PC[t where p[t]=1], FC, MB[t where p[t]=1], ND[1..T], PA[t where p[t]=1], NR` |

Provider-originated facts needed for retry are read only from authenticated
historical sources, then re-emitted as current-attempt Artifacts; re-emission
does not invoke a Provider. Every Consistency decision is recomputed, and every
modifier, deterministic result and diffusion result is re-executed as required
by the mode adapter. Stored decisions, modifiers, applications, deltas and
results remain comparison targets rather than authority. The ordinary
relationships of every re-emitted source are rebuilt exclusively against
current-attempt targets.

A v2 job whose status becomes `cancelled` is permanently terminal for that
`lifecycle_job_id` and `run_id`. Cancellation may not enqueue, resume or create
another attempt of that job, and a cancelled attempt is never a
GOV-RETRY-1/GOV-RECOVERY-1 historical source. Its Artifacts remain immutable
cancelled history but may not be re-emitted, copied into a new proof, or named
by `supersedes`. Recovery from the user's business intent requires an explicit
new-job request that creates a new lifecycle job and run; that execution starts
from its own authenticated inputs, may invoke the Provider again under its
ordinary mode contract, and receives no provider-free retry privilege from the
cancelled run. No cancelled Artifact is retransmitted to the Provider or
admitted into the new run.

Negotiation additionally retains its continuous-prefix recovery rule. Run
Control derives completed ticks from the authenticated stored checkpoint and
source Artifacts, and they must be exactly the one-based prefix `1..k`, where
`0 <= k <= T`. For every tick in that prefix, the canonical Artifact set and
recovery order is exactly `RR`, `NP`, `AC`, `CL`, `EL`, `PC` when `p[t]=1`,
`MB` when `p[t]=1`, `ND`, and `PA` when `p[t]=1`; `p[t]` is recomputed solely
from that tick's authenticated `EL`. A gap, missing or duplicate token, surplus
token, wrong tick, or conditional `PC`/`MB`/`PA` mismatch fails closed. The
prefix never contains terminal `FC` or `NR`. Its re-emission allow-set is
exactly `RR, NP, AC, CL, EL, PC, MB, ND, PA`, subject to those conditions;
`NP` and `EL` may not be treated as surplus. Run Control revalidates and
re-emits the prefix under the current attempt before continuing. It reruns
every prefix AC and applicable PC, Action Adapter, deterministic engine and
diffusion check from authenticated inputs and the pinned seed. The Provider
call count is zero throughout prefix revalidation.

For every historical source that is re-emitted, including a resolver Artifact,
the historical lookup scope is exactly `(organization_id, project_id,
lifecycle_job_id,
run_id, nullable session_id, schema, nullable role, nullable tick)`. `schema`
is the exact `proof_schema` for a proof source and the exact closed resolver
checkpoint schema (`agent-pack-resolver-output.v1` or
`constraint-context-resolver-output.v1`) for a resolver Artifact; `role` is the extracted Consistency role
for FC/AC/PC and is null otherwise. The target attempt must belong to that same
`lifecycle_job_id`, have terminal status `failed` or `abandoned`, and have an integer
`attempt_number` strictly less than the current attempt. Run Control selects
the unique candidate at the maximum such `attempt_number`; lexical attempt-ID
order, a different organization/project/lifecycle job, a non-terminal attempt and a
merely matching generic `artifact_type` are never eligible. No candidate, or
more than one candidate at the selected attempt number and coordinate, fails
closed for a source asserted to be a re-emission.

The selected target must have the same `content_hash`. For a proof source, its
opaque stored `attempt_id` is copied unchanged to `target_attempt`, and its
`artifact_id` is copied to both relationship `target_artifact_id` and the
current row's `supersedes_artifact_id`; the one `supersedes` relationship is
last. A resolver Artifact is not a proof reference and therefore records the
same lineage only in its current row's `supersedes_artifact_id`. Historical
rows may appear only in this authenticated lineage position, never as an
ordinary relationship target, resolver input row or proof reference. Every
ordinary proof reference and every resolver binding carries the current active
`attempt_id`.

Terminal `FC`, and negotiation `NR`, are freshly rebuilt from current-attempt
inputs. They never carry `supersedes`, even if a failed or abandoned attempt
contains the same terminal schema: their new rows have
`supersedes_artifact_id = null`, and their proof references have no
`supersedes` relationship. Thus every mode still emits all matrix-required
tokens under the current attempt while terminal authority is never copied from
history.

After structural validation, the Kernel applies the following numbered
governance invariants over claims rather than over opaque hashes alone. These
identifiers are normative references used by the acceptance outcomes below:

- **GOV-X-1 — identity/cardinality:** every referenced `run_id`, nullable
  `session_id` and attempt agrees with the request and record. Negotiation has
  one non-null session ID repeated identically by the request, record, every
  proof reference and every session-bearing claim, including `CL.session_id`;
  every non-negotiation request, record and proof reference has
  `session_id = null`, and its hybrid CL claim is also null. The request and
  record `evaluator_version` are equal to each other, to the
  runtime-profile-pinned `evaluator_version`, and to every mode-applicable
  FC/AC/PC evaluator-version claim. Their nullable Agent Pack/context fields
  obey the closed mode rule above and, when non-null, equal the current
  attempt's field-for-field-regenerated resolver Artifacts and every
  mode-applicable FC/AC/PC claim. Every count equals its tuple length and every
  ID set is unique;
- **GOV-X-2 — projection scope:** in deterministic and audit-only modes, `FC.deterministic_result_hash` equals
  both projections' `source_run_hash`. In hybrid modes it equals the baseline
  source hash, and in negotiation it equals the final source hash;
- **GOV-X-3 — non-negotiation proposal alignment:** in every non-negotiation mode that has PB,
  `FC.proposal_ids == PB.proposal_ids`,
  `FC.proposal_hashes == PB.proposal_hashes` and
  `FC.decision_count == PB.proposal_count`. In controlled and both hybrid
  modes, AR's proposal IDs and hashes equal the same PB vectors. Whenever a
  non-negotiation PA is present, the exact vector equalities are
  `PA.proposal_ids == FC.proposal_ids == PB.proposal_ids`,
  `PA.proposal_hashes == FC.proposal_hashes == PB.proposal_hashes` and
  `PA.record_input_hashes == PA.proposal_hashes == FC.proposal_hashes ==
  PB.proposal_hashes`; each aligned PA record claim repeats that same proposal
  ID, proposal hash and input hash, and its `decision`, `rule_version`,
  `outcome` and `rejection_reason` equal the aligned FC pre-projection decision.
  PA `projection_status`, `projection_hash` and `modifier_id` are derived only
  after FC from the recomputed MB and Projection Audit truth table and are not
  compared with FC projection fields. Every record's `final_result_hash`
  equals the PA top-level `final_result_hash`; for every projected record,
  `projection_hash` equals the `modifier_hash` in the unique PA modifier tuple
  selected by its `modifier_id`, while every non-projected record satisfies the
  null and rejection rules in the table. Every such PA also has
  `PA.consistency_audit_hash == FC.audit_hash`. In `mock_agent` and
  `controlled_agent`, its exact top-level state binding is
  `PA.before_result_hash == PA.final_result_hash ==
  baseline_projection.source_run_hash == final_projection.source_run_hash`;
- **GOV-X-4 — hybrid lineage:** for hybrid modes, accepted IDs agree across `FC`, `MB`, `PA` and `HR`; the
  exact audit/bundle bindings are `MB.consistency_audit_hash == FC.audit_hash`,
  `PA.consistency_audit_hash == FC.audit_hash` and
  `PA.modifier_bundle_hash == MB.bundle_hash`. The exact modifier invariant is
  `MB.modifier_tuples == PA.modifier_tuples`, including the valid empty-tuple
  numeric no-op. The replay bindings are exactly
  `HR.proposal_batch_hash == PB.batch_hash`,
  `HR.consistency_audit_hash == FC.audit_hash`,
  `HR.modifier_bundle_hash == MB.bundle_hash`,
  `HR.projection_audit_hash == PA.audit_hash`,
  `HR.ledger_hash == CL.ledger_hash` and
  `PA.before_result_hash == HR.baseline_result_hash ==
  baseline_projection.source_run_hash`. The other exact PA replay-state
  binding is `PA.final_result_hash == HR.final_result_hash`. Stored replay
  reproduces `HR.final_result_hash`, which is the final canonical result before
  `hybrid_trace` is attached. Run Control then derives that replay result's
  deterministic source payload and projected WorldState and verifies their
  hashes against the final projection's `deterministic_source_hash` and
  `world_state_hash`. The persisted full source `WarRoomRun` includes
  `hybrid_trace`; its separately computed hash must equal both
  `HR.full_source_run_hash` and the final projection's `source_run_hash`.
  For every `PA.projected_proposal_ids` entry, Run Control uniquely selects the
  complete proposal from PB, recomputes its semantic-key hash from the exact NP
  `actor_id`/`action_type`/ascending-`target_ids`/validated-`parameters`
  preimage, and requires equality with the aligned
  `PA.projected_semantic_key_hashes` value. Missing or ambiguous PB membership
  and every recomputed semantic mismatch fail closed.
  `CL.ledger_entry_count` is exactly zero with a recomputed canonical
  empty-ledger hash;
- **GOV-X-5 — negotiation admission/state chain:** for negotiation, RR ticks are exactly `1..6`, each
  `round_id` is the exact `round_`-prefixed session/tick digest above and the six
  values are unique. Every complete message wrapper has the same
  session/round/tick coordinate as its containing RR, its derived message ID
  and recomputed hash are valid, and the union of RR messages has one
  contiguous session-global `seq = 1..n` predecessor chain whose original
  sequence values are retained in the per-tick tuples. `RR[1].before_result_hash` equals the baseline projection,
  each later RR before hash equals the prior tick's RR after hash, and
  `RR[T].after_result_hash` equals the final projection. Negotiation FC has
  `proposal_ids`, `proposal_hashes`, `accepted_proposal_ids` and
  `decision_tuples` all exactly empty and `decision_count = 0`; it is a terminal
  state audit, not another proposal evaluation. For every tick, the
  exact current-message equality is
  `AC.proposal_ids == RR.proposal_ids == IDs(NP current_message subsequence)`
  and `AC.proposal_hashes == hashes(NP current_message subsequence)`; both AC
  vectors contain every current-message proposal and no active origin. AC's
  accepted IDs equal `RR.accepted_proposal_ids`, and
  `AC.deterministic_result_hash == RR.before_result_hash`;
- **GOV-X-6 — eligibility:** exactly one EL decision exists for each NP tuple and no other tuple. The
  Kernel recomputes each decision and eligibility hash, validates the ordered
  algorithm against AC, CL and prior PA, and compares the complete NP tuple in
  each EL decision field-for-field with NP. It first applies admission, hard
  origin validation, excluded-class, active-commitment and prior-projection
  precedence, then forms equal-semantic groups only from the remaining
  preliminary eligible candidates. For each such group it recomputes the
  proposal-ID UTF-8 minimum as the sole eligible winner and requires
  `semantic_duplicate` for every other preliminary member; an earlier-ID
  excluded proposal cannot compete. The prior-PA seen sets and
  `prior_projected` rule remain unchanged. Every active origin also satisfies
  the earlier-RR/earlier-NP/earlier-AC/current-CL four-way equality above.
  `RR.eligible_proposal_ids == EL.eligible_proposal_ids` and
  `RR.eligibility_hash == EL.eligibility_hash`;
- **GOV-X-7 — governed projection:** on every projected tick,
  `PC.candidate_proposal_ids == EL.eligible_proposal_ids`, PC's aligned
  proposal hashes equal the NP hashes selected by those IDs, and
  `PC.deterministic_result_hash == RR.before_result_hash`.
  `PA.proposal_ids == PC.candidate_proposal_ids` and PA's proposal hashes are
  the same NP-selected aligned vector; `PA.record_input_hashes` equals that
  proposal-hash vector, and every aligned record claim repeats the same
  proposal ID/hash/input hash. The exact equality is
  `MB.accepted_proposal_ids == PC.accepted_proposal_ids == PA.projected_proposal_ids`.
  Every accepted ID has exactly one MB modifier
  tuple, including an Action Adapter `no_numeric_effect_reason` tuple when the
  mapping has no numeric effect; no unaccepted ID has one. The exact ordered
  tuple equality is `MB.modifier_tuples == PA.modifier_tuples`. Every PA
  record's `decision`, `rule_version`, `outcome` and `rejection_reason` equal
  the aligned PC pre-projection decision. Its `projection_status`,
  `projection_hash` and `modifier_id` are instead derived after PC from the
  recomputed MB and Projection Audit truth table; no FC/PC projection field is
  an equality source. Every record's `final_result_hash` equals the PA top-level
  `final_result_hash`, and every projected record's `projection_hash` and
  `modifier_id` equal the `modifier_hash` and `modifier_id` in its unique
  aligned recomputed modifier tuple;
- **GOV-X-8 — projected semantics:** for every PA projected ID, including an ID first seen in the current tick,
  the aligned `PA.projected_semantic_key_hashes` value equals the
  `semantic_key_hash` obtained by unique ID lookup in the authenticated NP.
  Prior-tick seen-set reconstruction performs the same lookup; neither path
  trusts a stored semantic hash without NP;
- **GOV-X-9 — diffusion inputs/state:** `ND.input_proposal_ids` is exactly the subsequence of PC accepted IDs whose
  NP/EL class is `public_narrative` and whose EL outcome is `eligible`, and its
  aligned hashes are exactly the NP proposal hashes. The exact equality is
  `PA.before_result_hash == RR.before_result_hash`. Running the complete MB
  patch through the engine
  produces a post-MB result whose hash is `ND.before_result_hash`, and
  `ND.after_result_hash == PA.final_result_hash == RR.after_result_hash`;
- **GOV-X-10 — digest/replay bindings:** all repeated digest bindings are exact equalities:
  `RR.messages_hash` is the recomputed tick message hash,
  `RR.proposal_batch_hash == NP.batch_hash`,
  `RR.admission_audit_hash == AC.audit_hash`,
  `RR.ledger_hash == CL.ledger_hash`,
  `RR.eligibility_hash == EL.eligibility_hash`,
  `RR.projection_consistency_hash == PC.audit_hash ==
  MB.consistency_audit_hash == PA.consistency_audit_hash`,
  `RR.modifier_bundle_hash == MB.bundle_hash == PA.modifier_bundle_hash`,
  `RR.diffusion_evidence_hash == ND.diffusion_evidence_hash`, and
  `RR.projection_audit_hash == PA.audit_hash`. The three conditional values are
  null exactly when their proof is forbidden. NR reproduces the nine declared
  tick vectors, including the three conditional null slots, has
  `provider_calls_required = 0`, and binds the baseline/final hashes;
- **GOV-X-11 — tick cardinality predicate:** `e[t]` and `p[t]` are recomputed solely from
  `EL[t].eligible_proposal_ids`. Separately, the Kernel verifies the v2 ND
  attempted predicate and its exact EL-bound public-narrative proposal-ID
  tuple. Thus ND cannot create or suppress a required audit, and a surplus
  audit cannot be hidden on a no-projection tick.

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

The internal `negotiation-projection-audit.v2` payload fixes
`projection_mode = "negotiation"`. Non-negotiation
`agent-action-projection-audit.v2` payloads fix `projection_mode` to
`audit_only` or `hybrid` according to the engine mode as specified above. These
are internal Artifact-payload contracts only; the OpenAPI contract and all
public response models remain unchanged.

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
gate. All storage reads, evaluator invocations and deterministic re-execution
described in this section remain in Run Control. The pure Kernel remains free
of storage, Provider, network and wall-clock access.

Run Control first reads each stored Artifact as opaque raw bytes and
recomputes/compares its outer `artifact_sha256`. Only after that comparison
succeeds may it strictly decode UTF-8, parse JSON, select or validate any schema,
recompute/compare the inner `content_hash`, extract or validate claims and
`claims_hash`, or construct the complete typed reference. The pure
Kernel then validates that reference's structure and relationship to the
projections and authority path. Neither layer accepts a bag of caller-provided
digest strings as a substitute for authenticated typed envelopes.

The outer SHA is independently rooted before any proof source or resolver
Artifact can be consumed. For governed proof-source and resolver inputs, the
closed `artifact_refs` checkpoint union has exactly these two tuple variants,
in producing-step order:

```text
("resolver", artifact_id, artifact_sha256, content_hash, resolver_schema,
 attempt)
("proof", artifact_id, artifact_sha256, content_hash, proof_schema, attempt)
```

For the resolver variant, `resolver_schema` is exactly
`agent-pack-resolver-output.v1` for `agent_pack` or
`constraint-context-resolver-output.v1` for `agent_constraint_context`. For the
proof variant, `proof_schema` is the exact registry token, not the generic
`artifact_type`. The `attempt` member in either variant is the producing
attempt's opaque `attempt_id`. Each tuple has exactly one discriminator and its
corresponding schema field: a resolver Artifact may not be encoded or consumed
as `proof`, a proof source may not be encoded or consumed as `resolver`, and a
tuple containing both schema fields, neither schema field, an unknown
discriminator or additional members fails closed.

When a lifecycle source-producing step completes, its canonical output and `artifact_refs` hash
commit the exact ordered sequence of these variants, and the authenticated
checkpoint commits that completed-step output hash and `artifact_refs` hash.
Step-output and checkpoint-root verification of governed inputs accepts both
variants as this closed discriminated union and never collapses them into one
schema namespace. Non-proof report/projection Artifacts retain their separately
specified bindings and can never be inserted into this governed-input union.
Report, retry and replay paths recompute each tuple from the Artifact row and
verified payload and compare it with both the producing completed step and
checkpoint chain before accepting the source or resolver input.
Replacing one Artifact's bytes therefore fails even if the attacker also
updates that row's `artifact_sha256`: the tuple no longer matches the immutable
producing-step root and checkpoint. Updating `content_hash` or another tuple
member merely creates the same mismatch; neither relationships nor a later
request/record hash can repair it.

Stored Consistency decisions are never input authority. Before accepting any
FC, AC or PC, Run Control first reruns the pinned post-baseline context
resolvers where the mode requires them and performs the complete
field-for-field Artifact/binding comparison above. It then invokes the
runtime-profile-pinned deterministic Consistency evaluator again with Provider
access disabled. Its inputs are only
the complete proposals recovered from outer-SHA- and content-verified PB/NP,
the verified before-state for that evaluation, the complete pinned Rule Pack
whose recomputed ID/hash match the job, the complete regenerated Agent Pack and
constraint context required by the closed mode rule, and the exact pinned
evaluator version. A stored decision, accepted-ID set, projection
status, inner audit hash or wrapper audit hash is a comparison target and must
never be passed into the evaluator or used to select its result.

The mode scope is exact. Deterministic reruns its required empty-vector FC;
`mock_agent`, `controlled_agent`, `hybrid` and `hybrid_recorded` rerun FC over
the complete PB proposal vector and the verified non-negotiation before-state.
Negotiation reruns AC at every tick over the complete NP current-message
subsequence and `RR[t]` before-state, reruns PC exactly at each tick where PC is
required over the complete NP proposals selected by EL and the same verified
before-state, and reruns the empty terminal FC over the verified `RR[T]`
after-state. Each invocation uses the same resolved
`(agent_pack_id, agent_pack_hash, constraint_context_hash,
evaluator_version)` tuple; it is the all-null context tuple only for
deterministic FC and the same non-null regenerated tuple everywhere else.
Per-role or per-tick drift fails closed.

Run coordinates are not descriptive strings. For lifecycle run `R`, the exact
outer `(run_id, role, tick)` and inner `consistency-audit.v2.run_id` mappings are
FC `(R, final, null) -> R`, AC at tick `t`
`(R, admission, t) -> R:tick:t`, and PC at tick `t`
`(R, projection, t) -> R:projection:t`. The recomputed result is first encoded
as the complete `consistency-audit.v2` inner report and then as the complete
`consistency-audit.v3` wrapper. Run Control compares both objects
field-for-field, including every proposal ID/hash, decision, accepted ID,
version, coordinate and recomputed inner/wrapper hash. Any difference fails
before numeric replay or persistence.

After that evaluator comparison, the adapter rules are:

- deterministic: verify stored baseline/final identity and final Consistency
  Audit;
- mock/controlled Agent: additionally verify observation/proposal hashes and an
  audit-only Projection Audit when proposals exist; no Action Adapter hash is
  allowed;
- hybrid and `hybrid_recorded`: verify stored proposals, Consistency Audit,
  modifier bundle, Projection Audit and hybrid stored replay, plus exactly one
  canonical versioned empty Commitment Ledger; a non-empty ledger is invalid,
  before requesting Kernel finalization;
- negotiation: verify message, round, state and Commitment chains, the exact
  v2/v3 source versions and hash preimages, both Consistency wrappers and their
  complete inner decisions, exactly one eligibility proof and current/prior
  ledger and projection-audit references for each tick, the required per-tick
  Commitment Ledger snapshot, and every Projection Audit required by the tick
  cardinality below. Stored-only replay means deterministic re-execution from
  authenticated sources, not acceptance of stored numeric applications.

The adapter is fail-closed. A missing, duplicated, corrupt, cross-run or
mode-incompatible proof prevents report generation and research-run
projection.

For `hybrid` and `hybrid_recorded`, Run Control derives acceptance only from
the recomputed FC, selects the corresponding complete verified PB proposals,
and passes those proposals plus the pinned seed to the production Action
Adapter. It compares the complete recomputed MB field-for-field with storage,
then applies only the recomputed scenario patch to the production deterministic
engine from the verified before-state. PA, HR and the final projection are
verified against that re-executed result. Stored accepted IDs, modifier tuples,
scenario patches or final numeric values never drive this re-execution.

For each negotiation tick in order, Run Control first completes the AC and, when
required, PC evaluator reruns above. It reconstructs the complete RR before
`WarRoomRun`, authenticates the complete canonical NP proposals, derives the
accepted candidates only from the recomputed PC, and uses the pinned seed to
invoke the production `build_modifier_bundle()`/Action Adapter on exactly those
candidates. It compares every field of the recomputed bundle with MB, including
schema and adapter versions, accepted IDs, every complete modifier and modifier
hash, `scenario_patch` and `bundle_hash`. It then passes the recomputed scenario
patch to the production deterministic engine and obtains the post-MB state. A
stored bundle hash, stored modifier tuple or stored scenario patch is never
numeric authority and cannot suppress this re-execution. On a no-projection
tick, MB is forbidden and the authenticated RR before state is the post-MB
state.

Only after that post-MB state exists, Run Control selects the exact complete NP
public-narrative proposals admitted by the recomputed PC result and required by
the ND input equality. On a no-projection tick with no PC, that selection is the
canonical empty tuple required by the existing ND rules. It carries the pinned
seed and invokes the production deterministic diffusion adapter once. The
`cumulative_deltas` argument starts empty at tick 1
and thereafter is only the in-memory result of the same verified re-execution
for earlier ticks; it is never loaded from a session cache, RR, ND country
total, application object or `applied_delta`. Run Control compares the
recomputed complete v2 wrapper core audit, every fixed-point derivation, the
complete state request and its hash field-for-field, invokes the deterministic
engine on that recomputed request, and compares the complete result and result
hash field-for-field. It also reconstructs the v2 PA from the recomputed PC
decisions, recomputed MB and recomputed before/final states and compares every
field. Applying stored `applications` or `applied_delta` values to a state and
calling that operation replay is expressly forbidden. This sequence is what
proves numeric authority against internally consistent untrusted Agent payload
numbers and payload-local hashes; it makes no claim against the coordinated
all-root rewrite excluded by the threat model below.

### Negotiation Projection Audit closure

The target negotiation contract retains two distinct Consistency reports: the
read-only admission report that decides which proposals may proceed, and the
projection report that governs the deterministic projection inputs. Current
code does not yet satisfy that storage contract: its second report is
transient. This ADR requires the implementation to persist both reports as
versioned Artifacts, keep their hashes distinct, and bind both identities into
the hash-addressed round chain so replay detects replacement of either one.
They cannot be substituted for or deduplicated into one another. The modifier
bundle and `negotiation-projection-audit.v2` both bind the persisted projection
report.

Admission acceptance and projection eligibility are distinct tick-governance
facts. The persisted `EL[t]` proof, rather than a bare round field, performs
the canonical ordered current-admission and active-commitment filtering defined
above. `RR[t]` carries only the EL-bound eligible IDs and eligibility hash. A
nonempty admission-accepted set may therefore produce an empty eligible set,
while an eligible active-commitment origin may be outside the current admission
set when its earlier admission and current ledger proof are linked. The
projection report receives exactly `EL[t].eligible_proposal_ids` as its
candidate IDs. Its accepted IDs equal the projection audit's projected IDs and
the modifier bundle's accepted/modifier proposal IDs. For every aligned PA
record, only `proposal_id`, `proposal_hash`, `input_hash`, `decision`,
`rule_version`, `outcome` and `rejection_reason` equal the corresponding PC
pre-projection decision fields. After that equality is established, Run
Control derives PA `projection_status`, `projection_hash` and `modifier_id`
from the recomputed MB and the Projection Audit truth table, never from PC's
projection fields. Each projected record's projection hash and modifier ID
equal its unique modifier tuple's values, every non-projected record satisfies
the table's null rules, and every record's `final_result_hash` equals the PA
top-level `final_result_hash`.

Per-tick proof cardinality is exact:

1. A no-projection tick requires `e[t]=false`, hence the v2 ND predicate
   requires `ND[t].attempted=false`, canonical empty input IDs/hashes and
   country/application tuples, the fixed nonempty tone tuple, and equal
   before/after diffusion hashes. It carries an explicit
   canonical `no_projection` reason and identical before/after state hashes;
   it must not imply that a deterministic projection occurred. Its EL-bound
   eligible-ID set is empty. It may still contain proposals accepted by
   admission but excluded from EL.
2. Every eligible tick has exactly one `negotiation-projection-audit.v2`, even when
   projection Consistency accepts no candidate or deterministic execution
   produces no numeric change. A narrative-only eligible tick therefore also
   requires exactly one Projection Audit.
3. Every tick has exactly one versioned Commitment Ledger snapshot proof,
   including rejected, empty and otherwise no-projection ticks and including an
   empty ledger. Its snapshot hash is retained in the round chain.
4. Every tick has exactly one `NarrativeDiffusionAudit` (`ND`). As target v2
   behavior, the engine MUST call and use the diffusion adapter even when no
   narrative diffusion occurs, so it produces the canonical empty audit rather
   than the legacy ad-hoc empty dictionary. Invocation alone does not make an
   attempt: `attempted` and the input/output fields obey the v2 EL-bound ND
   predicate above. Current engine persistence does not yet make this
   guarantee; closing that gap is required for v2 and is not a claim about the
   current engine.

For a projection attempt, the implementation will build the deterministic
modifier bundle, run the deterministic engine and bounded diffusion adapter,
and build and verify `negotiation-projection-audit.v2` against the resulting final
tick-state hash. The round output will embed the two persisted,
version-bound Consistency-report references, modifier binding and Projection
Audit reference. The audit is persisted with
`artifact_type = negotiation_projection_audit`, a new allowed value in the
existing generic Artifact store. It is not a new storage type or public model:
no table, Artifact storage schema, OpenAPI schema or public Artifact model is
added.

Negotiation replay verifies both complete v3 Consistency wrappers and their
round-chain links, the projection-report bindings, projected IDs and semantic
hashes, canonical no-projection reason and every v2 CL snapshot. Its numeric
result comes only from the provider-free MB/engine/ND re-execution above; the
stored hashes and fixed-point claims are comparison targets, never state-delta
inputs.

### Report and recovery contract

The six existing production step keys and their order remain unchanged. For a
v2-pinned job, `report_generate` selects step version `report-generate.v2`
(hereafter `report_generate.v2`) and `replay_archive` selects
`replay-archive.v2` (hereafter `replay_archive.v2`). Upgrade the report Artifact
to `report-projection-manifest.v2` and embed the compact
`KernelModeExecutionRecord`, not Agent text or full WorldState, in that existing
Artifact.

`report-projection-manifest.v2` is a non-proof, closed payload. It has exactly
`schema_version`, `result_hash`, `workspace_compatible`,
`run_diff_compatible`, `replay_pack_compatible`, `execution_record`,
`proof_hash` and `manifest_hash`; every key is required and additional keys
fail validation. The three compatibility flags remain strict boolean `true`,
preserving the v1 workspace, Run Diff and Replay Pack contract. `result_hash`
retains the v1 complete-final-`WarRoomRun` hash scope and must equal
`execution_record.final_source_run_hash`. `execution_record` is the complete
compact `KernelModeExecutionRecord` defined above, including its `record_hash`,
and `proof_hash` must equal `execution_record.proof_hash`. The manifest digest
has this one exact preimage:

```text
manifest_hash = H({"schema_version":"report-projection-manifest.v2",
 "result_hash":result_hash,"workspace_compatible":true,
 "run_diff_compatible":true,"replay_pack_compatible":true,
 "execution_record":complete_execution_record,"proof_hash":proof_hash})
```

The manifest is not a `KernelModeExecutionProof` reference or a proof source.
It embeds neither `proof` nor any complete proof reference, claim or
relationship; `proof_hash` and the compact record are its only finalization
bindings. On every v2 report-consuming path, its raw bytes must first pass the
outer Artifact SHA comparison; only then may strict UTF-8/JSON parsing, closed
schema validation and `manifest_hash` recomputation/comparison occur. The outer
Artifact SHA and `manifest_hash` authenticate distinct byte and
canonical-content scopes.

The report manifest and embedded record are current-attempt objects only.
`execution_record.attempt`, the request behind its `request_hash`, every proof
reference behind `proof_hash`, the report Artifact row and the report-step
output/ref binding must all name the same `current_attempt_id`. During report
or replay execution that attempt is active and `running`; during the read-only
terminal duplicate-GET path below it is the same attempt already marked
`completed`. A report
manifest or record from an earlier attempt is immutable history and is never a
`supersedes` target, current comparison authority or current report-step
reference. GOV-RETRY-1 lineage applies only to the underlying proof-source and
resolver Artifact rows that it explicitly permits.

Every v2 `report_generate`, `replay_archive`, terminal duplicate-GET and source
lookup is scoped first by the same exact ownership tuple:

```text
(organization_id, project_id, lifecycle_job_id, run_id,
 nullable session_id, current attempt)
```

Here `current attempt` is the opaque `current_attempt_id` on the canonical job,
not a caller-selected attempt number. Artifact, producing-step, checkpoint,
manifest, research and projection queries must authenticate every member of
this tuple, through direct row predicates or mandatory ownership joins and
bindings, before applying their schema/role/tick coordinates; a
run-only, organization-and-run-only or nullable-session-wildcard lookup is
forbidden. Zero rows where one is required or more than one row at a supposedly
unique coordinate fails closed. GOV-RETRY-1's historical target selection is a
separate lineage lookup: it starts from this current ownership tuple and may
vary only the explicitly authenticated lower terminal target attempt described
there; historical rows never become current execution sources.

Every v2 claim creates one stable fencing epoch from authoritative immutable
identity. Let `A` be the job's `current_attempt_id`, `N` that attempt's strict
positive `attempt_number`, `W` both `attempt.worker_id` and the job's
`lease_owner`, `G` the runtime profile's `minimum_worker_generation`, and `V`
the worker registration's current unique UTF-8-sorted
`execution_contract_versions` tuple. The hashes are exactly:

```text
worker_capability_hash = H({"execution_contract_versions":V})
fencing_epoch_hash = H({"schema_version":"kernel-mode-fencing-epoch.v1",
 "current_attempt_id":A,"attempt_number":N,"worker_id":W,
 "minimum_worker_generation":G,
 "worker_capability_hash":worker_capability_hash})
```

The claim transaction writes `attempt.worker_id = W` and computes this epoch
only after authenticating the non-retired worker, requiring its immutable
`worker_generation >= G` and requiring `V` to contain exactly the supported v2
marker. Worker identity, generation and capability tuple are immutable
registration facts; retirement changes only retirement state. A job-lease
heartbeat for the same `(A, W)` may only extend `lease_expires_at`. It does not
change an owner, attempt, attempt number, generation, capability tuple or either
hash above, so it does not create a new fencing epoch. The separate worker
freshness heartbeat likewise cannot mutate those epoch inputs.

Immediately before either v2 phase starts its potentially long reconstruction,
and after ordinary claim/resume validation has required a fresh running lease,
the claimed worker captures `A`, `N`, `W`, `G`, `V`,
`worker_capability_hash` and `fencing_epoch_hash = E` from those authoritative
rows. It does not capture `lease_expires_at` as an identity token. The rebuilt
request and returned record both carry exact `fencing_epoch_hash = E`, and the
closed request/record preimages above hash it. The manifest, replay and
projection remain unauthoritative candidate values until the phase passes the
final write fence below.

`report_generate.v2` owns reconstruction and report finalization. It loads the
canonical lifecycle job and `current_attempt_id`, requires that exact attempt
to be active and `running`, reruns and field-for-field compares the applicable
post-baseline context resolvers, loads proof-source Artifacts only from that
exact ownership tuple, successfully compares each raw-byte outer SHA first,
and only then strict-decodes UTF-8, parses JSON, validates the selected closed
schema and content hash, and extracts and validates claims,
reconstructs the complete `ModeExecutionAdapter` proof, projections and
`KernelModeExecutionRequest`, and invokes the pure Kernel to obtain the
authoritative `KernelModeExecutionRecord`. It recomputes the complete stored
`runtime_profile_hash` and requires exact equality among the job, Kernel
request and returned record, including the complete ownership tuple, active
`attempt_id`,
execution-contract version, effective seed, Rule Pack, mode-governed nullable
Agent Pack/context outputs, engine mode and final projection bindings.
The reconstructed request and record must also contain the captured
`fencing_epoch_hash = E`; a caller record with another epoch is only a mismatch,
never authority to replace it.

A caller-supplied execution record is optional. When present it is only an
additional complete field-for-field comparison against the record returned by
that phase's reconstruction and Kernel call; it cannot provide missing facts,
authorize a write, or skip reconstruction. A missing caller record is
therefore not an error, while a stale or mismatched supplied record fails
closed.

After those checks succeed, `report_generate.v2` enters the
**GOV-FINALIZE-FENCE-1** Run Control Unit of Work. At the start of that
transaction, before any manifest, Artifact, step, metrics, research or
lifecycle write, the repository adapter reacquires locks and rereads the
canonical job row and attempt `A`. Its first state-changing statement is a real
guarded compare-and-set against the existing lease row (a value-preserving
conditional update is sufficient; an ordinary read is not). The CAS must
predicate on all of the following facts at one database instant and affect
exactly one job/attempt pair:

- the job's `current_attempt_id` is still exactly `A`;
- attempt `A` still belongs to that job, has `attempt_number = N`,
  `worker_id = W` and `status = running`;
- the job still has `status = running` and `lease_owner = W`, so
  `attempt.worker_id = job.lease_owner = W`;
- `lease_expires_at` is still fresh according to the production Clock;
- worker `W` still exists, is authenticated and not retired, has immutable
  `worker_generation >= G`, and has the exact capability tuple `V` containing
  `kernel-mode-execution.v2` with the recomputed
  `worker_capability_hash`; and
- the job still pins exact v2 and `minimum_worker_generation = G`, and the
  recomputed fencing epoch equals `E` and the `fencing_epoch_hash` in both the
  candidate request and record.

SQLite adapters use `BEGIN IMMEDIATE`, then perform both locked rereads and the
predicate-bearing conditional update on that same connection. PostgreSQL
adapters lock the job and attempt in the repository's fixed order with
`SELECT ... FOR UPDATE` and perform the guarded update in that transaction;
other adapters must provide an equivalent write-excluding primitive. The
attempt predicate must participate in the CAS, for example through a guarded
`EXISTS`, rather than being a stale application-side observation. Locks are
held through commit.

If the rows or CAS do not satisfy every predicate or its affected-row count is
not exactly one, the transaction rolls back with zero writes. This includes
zero manifest, Artifact, step, metrics, research, job and attempt mutations.
A same-attempt, same-worker heartbeat that only extends `lease_expires_at`
during reconstruction is explicitly allowed: it leaves `E` unchanged, and the
final CAS may commit if the extended lease is fresh and every other predicate
still holds. An expired lease does not authorize a stale commit. If expiry is
followed by creation of a new current attempt `B`, then `current_attempt_id` and
`attempt_number` differ, the recomputed epoch differs, and A's CAS fails with
zero writes even when B is owned by the same worker `W` with the same generation
and capability hash. A may never substitute B into its reconstructed objects.

Only after that CAS succeeds, and while those locks remain held, the same Unit
of Work writes the closed v2 manifest Artifact, writes the `report_generate` step output and
`artifact_refs` binding to that exact Artifact and execution-record hash, and
marks only that step complete. These writes commit atomically; a manifest,
step-output/ref or step-completion failure rolls all three back. It does not call
`persist_war_room_result()`, write `research_runs`, write the research-run
projection Artifact, complete the lifecycle job, or complete the attempt. The
job and its current attempt remain `running` with `replay_archive` as the next
production phase. Thus a stored report record is a checkpoint comparison target,
not terminal authorization.

Report recovery is idempotent only within the same current attempt. After the
full current-attempt reconstruction, Run Control may accept an already-complete
`report_generate` step only when there is exactly one current-attempt manifest
and its raw bytes, closed fields, hashes, step output and Artifact ref equal the
newly reconstructed manifest and bindings exactly. It then performs no report
write. A duplicate manifest, a manifest without its atomic completed-step
bindings, a completed step without that exact manifest, or any mismatch fails
closed; recovery does not choose, overwrite, delete or repair a duplicate.

Under GOV-RECOVERY-1, if attempt A completed `report_generate.v2` but
`replay_archive.v2` failed, a new attempt B resets its authenticated checkpoint to
`checkpoint.next_step_key = "report_generate"` with selected version
`report-generate.v2`; it may not resume at replay from A's manifest. After
GOV-RETRY-1 has re-materialized every mode-required proof source and resolver
Artifact under B, B independently reconstructs a B request, record and manifest
and commits B's report Unit of Work. A's report remains immutable history.
There is no field-for-field equality requirement between A's and B's manifests:
equal semantic fields such as `result_hash` may recur, but A supplies no field
to B and the attempt-bearing proof, request, record, Artifact-ref and manifest
hashes are derived from B's current-attempt objects.

`replay_archive.v2` immediately performs a fresh reconstruction before any
research write. It reloads the current active attempt's resolver and proof
Artifact raw bytes, successfully compares every outer SHA, and only then
strict-decodes UTF-8, parses JSON, validates the selected closed schemas,
content hashes and claims. It then repeats the resolver field comparison,
Consistency evaluation, deterministic
replay and Kernel call and compares the newly
rebuilt request, record and final projection field-for-field with the closed
current-attempt report manifest. It does not reuse verified objects or a record cached by
`report_generate.v2`.

Only after that comparison succeeds does Run Control enter one repository Unit
of Work and apply GOV-FINALIZE-FENCE-1 again using the stable fencing identity
`A`, `N`, `W`, `G`, `V`, `worker_capability_hash` and `E` captured before this
replay reconstruction. `lease_expires_at` is not part of that epoch identity; a
same-attempt, same-worker heartbeat may extend it during reconstruction without
changing `E`. A report-phase CAS does not authorize the later replay phase. Only
after the replay-phase locked rereads and CAS succeed,
and while those locks remain held, that same database transaction makes
`persist_war_room_result()` write the `research_runs` projection, writes the
generic research-run projection Artifact, completes the `replay_archive` step,
writes lifecycle metrics, transitions the lifecycle job to `completed`, and
transitions that same active attempt to `completed`. All terminal IDs and
Artifact refs are bound into the replay-step output. Any research, Artifact,
step, metrics, job or attempt failure rolls back the entire Unit of Work and
leaves both job and attempt non-terminal.

An active/running attempt must have no pre-existing `research_runs` row or
research-run projection Artifact for its exact ownership tuple. Encountering
either one in `report_generate.v2`, `replay_archive.v2`, recovery, or the
terminal-write transaction is corruption and fails closed, even when every
stored field equals the freshly rebuilt result. There is no active-attempt
existing-projection success branch. The terminal Unit of Work rechecks absence
under the exact ownership tuple immediately before inserting; a uniqueness
conflict or concurrent appearance rolls back the whole Unit of Work and is not
reinterpreted as idempotent success.

For a non-null `lifecycle_job_id`, `persist_war_room_result()` may be invoked
only inside that Run Control Unit of Work with its repository transaction
supplied by the caller. It writes the research projection rows and returns
their identities; it owns no commit and never completes a step, job or attempt
itself. `successful`/`completed` describes the outcome of the enclosing Unit of
Work and is never used to select its input attempt.

The null-ID compatibility path is narrower than a generic v1 escape hatch. A
call with `lifecycle_job_id = null` is accepted only from the trusted internal
Simulation Runtime application port and only for the actual deterministic
engine mode. Its non-lifecycle null rule is exact: `organization_id`,
`project_id` and `run_id` are non-null trusted-port coordinates;
`lifecycle_job_id` and `attempt` are null together; and `session_id` is present
with its exact nullable value. It constructs neither a v2 Kernel request nor a
v2 execution record. A partial combination, including a null organization or
project, a non-null attempt without a lifecycle job, or a lifecycle job without
an attempt, fails closed. That port must carry, or the persistence function
must reconstruct from its complete internal inputs, a closed
`LegacyDeterministicProvenance` containing those ownership coordinates,
`scenario_request_hash`, pinned `rule_pack_id` and `rule_pack_hash`, and
`deterministic_result_hash`, `deterministic_source_hash` and
`world_state_hash`. Each hash is recomputed from the complete scenario request,
Rule Pack and deterministic result/source/state rather than trusted as a bare
caller string. The path rejects Agent aliases, hybrid, `hybrid_recorded` and
negotiation output, and it cannot be invoked through a controller, Provider,
user payload or another repository caller. Trust is conveyed by the typed
internal port/capability, never by a caller-provided flag or name. Boundary
tests must prove those other callers fail.

This uses the existing generic Artifact store and adds no table, Artifact
storage schema or public Artifact model. Under **GOV-RECOVERY-1**, a stored
runtime profile with no `execution_contract_version` marker is permanently a
legacy-v1 job: initial execution and every recovery select
`report-generate.v1` for `report_generate` and `replay-archive.v1` for
`replay_archive` (hereafter `report_generate.v1` and `replay_archive.v1`),
retain those checkpoints despite v2 introducing new step versions, and never
add or upgrade the missing marker. `report_generate.v1` writes the legal v1
report manifest and completes only the report step; `replay_archive.v1` owns
the legacy research projection and the same replay-step/metrics/job/attempt
terminal Unit of Work. It does not run the v2 Kernel-record reconstruction.
There is no explicit-v1-marker branch. A present marker selects the v2 path if
and only if its value is exactly `kernel-mode-execution.v2`; every other present
value is an unknown contract version and fails closed before either phase is
selected or mutated. A job may never mix a v1 report phase with a v2 replay
phase or the reverse. Already projected historical jobs remain readable. V2 recovery
must first rerun and pass the raw-byte outer-SHA comparison and only then rerun
the same strict UTF-8/JSON parse, closed-schema/content/claims validation,
current-active-attempt reconstruction,
resolver comparison, Consistency evaluation, deterministic replay and Kernel
call before it can continue, and a checkpoint record is only a comparison
target.

In `replay_archive.v2`, checkpoint validation is not sufficient by itself. The v2
execution record and every referenced Artifact must be synchronously rebuilt
and revalidated through the full in-function adapter and Kernel path immediately
before the terminal Unit of Work lets `persist_war_room_result()` perform the
`research_runs` write.

The only existing-projection return is a read-only duplicate GET for a job
whose canonical job row and `current_attempt_id` are both already terminal
`completed`, whose replay step is completed, and whose exact ownership tuple
selects exactly one manifest, research row and projection Artifact. Before
returning, that GET synchronously reloads the completed current attempt's
resolver and proof Artifact raw bytes, recomputes and successfully compares
every outer SHA, and only then strict-decodes UTF-8, parses JSON, validates the
selected closed schemas, content hashes and claims, reruns the applicable
resolvers and compares their complete outputs, reconstructs the complete
proof/request, reruns Consistency and deterministic replay, calls the Kernel,
and compares the rebuilt request, record and projection field-for-field with
the immutable stored objects. It may not trust a checkpoint or caller record
to short-circuit those operations. The path opens no active Run Control Unit of
Work, performs no insert/update/delete, lifecycle transition, metrics write or
step completion, and returns only after exact validation succeeds. Any wrong
status, partial or duplicate row set, ownership mismatch or tampering fails
closed without rewriting, repairing or deleting immutable history.

### Threat model

The fail-closed boundary treats Agent/Provider output and user-controlled
payloads as untrusted. Within this boundary it detects and rejects malformed,
corrupt or partial payloads and rows, cross-run or cross-organization
substitution, and replacement of any single source Artifact. In particular,
replacing its bytes and updating its row-level `artifact_sha256` still changes
the committed discriminator-specific `("proof", artifact_id,
artifact_sha256, content_hash, proof_schema, attempt)` or `("resolver",
artifact_id, artifact_sha256, content_hash, resolver_schema, attempt)` tuple
and is rejected against the independently retained producing completed-step
output/`artifact_refs` hash and checkpoint chain. Substituting one tuple kind
for the other also fails the closed checkpoint union. This claim
assumes those roots have not also been rewritten; relationships and later
request, record, manifest and projection bindings provide additional scoped
comparisons but are not presented as an external trust root. These failures are
rejected before that phase's governed write: report-phase failure precedes the
atomic manifest/step Unit of Work, and replay-phase failure precedes research
and terminal lifecycle persistence.

This ADR does not defend against arbitrary code execution in the Run Control or
Kernel process. It also does not detect an attacker who can coordinate a rewrite
of the database payloads and rows together with every affected outer SHA,
content hash, producing-step output and `artifact_refs` hash, checkpoint,
relationship target, runtime-profile, request, record, report and projection
hash root. Such an attacker can manufacture a new internally consistent
database. A future ADR must define an external trust root, such as signatures
or MACs with keys held outside this database and/or WORM retention. Until that
work exists, this ADR must not claim detection of either excluded attacker.

### Rollout

Deployment is worker-first under **GOV-WORKER-1** and uses the existing worker
metadata seam. Every freshly registered worker has a deployment-assigned,
strict positive integer `worker_generation` and the exact metadata key
`execution_contract_versions`; the latter is a tuple of version strings that
is unique and sorted in ascending UTF-8 byte order. Both values are
authoritative registration metadata, not self-asserted claim-request fields. A
worker is v2-capable if and only if its tuple contains
`kernel-mode-execution.v2`. Missing, malformed or unknown identity, generation
or capability metadata fails closed.

Generation `G` is a rollout hard fence. Before enabling creation of any profile
with `minimum_worker_generation = G`, deployment must stop every pre-`G` worker
process, permanently retire its worker identity in the existing worker/control
plane, disable its supervisor and autostart path, and revoke its database and
queue execution credentials. Credentials are not shared across generations;
the new workers receive distinct identities and credentials. Retirement is
monotonic: rollback or a late heartbeat may not reactivate an old identity.
The heartbeat path authenticates the identity before updating freshness and
rejects a retired or unknown identity; after credential revocation a revived
old process is unauthenticated in any case. A retired or unknown identity may
never claim any lifecycle job, and a missing or lower generation may never
claim a v2 job.

An eligible worker for the creation check is a non-retired, authenticated
existing lifecycle worker whose lifecycle status is active and whose last
heartbeat is within the existing configured worker-freshness interval.
Inactive or stale workers do not participate, but missing/unknown metadata does
not count as support. Job creation may pin a new job to v2 generation `G` only
when that eligible set is nonempty and every member advertises v2 and has
`worker_generation >= G`; thus the gate observes at least one fresh active
worker and all such workers meet the pinned minimum generation. An empty set
fails the gate; universal quantification over an empty set is never support.

In a direct-SQLite deployment, every worker generation runs under a dedicated
OS service account that is not shared with an older identity or an operator's
interactive account. Before v2 creation can open, deployment achieves full
old-process quiescence, permanently disables every old supervisor/autostart
path, and removes the old service accounts' read, write, create, delete, list
and directory-traverse rights from both the SQLite database file and its entire
containing directory. The new-generation account receives the minimum required
NTFS ACL independently; process identity is not treated as revocable unless the
file and directory ACL actually enforce that separation.

Deployment then acquires the existing exclusive v2 deployment lock and keeps
both that lock and the generation-separated ACL continuously enforced until
every v2-pinned job in that database is terminal, including queued or running
jobs that are later completed, failed, abandoned or explicitly cancelled. The
lock/ACL interval is therefore the complete v2-job lifetime, not merely the
enablement transaction or creation-gate check. Rollback, restart, a late old
process and a supervisor revival may not shorten it. If the deployment cannot
maintain this hard OS-account/ACL isolation and exclusive lock for that whole
interval, direct-SQLite v2 is permanently disabled in that deployment; an
attestation, health check or temporary quiescence is no substitute.

In the existing job-claim transaction, a v2 job's hashed runtime-profile
marker and `minimum_worker_generation`, plus the claiming worker's
authenticated non-retired identity, `worker_generation` and current
`execution_contract_versions` tuple, are read and checked atomically before
any lease/owner or attempt mutation. The worker must advertise exact v2 and its
generation must be at least the profile minimum. A failed or unknown check does
not claim the job, write or consume a lease, or create, increment or consume an
attempt. A profile with no execution-contract marker is v1 under
GOV-RECOVERY-1 and remains claimable only by a current authenticated,
non-retired worker through the existing v1 compatibility path, without being
rewritten or opportunistically upgraded. A present marker other than exact
`kernel-mode-execution.v2`, or an exact v2 marker with an absent/invalid
minimum generation, fails the claim transaction before mutation and is never
reinterpreted as v1.

These generation, retirement, credential and direct-SQLite requirements are
the rollout hard fence. They reuse the existing runtime profile, worker
metadata/control plane, credentials and deployment lock/attestation; they add
no microservice or database table.

A job pinned to `kernel-mode-execution.v2` must never be processed by an old
worker, including during rollback. Rollback first disables creation of new v2
pins, then lets v2-capable workers drain active and queued v2-pinned jobs to a
terminal state or explicitly cancels the remaining jobs. Each cancellation is
the permanent same-job terminal state defined above, not a pause. Only after
every v2-pinned job is terminal may the worker/report implementation be
reverted or a direct-SQLite deployment release its exclusive lock and
generation-separated ACL. Claim refusal is a safety boundary, not a retryable
invitation to an older worker.

### Performance gates

**BENCH-01 — frozen fixtures and isolation.** The thresholds and protocol are
fixed before implementation measurement and must not be relaxed after any
result is observed. The benchmark runs with network access denied and a
Provider seam that counts and fails every call. For each representative mode,
the benchmark precommits two separately legal SQLite fixture files: a real
legacy-v1 control and a real v2 treatment. The authoritative pair metadata is a
committed `benchmark-fixture-manifest.v1` file. It is a closed payload with
exactly `schema_version`, `fixture_id`, `normalized_kernel_mode`, `control`,
`treatment`, `semantic_workload_manifest_sha256`, `benchmark_logical_time`,
`production_clock`, `pair_diff_allowlist` and `fixture_manifest_hash`; every
key is required and additional keys fail. `control` and `treatment` each have
exactly `database_sha256`, `schema_revision`, `row_inventory_hash` and
`artifact_inventory_hash`, all lowercase 64-hex strings except the non-empty
schema revision. `production_clock` has exactly `adapter_id`,
`adapter_sha256` and `wall_time_chain_hash`, with the latter two lowercase
64-hex strings. `pair_diff_allowlist` has exactly `schema_version` (the exact
string `benchmark-pair-diff-allowlist.v1`) and `entries`, an ordered array
exactly equal to `["runtime_profile", "source_artifact_enrichment",
"completed_step_chain", "report_projection_manifest",
"replay_research_projection"]`; duplicate, unknown or reordered entries
fail. `benchmark_logical_time` is the one canonical JSON timestamp
value used by both members. Its digest has this one exact preimage:

```text
fixture_manifest_hash = H({"schema_version":"benchmark-fixture-manifest.v1",
 "fixture_id":fixture_id,"normalized_kernel_mode":normalized_kernel_mode,
 "control":control,"treatment":treatment,
 "semantic_workload_manifest_sha256":semantic_workload_manifest_sha256,
 "benchmark_logical_time":benchmark_logical_time,
 "production_clock":production_clock,
 "pair_diff_allowlist":pair_diff_allowlist})
```

The repository commits the manifest bytes and their outer SHA-256 alongside
each fixture pair. Generation/refresh must update both database members,
their complete inventories, the fixed Clock metadata, the allowlist and this
digest together; a fixture with a missing, surplus or stale manifest field is
invalid before cloning or timing. The fixture manifest records each member's
own committed database-file SHA-256, generating revision and complete
row/Artifact inventory. It also records one fixed `benchmark_logical_time` and
the production `Clock` adapter identity used for every production time read and
write exercised by the benchmark.

Fixture sealing is part of generation, not a benchmark-time repair. After the
last fixture write, the generator first closes every connection except its one
finalizing connection, executes `PRAGMA wal_checkpoint(TRUNCATE)`, requires a
successful empty/truncated result, executes `PRAGMA journal_mode=DELETE`,
requires the returned mode to be exactly `delete`, and then cleanly closes that
last connection. Only after that close does it assert that no sibling
`<database>-wal`, `<database>-shm` or `<database>-journal` file exists and
compute the committed main-database SHA-256. A fixture with any such sidecar is
invalid; the generator may not hash a partial file set or rely on a later open
to recover visible state. Consequently the committed main-database SHA binds
all SQLite-visible fixture semantics in the cleanly closed member.

Every clone operation repeats the boundary assertions explicitly. Immediately
before copying, the harness verifies the immutable source main-database SHA and
the absence of all three source sidecars. It copies only that closed main file
into a new isolated temporary path. Immediately after copying and before the
first destination open, it verifies the destination main-file SHA and asserts
that no destination `-wal`, `-shm` or `-journal` sidecar exists. Every
benchmark invocation therefore starts from the same sealed main-file bytes;
the pair is not required or expected to have equal database bytes or hashes,
source-Artifact inventories or source-Artifact payload bytes/ids.

The repository commits one closed `benchmark-environment.v1` manifest with one
official release variant: Windows x86-64. Its top-level keys are exactly
`schema_version`, `platform`, `runner_image_digest`, `windows`, `cpu`, `power`,
`memory`, `benchmark_process`, `worker_process`, `storage`, `filesystem`,
`linux`, `python`, `sqlite`, `dependency_lock`,
`benchmark_concurrency_limit`, `page_cache_protocol`,
`background_noise_protocol`, `sqlite_pragmas` and `fixture_sealing`.
`schema_version` is the exact string `"benchmark-environment.v1"`, `platform`
is the exact string `"windows-x86_64"`, and `runner_image_digest` is a lowercase
64-hex SHA-256 string; tags are not schema members.

Every nested record is closed. `windows` has exactly the non-empty string
fields `product_name`, `edition`, `display_version`, `build_number` and
`kernel_version`, plus strict non-negative integer `update_build_revision`.
`cpu` has exactly non-empty strings `vendor` and `model`, strict non-negative
integers `family`, `model_number`, `stepping` and `logical_processor_count`, and
`logical_cpu_affinity`, a non-empty array of unique strict non-negative
integers in ascending order. `power` has exactly `power_scheme_guid`, a
lowercase canonical UUID string; `minimum_processor_state_percent` and
`maximum_processor_state_percent`, strict integers in `0..100` with minimum no
greater than maximum; and `processor_performance_boost_mode`, a strict
integer in `0..6`. The committed value of every power field is exact.
`memory` has exactly strict positive integers `physical_total_bytes`,
`channel_count` and `numa_node_count`, non-empty ordered string array
`channel_configuration`, and `numa_node_logical_cpu_sets`, a non-empty ordered
array of non-empty ascending unique strict non-negative-integer arrays.

`benchmark_process` and `worker_process` each have exactly non-empty strings
`priority_class` and `scheduling_class`, strict non-negative integer
`processor_group`, and non-empty ascending unique strict non-negative-integer
array `logical_cpu_affinity`. `storage` has exactly non-empty strings
`device_model`, `device_firmware_revision`, `bus_type`, `controller_model`,
`controller_firmware_revision`, `controller_driver_name` and
`controller_driver_version`; strict positive integers `logical_block_bytes`
and `physical_block_bytes`; and JSON booleans `write_cache_enabled` and
`trim_enabled`. `filesystem` has exactly `type = "NTFS"`, non-empty string
`version`, strict positive integer `allocation_unit_bytes`, JSON booleans
`compression_enabled`, `encryption_enabled`, `last_access_updates_enabled` and
`short_name_creation_enabled`, and `mount_options`, an ordered array of unique
non-empty strings.

`linux` has exactly `power_governor`, `io_scheduler`, `queue_nr_requests`,
`queue_read_ahead_kb` and `queue_rq_affinity`; each key is present with JSON
null in this sole official variant. These are the only nullable fields in the
manifest. `python` has exactly non-empty strings `implementation`, `version`,
`build` and `abi`, plus lowercase 64-hex string `executable_sha256`. `sqlite`
has exactly non-empty string `runtime_version` and ordered unique non-empty
string array `compiler_options`. `dependency_lock` has exactly non-empty string
`path` and lowercase 64-hex string `sha256`.
`benchmark_concurrency_limit` is a strict positive integer.
`page_cache_protocol` has exactly non-empty strings `scope`, `command_line`,
`api_name`, `privilege` and `observed_result`, ordered non-empty string arrays
`sample_classification_sequence`, `sync_barrier_sequence` and
`clone_relative_order`; every classification entry belongs to the closed set
`["cold", "warm"]`. `background_noise_protocol` has exactly non-empty strings
`scope`, `quiescence_command` and `observed_result`, plus ordered unique
non-empty string arrays `allowed_processes`, `allowed_services`,
`observed_processes` and `observed_services`. Unless a stricter rule is stated
above, strings are non-empty JSON strings, arrays are JSON arrays in committed
order, integers are strict JSON integers, booleans are JSON booleans, and
values are non-null.

`sqlite_pragmas` is one closed record with exactly `journal_mode`,
`synchronous`, `page_size`, `cache_size`, `temp_store`, `mmap_size`,
`wal_autocheckpoint`, `journal_size_limit`, `locking_mode`, `busy_timeout`,
`foreign_keys`, `automatic_index`, `fullfsync` and `checkpoint_fullfsync` at
each specified connection probe point. `journal_mode` and `locking_mode` are
non-empty strings; every other value is a strict integer, and
`foreign_keys`, `automatic_index`, `fullfsync` and `checkpoint_fullfsync` are
restricted to `0` and `1`. `fixture_sealing` has exactly
`wal_checkpoint_truncate_result`, a three-element array of strict integers,
and `journal_mode_delete_result`, the exact string `"delete"`.
The live probe must obtain these values from the actual production connections;
a configured value that differs from the effective PRAGMA result is a
mismatch. Unknown, missing and additional manifest fields fail its closed
schema. The machine report binds the committed manifest file SHA-256, records
the complete live probe and lists every mismatch. `official_environment_match`
is true only for field-for-field, type-for-type equality of the complete live
probe to every top-level and nested manifest field, including array order and
all five explicit Linux nulls. Any unequal field, unequal type, omitted field,
surplus field, image tag, version range, substituted device and substituted
host makes the run informational.

The harness injects a fixed-value, non-advancing production `Clock` port whose
every observation returns `benchmark_logical_time`. The committed running
owner/lease in both pair members is fresh at that value, and control and
treatment receive the same adapter and identical logical-time schedule. Every
production path observed by the BENCH-04 pre/post row diff obtains time only
through that port: all lease time reads and writes, and every created, updated
or completed timestamp on lifecycle events, Artifacts, steps, the job and the
attempt. A direct wall-clock read on any such path invalidates the sample. The
normal production claim/resume path still checks and, where required, writes
the lease; the harness does not rewrite database or lease bytes after SHA
verification, advance an expiry, bypass a claim, or call an internal phase
helper. The fixed logical Clock is distinct from the monotonic measurement
clock and does not determine duration metrics. Outside the benchmark, the
production Clock adapter continues to use wall time, while pure finalization
remains clock-free. If the production-injected Clock port does not cover every
one of those reads and writes, completing that routing is an implementation
gate: the benchmark and release gate may not substitute a test-only
monkeypatch, direct timestamp rewrite or stale-lease bypass.

A static architecture test scans the committed benchmark harness and the
complete run-lifecycle critical-module set and rejects direct wall-time calls,
including `datetime.now()`, `datetime.utcnow()`, `time.time()` and equivalent
library or aliased forms. The sole allowlisted caller of a wall-time primitive
is the concrete production `Clock` adapter; monotonic duration instrumentation
remains separate and may not supply lifecycle time. For every warmup and
measured sample, the benchmark emits an auditable ordered Clock-call trace and
its exact count. Each entry records call ordinal, adapter identity, read/write
operation and purpose, returned logical time, and the applicable
job/run/attempt/step and lease owner/expiry coordinates. The trace covers every
observation, including lease-freshness or lease-expiry reads that cause no
timestamp write. The reported count must equal the trace length, and the trace
must match the fixed schedule and the production-path coordinates; an
untraced, multiply counted or coordinate-free Clock read invalidates the
sample.

That static and runtime audit extends across the complete SQL and native
boundary. The static input set includes ORM metadata, migrations, checked-in
and generated schema DDL, column server defaults, triggers and production SQL
used by the benchmark-critical lifecycle tables. That table set is every table
read or written by the BENCH-04 path, including job, attempt, step, lifecycle
event, Artifact, research/projection and lifecycle-metric tables. Those tables
may not use
`CURRENT_TIMESTAMP`, `CURRENT_DATE`, `CURRENT_TIME`, SQLite
`datetime('now')`, `date('now')`, `time('now')`, `julianday('now')`, a no-argument
`unixepoch()`, or any backend-equivalent native wall-clock expression in a
default, trigger or statement; every governed timestamp write must bind the
value obtained from the production `Clock` port explicitly. The runtime report
binds the effective schema/default/trigger inventory and an ordered SQL-write
audit to the Clock trace, so an omitted time column, an implicit default, a
trigger-generated time or a bound value without the corresponding Clock call
invalidates the sample.

The audit also derives the complete transitive native/binary dependency set
from the locked environment and records each loaded module's identity, version,
exported time symbol and SHA-256 plus its wall-clock/monotonic classification.
Exactly one production wall-time call chain is permitted: the concrete,
hash-pinned production `Clock` adapter entry point through one ordered,
hash-pinned native dependency chain to the operating-system wall-time
primitive. The fixture manifest commits
`production_clock.wall_time_chain_hash = H(ordered complete
module/symbol/version/SHA-256 tuples)`, and the live inventory and runtime trace
must reproduce that unique chain exactly. The fixed benchmark adapter still
returns `benchmark_logical_time`; the allowlist identifies the production call
chain under test and cannot authorize a second caller or timestamp source.

Outside that one chain, native dependencies may expose only the separately
allowlisted monotonic duration source and may neither read nor transform wall
time, supply lifecycle time, or write a benchmark-critical timestamp. Any
second wall-time path, direct OS-clock call, unpinned binary, unknown symbol,
unknown/unclassified time source or digest mismatch invalidates the run. The
same unique pinned wall-time chain is the only native wall-time path allowed in
production outside the benchmark; the pure Kernel remains clock-free.

For each pair the repository also commits one closed
`semantic-workload-manifest.v1` benchmark data file. It is fixture metadata,
not a runtime Artifact: it is never inserted into the generic Artifact store,
referenced by a lifecycle step, supplied to production execution or included in
any timer. The fixture generator takes one immutable captured transcript for
the mode, records the transcript's exact file SHA-256 in this manifest, and
generates both the control and treatment from that same capture. Independently
authored or separately sampled control and treatment transcripts are forbidden.
Fixture generation/refresh must update the two committed database SHA values,
the recorded fixed Clock metadata and the exhaustive pair-diff report together;
the copied database and its lease bytes then remain immutable during a run.

**BENCH-02 — shared semantic workload and legal routing.** A pair shares exactly
the canonical scenario, Rule Pack id/hash/canonical bytes, normalized Kernel
mode, fixed integer seed in both the job and scenario, deterministic baseline,
mode-governed nullable
Agent Pack/context semantic outputs, and expected mode-final semantic result.
The baseline and final engine-result semantic projections must compare
field-for-field equal. Deterministic pairs have null Agent Pack/context values;
every Agent-capable pair normalizes the legacy sources and the v2 resolver
Artifacts to the same complete non-null Agent Pack and closed constraint
context before comparing their hashes.

The benchmark has schema-specific normalizers for the independently legal v1
and v2 source payloads. After removing only contract-wrapper, proof-lineage and
storage-identity fields, each normalizer emits the complete closed semantic
object committed in `semantic-workload-manifest.v1`. Its exact digest is:

```text
semantic_workload_digest = H({
 "schema_version":"semantic-workload-manifest.v1",
 "capture_transcript_sha256":capture_transcript_sha256,
 "scenario_hash":scenario_hash,"rule_pack_id":rule_pack_id,
 "rule_pack_hash":rule_pack_hash,"normalized_kernel_mode":normalized_kernel_mode,
 "effective_seed":effective_seed,
 "agent_pack_hash":agent_pack_hash,
 "constraint_context_hash":constraint_context_hash,
 "baseline_world_state_hash":baseline_world_state_hash,
 "final_world_state_hash":final_world_state_hash,
 "counts":counts,"hybrid_workload":hybrid_workload,
 "negotiation_ticks":negotiation_ticks})
```

There are no omitted defaults or additional digest keys. Every non-null hash in
this preimage is recomputed from the complete canonical value; a digest stored
in a runtime payload is not substituted for its preimage. `counts` has exactly:

```text
{"hybrid_proposal_count":hybrid_proposal_count,
 "hybrid_fc_decision_count":hybrid_fc_decision_count,
 "hybrid_fc_accepted_count":hybrid_fc_accepted_count,
 "hybrid_modifier_input_count":hybrid_modifier_input_count,
 "negotiation_tick_count":negotiation_tick_count,
 "negotiation_projection_tick_count":negotiation_projection_tick_count,
 "negotiation_message_count":negotiation_message_count,
 "negotiation_proposal_count":negotiation_proposal_count,
 "negotiation_ac_decision_count":negotiation_ac_decision_count,
 "negotiation_ac_accepted_count":negotiation_ac_accepted_count,
 "negotiation_cl_transition_count":negotiation_cl_transition_count,
 "negotiation_cl_entry_count":negotiation_cl_entry_count,
 "negotiation_eligible_count":negotiation_eligible_count,
 "negotiation_pc_decision_count":negotiation_pc_decision_count,
 "negotiation_pc_accepted_count":negotiation_pc_accepted_count,
 "negotiation_modifier_input_count":negotiation_modifier_input_count,
 "negotiation_nd_input_count":negotiation_nd_input_count}
```

Every count is recomputed from the corresponding collection and is zero when
that collection is inapplicable. `negotiation_projection_tick_count` is
`sum(p[1..T])`, and each ND input count is the length of the ordered proposal
collection inside that tick's complete ND input.

For `hybrid`, `hybrid_workload` has exactly:

```text
{"proposals":[complete_canonical_proposal,...],
 "fc_decisions":[complete_semantic_fc_decision,...],
 "fc_accepted_proposal_ids":[proposal_id,...],
 "modifier_semantic_inputs":[complete_modifier_semantic_input,...]}
```

These are the production proposal and decision orders and the complete ordered
semantic input objects actually passed to the production Action Adapter;
`negotiation_ticks` is empty. For `negotiation`, `hybrid_workload` is null and
`negotiation_ticks` has exactly `T` entries in ascending tick order. Each tick
has exactly:

```text
{"tick":tick,"messages":[complete_canonical_message,...],
 "proposals":[complete_canonical_proposal_with_origin,...],
 "ac_decisions":[complete_semantic_ac_decision,...],
 "ac_accepted_proposal_ids":[proposal_id,...],
 "cl_transitions":[complete_semantic_ledger_transition,...],
 "cl_snapshot":[complete_semantic_ledger_entry,...],
 "el_eligible_proposal_ids":[proposal_id,...],"p":p,
 "pc_decisions":[complete_semantic_pc_decision,...],
 "pc_accepted_proposal_ids":[proposal_id,...],
 "modifier_semantic_inputs":[complete_modifier_semantic_input,...],
 "nd_input":complete_nd_semantic_input,
 "counts":{"message_count":message_count,"proposal_count":proposal_count,
  "ac_decision_count":ac_decision_count,
  "ac_accepted_count":ac_accepted_count,
  "cl_transition_count":cl_transition_count,"cl_entry_count":cl_entry_count,
  "eligible_count":eligible_count,"pc_decision_count":pc_decision_count,
  "pc_accepted_count":pc_accepted_count,
  "modifier_input_count":modifier_input_count,
  "nd_input_count":nd_input_count}}
```

The messages, proposals, decisions and transitions retain their production
order. `cl_snapshot` is the complete post-transition snapshot. `p` is the strict
integer `0` or `1` derived from EL. Both PC arrays and the modifier-input array
are empty exactly when `p=0`. The complete ND semantic input includes its
ordered input proposals and complete state request. For `deterministic`, the
two mode-specific members are respectively null and empty and all counts are
zero. Object encoding and ordering use this ADR's canonical-JSON rules; array
order is semantic and may not be sorted or discarded by the normalizer.

The representative workloads have a mandatory non-zero shape. The hybrid
capture contains at least four complete proposals and its recomputed FC/PA/MB
facts include at least one accepted proposal that produces a numeric state
change, at least one accepted proposal whose deterministic application has no
numeric effect, and at least one rejected proposal. The negotiation capture
has at least three ticks with `p=1` and at least one tick with `p=0`. Across its
complete production-ordered ticks it contains at least one Commitment Ledger
entry that transitions `proposed -> active`, one candidate rejected by PC, one
accepted deterministic-modifier application, one non-empty narrative ND with
`attempted=true` and `application_count > 0`, and one non-empty numeric-no-op PA
whose `before_result_hash == final_result_hash`. These are semantic-workload
assertions recomputed from the complete objects and counts, not labels or
padding; fixture generation and preflight reject a capture that misses any one
of them. One event may satisfy multiple compatible assertions, but no duplicate
proposal, synthetic transition or surplus Artifact may be added to manufacture
the shape.

The control-normalized object and treatment-normalized object must each compare
field-for-field with the committed object and with each other, and all three
recomputed `semantic_workload_digest` values must be identical. V2 wrapper and
proof enrichment and storage identity are the only information removed by
normalization. In particular, equal baseline/final hashes alone cannot excuse a
different intermediate workload.

The control stores a legal production legacy-v1 runtime profile in which
`execution_contract_version`, `effective_seed`, `minimum_worker_generation`,
`agent_pack_resolver_version`,
`constraint_context_resolver_version` and `evaluator_version` are absent; that
absence is the implicit legacy-v1 contract and selects production
`report-generate.v1` and `replay-archive.v1`.
The treatment stores the same common profile fields plus
`execution_contract_version = "kernel-mode-execution.v2"` and
`effective_seed` equal to the shared fixed integer,
`minimum_worker_generation` equal to the committed treatment generation, plus
the three pinned resolver/evaluator version keys, and selects production
`report-generate.v2` and `replay-archive.v2`. The harness never inserts,
rewrites or removes any of those six keys after fixture commitment.

**BENCH-03 — independently legal checkpoints.** Each member is an exact
post-`consistency_audit`, pre-report checkpoint, not a queued job that would
execute an engine or Provider path. In its own database it has one running
`run_jobs` row at the production post-audit progress value, one current running
attempt numbered 1, and exactly four completed current-attempt steps in
production order: `scenario_compile`, `environment_prepare`,
`deterministic_run` and `consistency_audit`. Its owner/lease is legal, its
resume step is `report_generate`, and is fresh under the fixture manifest's
injected production Clock. It has no report/replay step, report or
projection Artifact, partial step, earlier attempt or unreferenced Artifact.
Every stored step uses the production version legal for that member; its input
chain names the exact preceding step output and Artifact refs, and every input
hash, output hash and outer Artifact SHA-256 is recomputed and valid within
that database.

The control contains the real checkpoint and source Artifact set, types, schema
versions, cardinalities and relationships that production legacy v1 emits and
consumes for that mode. It contains no v2 execution record and no V2-only `NP`,
`EL`, `consistency-audit.v3`, `narrative-diffusion.v2` or
`negotiation-replay.v2` source. The treatment contains the complete v2 matrix
source set: `FC` for `deterministic`; `AR, PB, FC, MB, CL, PA, HR` for
`hybrid`; and `RR[1..T], NP[1..T], AC[1..T], CL[1..T], EL[1..T],
PC[p[t]=1], FC, MB[p[t]=1], ND[1..T], PA[p[t]=1], NR` for
`negotiation`, with the exact registry versions and relationships. Thus the
applicable V2-only `NP`, `EL`, v3 Consistency wrappers, ND v2 and NR v2 proof
costs are present in the treatment and absent from the control, but those
objects may only enrich or wrap the semantic workload committed in BENCH-02.
The deterministic treatment has no context resolver Artifact. Each
Agent-capable treatment also contains exactly the two post-baseline resolver
Artifacts bound by its completed `deterministic_run` step; recovery regenerates
and compares them during the measured production path.
Neither fixture may contain a semantic operation absent from that manifest.
The control may not be padded with extra messages, proposals, decisions,
ledger transitions, modifier or diffusion inputs, duplicate rows/Artifacts or
other work, and the treatment may not omit, collapse, pre-apply or cache any of
them. A heavier-control/lighter-treatment pair is invalid rather than a valid
performance sample.

**BENCH-04 — exhaustive pair-diff allowlist.** The fixture manifest fixes this
closed allowlist, and the pair report records the complete pre- and
post-execution path-level diff and classifies every difference under it:

1. `runtime_profile`: absence versus presence of exactly the six treatment runtime-profile keys in
   BENCH-02: `execution_contract_version`, `effective_seed`,
   `minimum_worker_generation`, `agent_pack_resolver_version`,
   `constraint_context_resolver_version` and `evaluator_version`, plus the
   resulting canonical runtime-profile bytes and hash;
2. `source_artifact_enrichment`: the legal source-Artifact set: type, schema version, cardinality, order,
   Artifact id, contract/identity wrapper fields, relationship targets,
   canonical outer payload bytes and outer SHA-256, but only where the
   difference is V2 resolver/wrapper/proof enrichment or storage identity and both
   payloads normalize to the identical committed BENCH-02 semantic value;
3. `completed_step_chain`: completed-step `artifact_refs`, the Artifact-ref/identity fields in that step
   output and its `output_hash`, plus the immediately following step input fields
   and `input_hash` that are causally derived from that output/ref chain;
4. `report_projection_manifest`: the selected report-step version and its causally derived input, output,
   `artifact_refs` and hashes, plus the report Artifact set, type, schema
   version, Artifact id, payload bytes, outer SHA-256 and treatment-only embedded
   v2 execution record and `proof_hash` produced by the selected production
   path; no complete proof is embedded in the report manifest; and
5. `replay_research_projection`: the selected replay-step version and causal report-record bindings, its
   input/output, `artifact_refs` and hashes, plus contract-specific research
   provenance/projection-Artifact identity and lifecycle-metric duration/hash
   fields produced by completing the full selected production path. The
   normalized research result, terminal job/attempt state and terminal IDs must
   still compare equal.

The report must print every differing path, both values and exactly one
allowlist reason. Differences in items 2 through 5 are permitted only when they
are the causal closure of the profile/contract and legal source-set differences
above.
The two committed database SHA values are independently authenticated fixture
provenance, not a license for arbitrary row differences. All business inputs,
job/run, attempt and completed-step identities, and baseline/final engine-output
semantics remain equal. The report also prints both normalized semantic
manifests and their recomputed digests; no normalized field is allowlisted to
differ. Any other input, engine-output semantic, workload count or member,
seed, Rule Pack, normalized mode, checkpoint position, row field or derived-hash
difference invalidates the pair. Source-Artifact payload bytes and Artifact ids
are compared and reported under the allowlist; byte and identity equality is
not required, but a semantic difference hidden inside those bytes is forbidden.
The fixture `benchmark_logical_time`, production Clock adapter identity and
committed owner/lease bytes must be identical for control and treatment. They
are fixture validity requirements, not allowlisted differences, and a harness
mutation of any of them invalidates the sample. No timestamp path is
allowlisted to drift: a row present in both members must have equal time fields,
and every time field on an otherwise permitted treatment-only row must equal
the value dictated by the same fixed Clock schedule rather than an arbitrary
wall-clock value.

**BENCH-05 — production validation and completion.** Before any warmup or
measured sample, the harness creates one dedicated, disposable preflight clone
of each committed fixture member. Only on those preflight clones it loads the
job through the production repository and calls
`load_verified_checkpoint(job)`. Both calls must independently pass,
authenticate exactly that member's legal source set and return
`checkpoint.next_step_key == "report_generate"`; production routing must
select `report-generate.v1` for the key-absent control and
`report-generate.v2` for the treatment, followed respectively by
`replay-archive.v1` and `replay-archive.v2`. The Provider counter must be zero.
On those same preflight clones, the harness reconstructs each normalized
semantic workload from the independently verified source payloads, recomputes
the BENCH-02 digest and performs both field-for-field comparisons. It then
discards the clones and all checkpoint, payload and normalizer results. This
preflight validates the fixture and protocol only; neither clone nor any
duration or cached result from it is a warmup or measured sample.

Every warmup and measured invocation uses a different fresh clone made
directly from the same immutable committed fixture using BENCH-01's explicit
pre-copy source-sidecar and post-copy destination-sidecar assertions, and
verifies its complete database-file SHA-256 before opening it. That whole-file
fixture check is not an Artifact `artifact_sha256` verification. Matching the
committed sealed main-file SHA
binds the fresh clone to the already preflighted bytes and therefore to the
BENCH-02 comparisons without reading any Artifact payload on the sample clone.
Before its combined-lifecycle timer starts, the harness may not call
`load_verified_checkpoint`, run either normalizer, read source
`content_json`, perform an outer-SHA comparison or construct a verified-payload
cache on that clone. No repository object, decoded payload or verification
result crosses from a preflight clone into a sample clone.

With the combined-lifecycle timer running, the harness invokes the same
production worker claim/resume `process_job(run_id)` entry, with the production
Clock port fixed as BENCH-01 requires. That production entry performs its
ordinary checkpoint load, verification and routing on the fresh sample clone.
Each job must legally validate its fresh committed lease, complete both
selected production steps, persist its research projection and lifecycle
metrics, and finish with job and attempt `completed`, while leaving its
Provider counter at zero. The harness may not call a report/finalization helper
directly, mutate either profile or checkpoint, force a selector, prepopulate
the report, stub verification, or use a test-only bypass of lease claim or
phase completion.

**BENCH-06 — modes, pairing and order.** The p95 benchmark covers the three
representative normalized Kernel modes `deterministic`, `hybrid` and
`negotiation`. The engine aliases `mock_agent`, `controlled_agent` and
`hybrid_recorded` are covered by functional integration tests of their
normalization, proof requirements and v2 report/replay checkpoints, not by separate p95
gates. For each representative mode, run three unreported warmup **pairs**,
followed by 30 measured control/treatment **pairs**. A pair uses fresh isolated
copies of the two precommitted fixtures. Number the 33 pair rounds from zero
without resetting after warmup. Within each mode's pair, run control then
treatment on even rounds and treatment then control on odd rounds. Across a
pair round, use this fixed six-round mode-order cycle, then repeat it:

1. `deterministic`, `hybrid`, `negotiation`;
2. `hybrid`, `negotiation`, `deterministic`;
3. `negotiation`, `deterministic`, `hybrid`;
4. `negotiation`, `hybrid`, `deterministic`;
5. `hybrid`, `deterministic`, `negotiation`;
6. `deterministic`, `negotiation`, `hybrid`.

**BENCH-07 — statistics and timer boundaries.** Use a monotonic high-resolution
clock. Every measured duration is retained as the raw integer nanosecond
difference between its recorded monotonic endpoints; no value is rounded,
converted to display milliseconds or corrected by subtracting another timer.
For 30 values, nearest-rank p95 is the raw value at one-based rank
`ceil(0.95 * 30) = 29` after ascending sort.

Each fresh control and treatment sample records `lookup_outer_sha_ns`. Its
production instrumentation covers the non-overlapping lookup/verification
spans used to load the job, checkpoint and Artifact rows and to read, hash and
compare each Artifact's raw bytes for the first time on that clone. In
particular, every first outer-SHA comparison performed by the measured
`process_job(run_id)` is charged to this raw value; a comparison performed on a
discarded BENCH-05 preflight clone cannot satisfy it. For the treatment's
report source set, the final such first comparison completes immediately before
the stored-finalization timer starts. A later production re-read or repeated
outer-SHA verification is not renamed "first" and is charged to the production
phase in which it occurs. The lookup/first-SHA spans are excluded only from the
stored-finalization sub-timer; they remain inside the combined lifecycle.

The raw `stored_finalization_ns` value is recorded only for the v2 treatment
inside production `report_generate.v2`; it is never moved to fixture
preparation or `replay_archive.v2`. It starts only after every report-source
payload's first raw-byte outer-SHA comparison has succeeded on that fresh
sample clone. It includes resolver regeneration and field-for-field comparison
where applicable, strict parsing, closed-schema and canonical-content
validation, stored-only replay, baseline/final projection construction,
`ModeExecutionAdapter` proof construction, the pure Kernel
`finalize_execution()` call and execution-record serialization, and stops
before report Artifact persistence. If production re-reads bytes or repeats an
outer-SHA verification after this timer starts, that repeated work remains
inside `stored_finalization_ns`; no repeated SHA may be reported as, or used as
a substitute for, the first comparison. No verified-payload cache may suppress
a production-required re-verification. The fresh reconstruction performed
later by `replay_archive.v2` is outside this sub-timer but remains inside the
combined lifecycle.

The combined-lifecycle timer starts from the corresponding member's legal
pre-report checkpoint immediately before the production worker claim/resume
entry and ends only after the terminal `replay_archive` Unit of Work commits the
replay step, lifecycle metrics, research/projection writes, job completion and
attempt completion. Its raw value is `combined_lifecycle_ns`. It contains all
production work on the sample clone after that entry: Clock reads and timestamp
writes, normal lease validation, the complete `lookup_outer_sha_ns` work and
every first outer SHA, outer and inner validation, report-phase finalization
and manifest persistence, the complete stored-finalization work, independent
replay-phase reconstruction, research projection and all terminal writes and
commits. The lookup and stored-finalization measurements are nested
observations; neither control nor treatment combined lifecycle is synthesized
by adding or subtracting sub-timers. All additional Artifact count, schema,
hash, relationship and replay verification required by the treatment's
different v2 source set is v2 incremental overhead and remains inside the
treatment combined lifecycle. It may not be moved into fixture construction or
an untimed prevalidation/cache, disabled, stubbed or bypassed for this
benchmark.

The same machine-readable report prints the committed and observed
`benchmark-environment.v1` values, manifest SHA-256, mismatch list and
`official_environment_match`, plus every per-sample Clock trace/count and its
job/run/attempt/step/lease coordinates. These audit fields are never omitted
from an informational run.

For each mode the machine-readable benchmark report prints, in execution
order, all 30 raw `lookup_outer_sha_ns` values for both sides, all 30 raw
treatment `stored_finalization_ns` values and all 30 raw
`combined_lifecycle_ns` values for both sides. It also prints each ascending
raw vector and its selected rank-29 integer. Only when
`official_environment_match = true` does the report emit and evaluate the
absolute-gate record: it prints the raw treatment
`stored_finalization_p95_ns`, the applicable exact threshold (`20000000`,
`50000000` or `100000000` ns) and the integer comparison result. Under that
same condition, and only then, the ratio record prints the raw
`treatment_combined_p95_ns` numerator, raw `control_combined_p95_ns`
denominator and their exact rational quotient; the 1.15 gate is evaluated
without a rounded decimal as `treatment_combined_p95_ns * 100 <=
control_combined_p95_ns * 115`. When the environment does not match, the
report retains the raw vectors and p95 values but fixes the performance
classification to `informational_environment_mismatch`, records the mismatch
list, and emits neither an absolute-threshold comparison nor a ratio-gate
comparison or pass/fail value. Pair ratios, averaged ratios and rounded
display values are never gate inputs. A mode
contributes only if every warmup and measured clone is file-hash-bound to the
preflighted member and passed the BENCH-02 field-for-field manifest and digest
equalities under BENCH-05. A sample from a padded control or pruned,
precomputed or cached treatment is invalid and may not enter any p95.

**BENCH-08 — fixed gates.** Under BENCH-01 through BENCH-07:

The following 20/50/100 ms absolute thresholds and 1.15 ratio are unchanged,
but they are release gates only when `official_environment_match = true` for
the complete run. A nonmatching environment still executes the identical
protocol and reports all raw values and environment mismatches as
informational results, but performs and emits none of those four gate
comparisons; it therefore neither passes nor fails release and cannot be cited
as satisfying the official performance gate. The embedded record-size and
compatibility gates below remain applicable independently of that
performance-environment classification.

- deterministic treatment stored-finalization p95 is at most **20 ms**;
- hybrid treatment stored-finalization p95 is at most **50 ms**;
- negotiation treatment stored-finalization p95 is at most **100 ms**;
- the matched-semantic-workload legal v2 treatment combined-lifecycle p95 is at
  most **1.15 times** the matched-semantic-workload legal legacy-v1 control
  combined-lifecycle p95, with both sides authenticated by the identical
  committed `semantic_workload_digest`;
- the embedded record is at most **32,768 UTF-8 bytes**; and
- migration files, the committed OpenAPI snapshot and all public response
  models remain unchanged.

## Compatibility and acceptance gates

This slice is accepted only when the following testable outcomes hold. Registry
references mean the token-labelled rows in **Normative proof-schema registry**;
matrix references mean the engine-labelled rows in **Normative six-mode proof
matrix**. The acceptance text does not redefine either contract.

1. **AG-01 — compatibility and routing.** Golden Scenario hashes remain
   byte-for-byte unchanged. Each new v2 lifecycle report for all six engine
   names has exactly one valid execution record and calls the same public
   `finalize_execution()` gate through its matrix row; alias normalization and
   the required v2 report/replay checkpoints are integration-tested. Each mode
   emits only its exact six-row `authority_path`; substituting any other row's
   discriminator fails even after recomputing the record and manifest hashes.
   Legacy synchronous
   deterministic v1 reports remain outside that claim. A Kernel spy observes no
   storage, Provider, network or wall-clock access, and Agent observations never
   become numeric-authority StateDelta sources.
2. **AG-02 — pinned identity and seed.** Creation/recovery tests enforce that
   job creation pins resolver inputs/versions but no baseline-derived output,
   including seed `0`, absence of truthiness fallback and exact runtime-profile
   hash agreement. Request/record/preimage mutation tests independently vary
   `organization_id`, `project_id`, `lifecycle_job_id`, `run_id`, nullable
   `session_id` and current `attempt`, and require the Kernel to reject every
   ownership mismatch. They also recompute the stable epoch from current
   attempt ID/number, worker ID, pinned minimum generation and capability hash,
   require its exact presence in request/record/preimages, and reject an epoch
   mutation even when later hashes are recomputed. Provider-disabled tests rerun and field-compare the
   post-baseline resolvers and verify the mode-governed nullable Agent
   Pack/context/evaluator tuple on every
   mode-applicable registry `FC`, `AC` and `PC`, compare both complete
   Consistency layers field-for-field, and reject stored decision or accepted-ID
   mutation even when payload-local hashes are recomputed.
3. **AG-03 — worker/recovery seam.** Concurrency tests prove GOV-WORKER-1's
   eligible-worker creation gate rejects an empty eligible set, requires every
   eligible worker to advertise v2 and have generation at least the pinned
   `minimum_worker_generation`, and observes at least one fresh active eligible
   worker. Enablement tests prove every old identity/process is retired, its
   supervisor is disabled, its database/queue execution credentials are
   revoked and its replacement uses a distinct identity and credential before
   v2 creation opens. A revived retired identity cannot authenticate a
   heartbeat, cannot become fresh again and cannot claim; unknown identities,
   missing/unknown capability metadata and old generations also fail closed.
   Direct-SQLite tests keep creation permanently disabled unless old and new
   generations use separate OS accounts, old file/directory rights are revoked,
   and full process quiescence, old-supervisor disablement and the exclusive
   deployment lock all hold continuously until every v2-pinned job is terminal.
   Releasing the lock or ACL at enablement rather than terminal drain fails the
   gate. Atomic claim refusal leaves owner, lease and attempt state unchanged.
   Recovery tests prove
   GOV-RECOVERY-1: only key-absent profiles select `report-generate.v1` and
   `replay-archive.v1` without mutation or a version-triggered rerun, exact-v2
   profiles select only both v2 phases, and every other present value fails
   closed without mutation or a mixed-version phase pair.
4. **AG-04 — registry conformance.** Table-driven positive and negative tests
   cover every registry token used by each matrix row: exact artifact/source
   schema, closed claims, hash preimage, coordinate, relationship and null rule.
   Negotiation therefore admits only the registry `RR`, `NP`, `AC`, `CL`, `EL`,
   `PC`, `FC`, `MB`, `ND`, `PA` and `NR` versions; hybrid accepts exactly the
   displayed closed `commitment-ledger.v2` wrapper with canonical request
   `run_id`, null session/tick, empty entries, count zero and its recomputed
   hash. Hybrid CL mutation tests independently change or omit each of those
   values, add a key, substitute a legacy ledger, or attempt to source `run_id`
   from legacy data, and reject the object even after all local hashes are
   recomputed. NR mutation tests independently omit or add every closed
   top-level key, alter each vector's length/order/null slot, change the fixed
   zero Provider count or poison `replay_hash`, and reject the payload before
   replay even when its outer Artifact SHA is recomputed. NP mutation tests
   independently omit each of its nine top-level
   keys, add a key, change every declared type/null rule, desynchronize either
   aligned array, and poison the stored count or digest; strict validation and
   recomputation reject every case. ND mutation tests do the same for all
   eighteen required top-level keys and both closed nested objects, prove fixed
   claim extraction, and require `diffusion_evidence_hash` to change for every
   mutation of any member other than itself, including the complete core/request
   objects and `application_count`. Empty ND tests retain both complete nested
   objects and their hashes while enforcing all empty rules. On persistence,
   recovery and the terminal-completed-job
   duplicate GET, the raw-byte outer-SHA
   comparison must succeed before strict UTF-8 decoding, JSON parsing, schema or
   content-hash validation, claims extraction/validation, or storage/model
   acceptance. The strict parser rejects duplicate keys, coercions,
   non-canonical numbers and malformed Unicode.
5. **AG-05 — matrix cardinality.** Tests for every matrix row reject any
   missing, duplicate, surplus, out-of-order or wrongly conditioned proof.
   Hybrid and `hybrid_recorded` require their complete matrix proof, including
   the empty CL, mandatory PA and provider-free HR; `hybrid_recorded` exercises
   controlled-Agent plus hybrid deterministic projection and is never routed as
   offline input. HR proves the pre-`hybrid_trace` result, traced full-source
   hash, deterministic-source hash and WorldState hash required by GOV-X-4.
   Audit-only, hybrid and negotiation PA mutation tests align only the declared
   pre-projection Consistency fields, reject copying FC/PC projection fields,
   and validate every PA projection status/hash/modifier ID against the truth
   table and the recomputed MB tuple equalities where MB is present. Additional
   non-negotiation mutations independently change PA `before_result_hash` and
   `final_result_hash`: audit-only cases enforce equality to both projections'
   identical source hash, while hybrid cases enforce equality to
   `HR.baseline_result_hash` and the pre-trace `HR.final_result_hash`.
   Hybrid semantic-key mutation cases cover missing and ambiguous PB lookups,
   independently change each PB proposal preimage member and the aligned PA
   semantic hash, and require the PB-derived recomputation/comparison from
   GOV-X-4 to fail after every affected proposal, PB, PA, HR, request and record
   hash is recomputed.
   Recomputing PA, HR, reference, proof, request or record hashes does not make
   any cross-coordinate mutation valid.
6. **AG-06 — negotiation governance.** Property and mutation tests enforce
   GOV-CL-1, GOV-EL-1 and GOV-X-5 through GOV-X-11, including unique UTF-8-sorted
   `target_ids` before AC, exact CL ID/hash/event/expiry order, four-way active
   origins, strict EL discriminator/null combinations, `prior_projected` iff
   prior PA membership, and the UTF-8-minimum same-tick semantic winner selected
   only among preliminary eligible candidates. There is a complete EL decision
   for every NP tuple with every preliminary same-tick loser classified
   `semantic_duplicate`, the prior-PA-only seen-set construction is unchanged,
   and decision/eligibility hashes are recomputed from the final outcomes.
   Permutation and ID mutation cases prove that input order cannot change the
   winner, NP remains only the complete proposal-ID-sorted candidate vector,
   loser decisions remain in the complete EL vector, and a lower-ID
   proposal that is not admitted or is classified by an earlier nonfatal
   eligibility condition cannot suppress a higher-ID candidate. Invalid-origin
   cases fail before grouping. Same-tick grouping cannot mark an ID or semantic
   key seen.
   RR/message mutations independently change a message wrapper's session,
   round or tick, the six-tick derived/unique round IDs, a global `seq`, a
   cross-tick `previous_hash`, a derived `message_id`, a message digest input or
   its aligned per-tick tuple. Gaps, duplicates, local per-tick renumbering and
   incomplete or surplus wrapper keys fail even after every RR, NR, Artifact
   and enclosing proof hash is recomputed.
   Coordinate mutations independently change a PB/NP proposal `run_id`, a
   current-message `turn`, an active origin's source-admission `turn`, or the
   separate current NP tick; each fails before AC or later consumption even
   after proposal, batch, audit, content and claims hashes are recomputed.
   Expiry/MB/ND poison cases prove that their current run/tick comes only from
   the authenticated request and RR/NP/PC proof coordinates, never from either
   Provider proposal turn. The tests also enforce every AC/NP and EL/PC
   equality; PA equality only for the PC pre-projection proposal,
   decision/rule/outcome/rejection fields; and the post-Consistency PA truth
   table plus recomputed MB projection-hash/modifier-ID equalities. They enforce
   every ND/state and RR/NR equality and reject any locally rehashed drift;
   FC/PC projection-status/hash mutation can never be made authoritative by
   copying it into PA. Bilateral mutation cases independently
   change origin visibility, origin recipient cardinality, proposal actor,
   Agent Pack target resolution, either party, action type, response sender,
   response visibility or response recipients; they include multi-recipient
   origins and third-party or multi-recipient `accept` responses, and must fail
   even after all payload-local commitment, ledger, message, proposal,
   admission, content and claims hashes are recomputed.
7. **AG-07 — tick closure and numeric authority.** The negotiation matrix row,
   GOV-X-11 and the four numbered **Per-tick proof cardinality** rules are tested
   for no-projection, eligible, narrative-only, empty and numeric-no-op ticks.
   Each tick has exactly one CL and ND; the empty ND comes from the production
   adapter. Required PA/PC/MB presence, canonical `no_projection`, internal
   negotiation projection mode and `negotiation_projection_audit` type are
   asserted. Fixed-point tests cover every conversion, product and cumulative
   update in signed int64 at scale 10,000 with half-even rounding.
8. **AG-08 — retry lineage.** Retry tests cover all six engine modes and enforce
   GOV-RETRY-1's exact matrix-token source sets, current-attempt re-emission of
   every required proof source, and regenerated current-attempt resolver
   Artifacts for every Agent-capable mode. Negotiation additionally proves the
   continuous prefix, provider-free prefix re-execution and exact conditional
   allow-set including `NP` and `EL`. Scope-substitution cases independently
   vary organization, project, job, run, session, schema, role and tick. Tests
   select the unique maximum lower `attempt_number` only from terminal
   `failed`/`abandoned` attempts of the same job, prove row/relationship target
   equality and opaque `target_attempt`, and reject every historical Artifact
   as an ordinary target, resolver input or proof reference. Fresh terminal
   `FC`/`NR` rows and relationships remain explicitly null/no-supersedes.
   Cancellation tests prove that a cancelled job/run is permanently terminal,
   supplies no retry source and can be recovered only by explicit creation of a
   new job/run whose Provider may be called again and whose proof cannot
   re-emit any cancelled Artifact.
9. **AG-09 — stored replay.** Provider-disabled hybrid and negotiation replay
   reproduce the exact final result and WorldState admitted by the record.
   Negotiation rebuilds MB and PA from authenticated NP, recomputed PC, pinned
   seed and RR-before state, reruns the engine and then ND, and derives
   cumulative deltas only from prior verified re-executions; stored decisions,
   applications and applied deltas never supply numeric authority.
10. **AG-10 — persistence/recovery boundary.** Nested proof tampering fails
    even after recomputing an outer Artifact SHA. Replacing one source
    Artifact's bytes and row SHA fails its discriminator-specific producing-step
    tuple and checkpoint roots; resolver/proof discriminator or schema mixing
    fails independently. For each non-null `lifecycle_job_id`, tests prove
    reconstruction from the exact
    `(organization_id, project_id, lifecycle_job_id, run_id, nullable
    session_id, current attempt)` ownership tuple, an authoritative Kernel
    comparison of that identity, an optional comparison-only caller record and
    runtime-profile agreement.
    `report_generate.v2` atomically writes the manifest, exact step output/ref
    bindings and report-step completion, rolling back all three on any failure;
    same-attempt recovery accepts only the one exact reconstructed manifest and
    rejects duplicates or partial bindings. When A completed report generation
    and then replay failed, B resets to `report_generate.v2`, rebuilds B's
    current-attempt record and manifest without an A/B field-equality
    requirement, and never resumes from A's manifest.
    `replay_archive.v2` synchronously rebuilds and revalidates v2, and its one
    Run Control Unit of Work atomically owns research/projection writes,
    replay-step completion, lifecycle metrics, job completion and attempt
    completion. SQLite and PostgreSQL concurrency tests exercise
    GOV-FINALIZE-FENCE-1 for both phases: after A captures its stable fencing
    epoch and begins
    a long reconstruction, A's lease expires, B creates a new current attempt,
    and A's final CAS fails with zero writes, including when B uses the same
    worker identity. A separate same-attempt/same-worker heartbeat extends the
    lease without changing the epoch; finalization remains legal only when the
    final CAS rechecks current attempt, equal attempt/job owner, both running
    states, fresh lease, non-retirement, generation, capability hash and the
    request/record epoch. Any existing projection
    observed while the current attempt is
    active/running fails as corruption, even on an exact content match. Only a
    duplicate GET of an already completed job/attempt may rebuild and validate
    the immutable result and return; it is read-only and opens no active Unit of
    Work. `persist_war_room_result()` owns no lifecycle transition. Failure
    writes nothing terminal and does not rewrite or delete immutable history.
    Null-ID boundary tests enforce the separate legacy tuple rule and accept
    only the trusted internal deterministic port with complete recomputed
    `LegacyDeterministicProvenance`; they reject Agent, hybrid, negotiation,
    controller, Provider, user and other repository callers.
11. **AG-11 — security boundary.** Tests cover untrusted user/Provider payloads,
    corrupt/partial rows, cross-run/cross-organization substitution and a
    single-Artifact byte replacement accompanied by an updated row SHA while
    the producing-step/checkpoint roots remain unchanged. Documentation and
    assertions remain limited by the stated threat model and do not claim
    protection against arbitrary in-process execution or a coordinated rewrite
    of the database plus every producing-step, checkpoint and later hash root.
12. **AG-12 — performance and release.** BENCH-01 through BENCH-08 run without
    reinterpretation. The unchanged 20/50/100 ms and 1.15 comparisons are
    release gates only for a live probe that exactly matches the committed
    closed `benchmark-environment.v1`; a mismatch is explicitly informational
    and emits no absolute or ratio gate verdict. Fixture-generation tests prove
    WAL truncation, transition to DELETE journaling, clean close, absence of
    every source/destination sidecar before and after cloning, and binding of
    all SQLite-visible fixture state by the sealed main-file SHA. The live
    environment comparison covers every top-level and nested field of the sole
    Windows x86-64 manifest, including exact power, storage, NTFS, PRAGMA,
    page-cache, process priority/affinity and background-noise values, plus all
    five explicit Linux nulls. Schema mutations independently exercise every
    missing, surplus, wrong-type and wrong-null field. The fixture's production
    pair manifest is independently validated as the exact closed
    `benchmark-fixture-manifest.v1`: its committed outer SHA-256 and
    `fixture_manifest_hash` must both match, each control/treatment inventory
    and production-Clock field is type-checked, and mutations cover every
    missing, surplus, reordered allowlist, wrong-type and stale-digest case.
    The fixture's production
    Clock injection proves
    both committed leases fresh and every compared lifecycle event, Artifact,
    step, job and attempt timestamp is produced under the identical fixed
    logical-time schedule without changing lease bytes or bypassing claim. The
    static architecture test rejects direct wall-time APIs everywhere in the
    benchmark and run-lifecycle critical-module sets, SQL schema defaults and
    triggers, and transitive native dependencies except the production Clock
    adapter. Benchmark-critical tables reject SQL-native current-date/time
    expressions. Machine-report assertions cross-check the effective SQL
    schema/write audit and native dependency inventory with the complete
    Clock-call trace/count/coordinates, including read-only lease checks.
    The one production Clock-to-OS native wall-time chain is ordered and
    hash-pinned; every other native time source is forbidden except the
    separate monotonic-duration source. Production outside the benchmark still
    uses wall time only through that unique chain and the pure Kernel remains
    clock-free. Fixture shape assertions require hybrid's four-plus proposals
    with numeric/no-effect acceptance and rejection, plus negotiation's three
    `p=1` ticks, one `p=0` tick, CL activation, PC rejection, deterministic
    modifier, nonempty ND and numeric-no-op PA.

## Rollback

1. Disable new `kernel-mode-execution.v2` job pinning while v2-capable workers
   remain deployed.
2. Drain active and queued v2-pinned jobs to completion on those workers, or
   explicitly cancel the remainder. Confirm that every v2-pinned job is
   terminal; an old worker is never allowed to consume one. A direct-SQLite
   deployment retains its exclusive v2 lock and generation-separated ACL until
   this assertion succeeds.
3. Revert the worker, report-step and adapter commits. Permanently retired
   identities and revoked credentials remain retired/revoked; if an older
   compatible worker binary is redeployed, it receives a new authorized
   identity, current generation and distinct credentials. No schema downgrade
   is required.
4. Historical `report-projection-manifest.v2` payloads remain valid generic
   Artifacts; older code ignores additive fields.
5. Key-absent legacy-v1 jobs continue through the v1 compatibility path. A
   non-terminal v2-pinned job is not reinterpreted as v1 and may resume only
   after v2-capable workers are restored. A cancelled v2 job never resumes or
   retries under the same job/run; renewed intent explicitly creates a new
   job/run, may call its Provider again, and cannot re-emit cancelled Artifacts.
   A present unknown marker also remains fail-closed.
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
