"""Pure, immutable proof contracts for ADR-0007 Kernel mode finalization.

This module deliberately contains data validation only.  Storage authentication,
proof extraction, replay, and the mode-cardinality finalization algorithm belong
to later slices outside the Simulation Kernel's pure boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import ConfigDict, Field, field_validator, model_validator

from app.services.consistency.hashing import stable_hash

from .contracts import AUTHORITY_PATH_BY_KERNEL_MODE, KernelContract
from .war_room_projection import WarRoomProjection


SHA256_PATTERN = r"^[0-9a-f]{64}$"
Digest: TypeAlias = Annotated[str, Field(pattern=SHA256_PATTERN)]
EngineMode: TypeAlias = Literal[
    "deterministic", "mock_agent", "controlled_agent", "hybrid", "hybrid_recorded", "negotiation"
]
KernelMode: TypeAlias = Literal["deterministic", "hybrid", "negotiation"]
ProofToken: TypeAlias = Literal["AR", "PB", "FC", "RR", "AC", "PC", "MB", "ND", "CL", "PA", "HR", "NR"]
ProofSchema: TypeAlias = Literal[
    "kp.agent-runtime.v1",
    "kp.proposal-batch.v1",
    "kp.final-consistency.v1",
    "kp.negotiation-round.v1",
    "kp.negotiation-admission-consistency.v1",
    "kp.negotiation-projection-consistency.v1",
    "kp.action-modifier-bundle.v1",
    "kp.narrative-diffusion.v1",
    "kp.commitment-ledger.v1",
    "kp.projection-audit.v1",
    "kp.hybrid-replay.v1",
    "kp.negotiation-replay.v1",
]
RelationshipType: TypeAlias = Literal[
    "generated_by",
    "evaluates",
    "covers",
    "governed_by",
    "maps",
    "admitted_by",
    "ledger_for",
    "audits",
    "ledger_snapshot",
    "observations",
    "replays",
    "audit",
    "previous_round",
    "filters",
    "bounded_by",
    "no_projection_for",
    "snapshot_for",
    "round",
    "diffusion",
    "final_audit",
    "projection",
    "modifiers",
    "ledgers",
    "admission",
    "supersedes",
]

KERNEL_MODE_BY_ENGINE_MODE: Mapping[EngineMode, KernelMode] = MappingProxyType(
    {
        "deterministic": "deterministic",
        "mock_agent": "deterministic",
        "controlled_agent": "deterministic",
        "hybrid": "hybrid",
        "hybrid_recorded": "hybrid",
        "negotiation": "negotiation",
    }
)


def normalize_kernel_mode(engine_mode: EngineMode | str) -> KernelMode:
    """Map an exact ADR engine mode to its numeric-state Kernel mode."""

    try:
        return KERNEL_MODE_BY_ENGINE_MODE[engine_mode]  # type: ignore[index]
    except KeyError as exc:
        raise ValueError(f"Unknown Kernel engine mode: {engine_mode!r}") from exc


def _validate_ascending_unique(values: tuple[str, ...], field_name: str) -> None:
    if len(set(values)) != len(values):
        raise ValueError(f"{field_name} must be unique")
    if tuple(sorted(values, key=lambda value: value.encode("utf-8"))) != values:
        raise ValueError(f"{field_name} must be ascending UTF-8 byte order")


class KernelModeContract(KernelContract):
    """Closed proof-boundary models with no coercion at the Kernel edge."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def accept_canonical_json_tuples(cls, value: object) -> object:
        """Restore JSON arrays for tuple fields before strict scalar validation."""

        def restore(value: object) -> object:
            if isinstance(value, list):
                return tuple(restore(item) for item in value)
            if isinstance(value, dict):
                return {key: restore(item) for key, item in value.items()}
            return value

        return restore(value)


class KernelModeClaims(KernelModeContract):
    """Base class for the closed, schema-selected claim records."""

    run_id: str = Field(min_length=1, max_length=160)


class ARClaims(KernelModeClaims):
    runtime_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    proposal_count: int = Field(ge=0)
    invocation_ids: tuple[str, ...] = ()
    invocation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.invocation_ids, "invocation_ids")
        if self.proposal_count != len(self.proposal_ids) or self.invocation_count != len(self.invocation_ids):
            raise ValueError("AR claim counts must equal tuple lengths")
        return self


class PBClaims(KernelModeClaims):
    source_kind: Literal["mock_agent", "controlled_agent"]
    batch_hash: Digest | None = None
    runtime_hash: Digest | None = None
    proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    proposal_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_batch_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        if (self.batch_hash is None) == (self.runtime_hash is None):
            raise ValueError("PB claims require exactly one of batch_hash or runtime_hash")
        if self.proposal_count != len(self.proposal_ids) or len(self.proposal_ids) != len(self.proposal_hashes):
            raise ValueError("PB proposal count and hashes must match proposal_ids")
        return self


class FCClaims(KernelModeClaims):
    role: Literal["final"] = "final"
    audit_hash: Digest
    deterministic_result_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_consistency_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if self.decision_count != len(self.proposal_ids):
            raise ValueError("FC decision_count must equal proposal_ids length")
        if not set(self.accepted_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("FC accepted_proposal_ids must be proposals")
        return self


class RRClaims(KernelModeClaims):
    session_id: str = Field(min_length=1, max_length=160)
    round_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    input_hash: Digest
    output_hash: Digest
    before_result_hash: Digest
    after_result_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    admission_audit_hash: Digest
    projection_consistency_hash: Digest | None = None
    modifier_bundle_hash: Digest | None = None
    diffusion_hash: Digest
    ledger_hash: Digest
    projection_audit_hash: Digest | None = None
    no_projection_reason: Literal["no_projection"] | None = None

    @model_validator(mode="after")
    def validate_round_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if not set(self.accepted_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("RR accepted_proposal_ids must be proposals")
        return self


class ACClaims(KernelModeClaims):
    role: Literal["admission"] = "admission"
    tick: int = Field(ge=1, le=6)
    audit_hash: Digest
    deterministic_result_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_admission_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if self.decision_count != len(self.proposal_ids):
            raise ValueError("AC decision_count must equal proposal_ids length")
        if not set(self.accepted_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("AC accepted_proposal_ids must be proposals")
        return self


class PCClaims(KernelModeClaims):
    role: Literal["projection"] = "projection"
    tick: int = Field(ge=1, le=6)
    audit_hash: Digest
    deterministic_result_hash: Digest
    candidate_proposal_ids: tuple[str, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_projection_claims(self) -> Self:
        _validate_ascending_unique(self.candidate_proposal_ids, "candidate_proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if self.decision_count != len(self.candidate_proposal_ids):
            raise ValueError("PC decision_count must equal candidate_proposal_ids length")
        if not set(self.accepted_proposal_ids).issubset(self.candidate_proposal_ids):
            raise ValueError("PC accepted_proposal_ids must be candidates")
        return self


class ModifierReference(KernelModeContract):
    proposal_id: str = Field(min_length=1, max_length=160)
    modifier_id: str = Field(min_length=1, max_length=160)
    modifier_hash: Digest


def _modifier_sort_key(item: ModifierReference) -> tuple[bytes, bytes, bytes]:
    return (
        item.proposal_id.encode("utf-8"),
        item.modifier_id.encode("utf-8"),
        item.modifier_hash.encode("utf-8"),
    )


def _validate_modifier_tuples(
    values: tuple[ModifierReference, ...],
    field_name: str,
) -> None:
    keys = tuple(_modifier_sort_key(item) for item in values)
    if len(set(keys)) != len(keys):
        raise ValueError(f"{field_name} must be unique")
    if tuple(sorted(values, key=_modifier_sort_key)) != values:
        raise ValueError(f"{field_name} must be ascending UTF-8 byte order")


class MBClaims(KernelModeClaims):
    tick: int | None = Field(default=None, ge=1, le=6)
    bundle_hash: Digest
    consistency_audit_hash: Digest
    accepted_proposal_ids: tuple[str, ...] = ()
    modifier_tuples: tuple[ModifierReference, ...] = ()
    modifier_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_modifier_claims(self) -> Self:
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if self.modifier_count != len(self.modifier_tuples):
            raise ValueError("MB modifier_count must equal modifier_tuples length")
        _validate_modifier_tuples(self.modifier_tuples, "MB modifier_tuples")
        if any(item.proposal_id not in self.accepted_proposal_ids for item in self.modifier_tuples):
            raise ValueError("MB modifier_tuples must belong to accepted proposals")
        return self


class NDClaims(KernelModeClaims):
    tick: int = Field(ge=1, le=6)
    attempted: bool
    diffusion_hash: Digest
    application_count: int = Field(ge=0)
    proposal_ids: tuple[str, ...] = ()
    before_result_hash: Digest
    after_result_hash: Digest

    @model_validator(mode="after")
    def validate_diffusion_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        if self.application_count != len(self.proposal_ids):
            raise ValueError("ND application_count must equal proposal_ids length")
        if not self.attempted and (
            self.application_count != 0
            or self.proposal_ids
            or self.before_result_hash != self.after_result_hash
        ):
            raise ValueError("unattempted ND claims must be an empty numeric no-op")
        return self


class CommitmentReference(KernelModeContract):
    commitment_id: str = Field(min_length=1, max_length=160)
    commitment_hash: Digest
    status: str = Field(min_length=1, max_length=80)


class CLClaims(KernelModeClaims):
    tick: int | None = Field(default=None, ge=1, le=6)
    ledger_hash: Digest
    ledger_entry_count: int = Field(ge=0)
    commitments: tuple[CommitmentReference, ...] = ()

    @model_validator(mode="after")
    def validate_ledger_claims(self) -> Self:
        if self.ledger_entry_count != len(self.commitments):
            raise ValueError("CL ledger_entry_count must equal commitments length")
        if tuple(sorted(self.commitments, key=lambda item: (item.commitment_id, item.commitment_hash, item.status))) != self.commitments:
            raise ValueError("CL commitments must be in canonical order")
        if len({item.commitment_id for item in self.commitments}) != len(self.commitments):
            raise ValueError("CL commitment ids must be unique")
        return self


class PAClaims(KernelModeClaims):
    tick: int | None = Field(default=None, ge=1, le=6)
    projection_mode: Literal["audit_only", "hybrid", "negotiation"]
    audit_hash: Digest
    consistency_audit_hash: Digest
    modifier_bundle_hash: Digest | None = None
    proposal_ids: tuple[str, ...] = ()
    projected_proposal_ids: tuple[str, ...] = ()
    modifier_tuples: tuple[ModifierReference, ...] = ()
    modifier_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    before_result_hash: Digest
    final_result_hash: Digest

    @model_validator(mode="after")
    def validate_audit_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.projected_proposal_ids, "projected_proposal_ids")
        if self.record_count != len(self.proposal_ids):
            raise ValueError("PA record_count must equal proposal_ids length")
        if self.modifier_count != len(self.modifier_tuples):
            raise ValueError("PA modifier_count must equal modifier_tuples length")
        _validate_modifier_tuples(self.modifier_tuples, "PA modifier_tuples")
        if not set(self.projected_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("PA projected_proposal_ids must be proposals")
        if any(item.proposal_id not in self.projected_proposal_ids for item in self.modifier_tuples):
            raise ValueError("PA modifier_tuples must belong to projected proposals")
        if self.projection_mode == "audit_only" and self.modifier_tuples:
            raise ValueError("audit_only PA modifier_tuples must be empty")
        return self


class HRClaims(KernelModeClaims):
    engine_mode: Literal["hybrid", "hybrid_recorded"]
    replay_source_kind: Literal["stored_only"]
    provider_calls_required: Literal[0]
    replay_hash: Digest
    baseline_result_hash: Digest
    final_result_hash: Digest
    full_source_run_hash: Digest
    consistency_audit_hash: Digest
    modifier_bundle_hash: Digest
    projection_audit_hash: Digest
    ledger_hash: Digest
    accepted_proposal_ids: tuple[str, ...] = ()

    @field_validator("provider_calls_required", mode="before")
    @classmethod
    def require_exact_zero_provider_calls(cls, value: object) -> object:
        if type(value) is not int or value != 0:
            raise ValueError("provider_calls_required must be the integer 0")
        return value

    @model_validator(mode="after")
    def validate_replay_claims(self) -> Self:
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        return self


class NRClaims(KernelModeClaims):
    session_id: str = Field(min_length=1, max_length=160)
    replay_hash: Digest
    baseline_result_hash: Digest
    final_result_hash: Digest
    round_hashes: tuple[Digest, ...]
    admission_audit_hashes: tuple[Digest, ...]
    projection_consistency_hashes: tuple[Digest | None, ...]
    diffusion_hashes: tuple[Digest, ...]
    ledger_hashes: tuple[Digest, ...]
    projection_audit_hashes: tuple[Digest | None, ...]
    message_chain_head: Digest
    provider_calls_required: Literal[0] = 0

    @field_validator("provider_calls_required", mode="before")
    @classmethod
    def require_exact_zero_provider_calls(cls, value: object) -> object:
        if type(value) is not int or value != 0:
            raise ValueError("provider_calls_required must be the integer 0")
        return value

    @model_validator(mode="after")
    def validate_negotiation_replay_claims(self) -> Self:
        sequences = (
            self.round_hashes,
            self.admission_audit_hashes,
            self.projection_consistency_hashes,
            self.diffusion_hashes,
            self.ledger_hashes,
            self.projection_audit_hashes,
        )
        if any(len(sequence) != 6 for sequence in sequences):
            raise ValueError("NR tick-ordered hash tuples must contain six entries")
        return self


ModeClaims: TypeAlias = (
    ARClaims | PBClaims | FCClaims | RRClaims | ACClaims | PCClaims | MBClaims | NDClaims | CLClaims | PAClaims | HRClaims | NRClaims
)
_CLAIMS_BY_SCHEMA: Mapping[ProofSchema, type[KernelModeClaims]] = MappingProxyType({
    "kp.agent-runtime.v1": ARClaims,
    "kp.proposal-batch.v1": PBClaims,
    "kp.final-consistency.v1": FCClaims,
    "kp.negotiation-round.v1": RRClaims,
    "kp.negotiation-admission-consistency.v1": ACClaims,
    "kp.negotiation-projection-consistency.v1": PCClaims,
    "kp.action-modifier-bundle.v1": MBClaims,
    "kp.narrative-diffusion.v1": NDClaims,
    "kp.commitment-ledger.v1": CLClaims,
    "kp.projection-audit.v1": PAClaims,
    "kp.hybrid-replay.v1": HRClaims,
    "kp.negotiation-replay.v1": NRClaims,
})
_TOKEN_BY_SCHEMA: Mapping[ProofSchema, ProofToken] = MappingProxyType({
    "kp.agent-runtime.v1": "AR",
    "kp.proposal-batch.v1": "PB",
    "kp.final-consistency.v1": "FC",
    "kp.negotiation-round.v1": "RR",
    "kp.negotiation-admission-consistency.v1": "AC",
    "kp.negotiation-projection-consistency.v1": "PC",
    "kp.action-modifier-bundle.v1": "MB",
    "kp.narrative-diffusion.v1": "ND",
    "kp.commitment-ledger.v1": "CL",
    "kp.projection-audit.v1": "PA",
    "kp.hybrid-replay.v1": "HR",
    "kp.negotiation-replay.v1": "NR",
})
_ARTIFACT_TYPES_BY_SCHEMA: Mapping[ProofSchema, frozenset[str]] = MappingProxyType({
    "kp.agent-runtime.v1": frozenset({"agent_runtime_audit"}),
    "kp.proposal-batch.v1": frozenset({"agent_action_proposals"}),
    "kp.final-consistency.v1": frozenset({"consistency_audit"}),
    "kp.negotiation-round.v1": frozenset({"negotiation_round"}),
    "kp.negotiation-admission-consistency.v1": frozenset({"consistency_audit"}),
    "kp.negotiation-projection-consistency.v1": frozenset({"consistency_audit"}),
    "kp.action-modifier-bundle.v1": frozenset({"deterministic_action_modifiers"}),
    "kp.narrative-diffusion.v1": frozenset({"narrative_diffusion"}),
    "kp.commitment-ledger.v1": frozenset({"commitment_ledger"}),
    "kp.projection-audit.v1": frozenset({"agent_action_projection_audit", "negotiation_projection_audit"}),
    "kp.hybrid-replay.v1": frozenset({"hybrid_replay_record"}),
    "kp.negotiation-replay.v1": frozenset({"negotiation_replay"}),
})
_SOURCE_SCHEMAS_BY_SCHEMA: Mapping[ProofSchema, frozenset[str]] = MappingProxyType({
    "kp.agent-runtime.v1": frozenset({"agent-runtime-result.v1"}),
    "kp.proposal-batch.v1": frozenset({"mock-agent-batch.v1", "agent-action-batch.v1"}),
    "kp.final-consistency.v1": frozenset({"consistency-audit.v1", "consistency-audit.v2"}),
    "kp.negotiation-round.v1": frozenset({"negotiation-round.v1"}),
    "kp.negotiation-admission-consistency.v1": frozenset(
        {"consistency-audit.v1", "consistency-audit.v2"}
    ),
    "kp.negotiation-projection-consistency.v1": frozenset({"consistency-audit.v2"}),
    "kp.action-modifier-bundle.v1": frozenset({"hybrid-modifier-bundle.v1"}),
    "kp.narrative-diffusion.v1": frozenset({"narrative-diffusion.v1"}),
    "kp.commitment-ledger.v1": frozenset({"commitment-ledger.v1"}),
    "kp.projection-audit.v1": frozenset({"agent-action-projection-audit.v1"}),
    "kp.hybrid-replay.v1": frozenset({"hybrid-replay-record.v1"}),
    "kp.negotiation-replay.v1": frozenset({"negotiation-replay.v1"}),
})


class KernelModeProofRelationship(KernelModeContract):
    relationship_type: RelationshipType
    target_artifact_id: str = Field(min_length=1, max_length=160)
    target_content_hash: Digest
    target_attempt: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_retry_attempt(self) -> Self:
        if self.relationship_type == "supersedes":
            if self.target_attempt is None:
                raise ValueError("supersedes relationship requires target_attempt")
        elif self.target_attempt is not None:
            raise ValueError("target_attempt is only allowed for supersedes")
        return self


class KernelModeProofReference(KernelModeContract):
    proof_schema: ProofSchema
    artifact_type: str = Field(min_length=1, max_length=120)
    schema_version: str = Field(min_length=1, max_length=120)
    artifact_id: str = Field(min_length=1, max_length=160)
    run_id: str = Field(min_length=1, max_length=160)
    attempt: str = Field(min_length=1, max_length=160)
    ordinal: int | None = Field(default=None, ge=0)
    tick: int | None = Field(default=None, ge=1, le=6)
    artifact_sha256: Digest
    content_hash: Digest
    claims: ModeClaims
    claims_hash: Digest
    relationships: tuple[KernelModeProofRelationship, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def parse_schema_claims(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        proof_schema = value.get("proof_schema")
        claims_model = _CLAIMS_BY_SCHEMA.get(proof_schema)  # type: ignore[arg-type]
        if claims_model is not None and isinstance(value.get("claims"), dict):
            value = dict(value)
            value["claims"] = claims_model.model_validate(value["claims"])
        return value

    @model_validator(mode="after")
    def validate_reference(self) -> Self:
        expected_claims = _CLAIMS_BY_SCHEMA[self.proof_schema]
        if type(self.claims) is not expected_claims:
            raise ValueError(f"claims do not match proof_schema {self.proof_schema}")
        if self.artifact_type not in _ARTIFACT_TYPES_BY_SCHEMA[self.proof_schema]:
            raise ValueError("artifact_type is not allowed by proof_schema")
        if self.schema_version not in _SOURCE_SCHEMAS_BY_SCHEMA[self.proof_schema]:
            raise ValueError("schema_version is not allowed by proof_schema")
        if self.claims.run_id != self.run_id:
            raise ValueError("claims run_id must match proof reference")
        expected_hash = stable_hash(
            {"claims": self.claims.model_dump(mode="json"), "proof_schema": self.proof_schema}
        )
        if self.claims_hash != expected_hash:
            raise ValueError("Kernel mode proof claims_hash mismatch")
        if any(item.relationship_type == "supersedes" for item in self.relationships[:-1]):
            raise ValueError("supersedes relationship must be last")
        return self

    @property
    def token(self) -> ProofToken:
        return _TOKEN_BY_SCHEMA[self.proof_schema]


class KernelModeExecutionProof(KernelModeContract):
    schema_version: Literal["kernel-mode-execution-proof.v1"] = "kernel-mode-execution-proof.v1"
    references: tuple[KernelModeProofReference, ...]
    proof_hash: Digest

    @model_validator(mode="after")
    def validate_proof_hash(self) -> Self:
        expected_hash = stable_hash(
            {"references": [item.model_dump(mode="json") for item in self.references], "schema_version": self.schema_version}
        )
        if self.proof_hash != expected_hash:
            raise ValueError("Kernel mode execution proof_hash mismatch")
        return self


class KernelModeExecutionRequest(KernelModeContract):
    schema_version: Literal["kernel-mode-execution-request.v1"] = "kernel-mode-execution-request.v1"
    execution_contract_version: Literal["kernel-mode-execution.v2"] = "kernel-mode-execution.v2"
    engine_mode: EngineMode
    kernel_mode: KernelMode
    run_id: str = Field(min_length=1, max_length=160)
    attempt: str = Field(min_length=1, max_length=160)
    effective_seed: int
    rule_pack_hash: Digest
    baseline: WarRoomProjection
    final: WarRoomProjection
    proof: KernelModeExecutionProof
    retry_origin_attempt_ids: tuple[str, ...] = ()
    retry_completed_ticks: tuple[int, ...] = ()

    @model_validator(mode="after")
    def validate_request_identity(self) -> Self:
        if self.kernel_mode != normalize_kernel_mode(self.engine_mode):
            raise ValueError("kernel_mode does not match engine_mode")
        for projection in (self.baseline, self.final):
            state = projection.world_state
            if state.run_id != self.run_id:
                raise ValueError("projection run_id must match request")
            if state.seed != self.effective_seed:
                raise ValueError("projection seed must match effective_seed")
            if state.rule_pack_hash != self.rule_pack_hash:
                raise ValueError("projection Rule Pack hash must match request")
        _validate_ascending_unique(self.retry_origin_attempt_ids, "retry_origin_attempt_ids")
        if tuple(sorted(set(self.retry_completed_ticks))) != self.retry_completed_ticks:
            raise ValueError("retry_completed_ticks must be unique and ascending")
        if self.retry_completed_ticks and (
            self.retry_completed_ticks[0] < 1 or self.retry_completed_ticks[-1] > 6
        ):
            raise ValueError("retry_completed_ticks must be in 1..6")
        if self.retry_completed_ticks != tuple(range(1, len(self.retry_completed_ticks) + 1)):
            raise ValueError("retry_completed_ticks must be a contiguous prefix beginning at 1")
        if bool(self.retry_origin_attempt_ids) != bool(self.retry_completed_ticks):
            raise ValueError("retry origins and completed ticks must be supplied together")
        if self.engine_mode != "negotiation" and (self.retry_origin_attempt_ids or self.retry_completed_ticks):
            raise ValueError("retry context is only allowed for negotiation")
        if self.attempt in self.retry_origin_attempt_ids:
            raise ValueError("retry origin attempts must differ from the current attempt")
        return self


class KernelModeExecutionRecord(KernelModeContract):
    schema_version: Literal["kernel-mode-execution-record.v1"] = "kernel-mode-execution-record.v1"
    execution_contract_version: Literal["kernel-mode-execution.v2"] = "kernel-mode-execution.v2"
    engine_mode: EngineMode
    kernel_mode: KernelMode
    run_id: str = Field(min_length=1, max_length=160)
    attempt: str = Field(min_length=1, max_length=160)
    effective_seed: int
    rule_pack_hash: Digest
    authority_path: tuple[str, ...]
    baseline_source_run_hash: Digest
    baseline_deterministic_source_hash: Digest
    baseline_world_state_hash: Digest
    final_source_run_hash: Digest
    final_deterministic_source_hash: Digest
    final_world_state_hash: Digest
    proof_hash: Digest
    record_hash: Digest

    @model_validator(mode="after")
    def validate_record_hash(self) -> Self:
        if self.kernel_mode != normalize_kernel_mode(self.engine_mode):
            raise ValueError("kernel_mode does not match engine_mode")
        if self.authority_path != AUTHORITY_PATH_BY_KERNEL_MODE[self.kernel_mode]:
            raise ValueError("authority_path must match the fixed Kernel mode authority path")
        expected_hash = stable_hash(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != expected_hash:
            raise ValueError("Kernel mode execution record_hash mismatch")
        return self


# Descriptive aliases keep callers from coupling to the short ADR table tokens.
AgentRuntimeClaims = ARClaims
ProposalBatchClaims = PBClaims
FinalConsistencyClaims = FCClaims
NegotiationRoundClaims = RRClaims
NegotiationAdmissionConsistencyClaims = ACClaims
NegotiationProjectionConsistencyClaims = PCClaims
ActionModifierBundleClaims = MBClaims
NarrativeDiffusionClaims = NDClaims
CommitmentLedgerClaims = CLClaims
ProjectionAuditClaims = PAClaims
HybridReplayClaims = HRClaims
NegotiationReplayClaims = NRClaims
