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

from .contracts import KernelContract
from .war_room_projection import WarRoomProjection


SHA256_PATTERN = r"^[0-9a-f]{64}$"
Digest: TypeAlias = Annotated[str, Field(pattern=SHA256_PATTERN)]
EngineMode: TypeAlias = Literal[
    "deterministic", "mock_agent", "controlled_agent", "hybrid", "hybrid_recorded", "negotiation"
]
KernelMode: TypeAlias = Literal["deterministic", "hybrid", "negotiation"]
ProofToken: TypeAlias = Literal[
    "AR", "PB", "FC", "RR", "NP", "AC", "CL", "EL", "PC", "MB", "ND", "PA", "HR", "NR"
]
ProofSchema: TypeAlias = Literal[
    "kp.agent-runtime.v1",
    "kp.proposal-batch.v1",
    "kp.final-consistency.v1",
    "kp.negotiation-round.v1",
    "kp.negotiation-proposal-batch.v1",
    "kp.negotiation-admission-consistency.v1",
    "kp.negotiation-eligibility.v1",
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
    "source_for",
    "filters",
    "snapshot_after",
    "sources",
    "current_ledger",
    "prior_projection",
    "origin_admission",
    "inputs",
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
    "proposal_sources",
    "eligibility",
    "supersedes",
]

AUTHORITY_PATH_BY_ENGINE_MODE: Mapping[EngineMode, str] = MappingProxyType(
    {
        "deterministic": "deterministic_audit_only",
        "mock_agent": "mock_action_adapter_deterministic",
        "controlled_agent": "controlled_action_adapter_deterministic",
        "hybrid": "hybrid_action_adapter_replay",
        "hybrid_recorded": "hybrid_recorded_action_adapter_replay",
        "negotiation": "negotiation_governed_deterministic",
    }
)

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


ActionClass: TypeAlias = Literal[
    "deterministic_modifier",
    "bilateral_commitment",
    "public_narrative",
    "audit_only",
    "alliance_response",
]
ProposalSourceKind: TypeAlias = Literal["current_message", "active_commitment_origin"]
EligibilityOutcome: TypeAlias = Literal[
    "eligible",
    "not_admitted",
    "inactive_commitment",
    "audit_only",
    "alliance_response",
    "already_projected",
    "semantic_duplicate",
]
CommitmentStatus: TypeAlias = Literal["proposed", "active", "rejected", "withdrawn", "expired"]
Tone: TypeAlias = Literal["firm", "informational", "stabilizing"]

# Claims deliberately use fixed tuples instead of open dictionaries.  The
# authenticated source Artifacts retain complete objects; the pure Kernel sees
# only immutable, positionally closed evidence.
NegotiationProposalSourceTuple: TypeAlias = tuple[
    str,
    Digest,
    str,
    Digest,
    str,
    ActionClass,
    Digest,
    ProposalSourceKind,
    str | None,
    int,
    Digest,
]
EligibilityDecisionTuple: TypeAlias = tuple[
    NegotiationProposalSourceTuple,
    bool,
    EligibilityOutcome,
    Digest,
]
CommitmentClaimTuple: TypeAlias = tuple[
    str,
    Digest,
    CommitmentStatus,
    str,
    tuple[str, ...],
    Digest,
    str,
    Digest,
    str,
    Digest,
    int,
    Digest,
]
ToneDeltaTuple: TypeAlias = tuple[Tone, int]
CountryDeltaTuple: TypeAlias = tuple[str, int]
DiffusionApplicationTuple: TypeAlias = tuple[
    str,
    str,
    str,
    Tone,
    Literal["domestic", "regional", "global"],
    int,
    int,
    int,
    int,
    int,
    int,
    Digest,
]
ProjectionRecordClaimTuple: TypeAlias = tuple[
    str,
    Digest,
    Digest,
    Literal["accepted", "rejected", "needs_revision", "not_evaluated"],
    str,
    Literal["accepted", "rejected", "constrained", "expired"],
    str | None,
    Literal["not_projected", "projected", "constrained", "blocked", "expired"],
    Digest | None,
    str | None,
    Digest,
]


def _validate_aligned(
    identifiers: tuple[str, ...], hashes: tuple[str, ...], field_name: str
) -> None:
    _validate_ascending_unique(identifiers, field_name)
    if len(identifiers) != len(hashes):
        raise ValueError(f"{field_name} and hashes must have equal length")


def _validate_int64(value: int, field_name: str) -> None:
    if value < -(2**63) or value > 2**63 - 1:
        raise ValueError(f"{field_name} must fit signed int64")


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
    proposal_hashes: tuple[Digest, ...] = ()
    proposal_count: int = Field(ge=0)
    invocation_ids: tuple[str, ...] = ()
    invocation_hashes: tuple[Digest, ...] = ()
    invocation_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_counts(self) -> Self:
        _validate_aligned(self.proposal_ids, self.proposal_hashes, "AR proposal_ids")
        _validate_aligned(self.invocation_ids, self.invocation_hashes, "AR invocation_ids")
        if self.proposal_count != len(self.proposal_ids) or self.invocation_count != len(self.invocation_ids):
            raise ValueError("AR claim counts must equal tuple lengths")
        return self


class PBClaims(KernelModeClaims):
    source_kind: Literal["mock_batch", "agent_runtime"]
    source_runtime_hash: Digest | None = None
    source_mock_batch_hash: Digest | None = None
    batch_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    proposal_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_batch_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        if (self.source_runtime_hash is None) == (self.source_mock_batch_hash is None):
            raise ValueError("PB claims require exactly one source hash")
        if self.source_kind == "mock_batch" and (
            self.source_mock_batch_hash is None or self.source_runtime_hash is not None
        ):
            raise ValueError("mock_batch PB claims require only source_mock_batch_hash")
        if self.source_kind == "agent_runtime" and (
            self.source_runtime_hash is None or self.source_mock_batch_hash is not None
        ):
            raise ValueError("agent_runtime PB claims require only source_runtime_hash")
        if self.proposal_count != len(self.proposal_ids) or len(self.proposal_ids) != len(self.proposal_hashes):
            raise ValueError("PB proposal count and hashes must match proposal_ids")
        return self


class FCClaims(KernelModeClaims):
    role: Literal["final"] = "final"
    audit_hash: Digest
    deterministic_result_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_consistency_claims(self) -> Self:
        _validate_aligned(self.proposal_ids, self.proposal_hashes, "FC proposal_ids")
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
    round_hash: Digest
    before_result_hash: Digest
    after_result_hash: Digest
    message_tuples: tuple[tuple[int, str, Digest], ...] = ()
    messages_hash: Digest
    message_count: int = Field(ge=0)
    proposal_ids: tuple[str, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    proposal_batch_hash: Digest
    admission_audit_hash: Digest
    ledger_hash: Digest
    eligibility_hash: Digest
    eligible_proposal_ids: tuple[str, ...] = ()
    projection_consistency_hash: Digest | None = None
    modifier_bundle_hash: Digest | None = None
    diffusion_evidence_hash: Digest
    projection_audit_hash: Digest | None = None
    no_projection_reason: Literal["no_projection"] | None = None

    @model_validator(mode="after")
    def validate_round_claims(self) -> Self:
        _validate_ascending_unique(self.proposal_ids, "proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        _validate_ascending_unique(self.eligible_proposal_ids, "eligible_proposal_ids")
        if not set(self.accepted_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("RR accepted_proposal_ids must be proposals")
        if self.message_count != len(self.message_tuples):
            raise ValueError("RR message_count must equal message_tuples length")
        sequence_numbers = tuple(item[0] for item in self.message_tuples)
        if any(type(value) is not int or value < 1 for value in sequence_numbers):
            raise ValueError("RR message sequence numbers must be strict positive integers")
        if tuple(sorted(self.message_tuples, key=lambda item: (item[0], item[1].encode("utf-8")))) != self.message_tuples:
            raise ValueError("RR message_tuples must be ordered by seq and message_id")
        return self


class NPClaims(KernelModeClaims):
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    source_hashes: tuple[Digest, Digest, Digest]
    proposal_claim_tuples: tuple[NegotiationProposalSourceTuple, ...] = ()
    proposal_count: int = Field(ge=0)
    batch_hash: Digest

    @model_validator(mode="after")
    def validate_proposal_sources(self) -> Self:
        proposal_ids = tuple(item[0] for item in self.proposal_claim_tuples)
        _validate_ascending_unique(proposal_ids, "NP proposal ids")
        if self.proposal_count != len(self.proposal_claim_tuples):
            raise ValueError("NP proposal_count must equal proposal_claim_tuples length")
        for item in self.proposal_claim_tuples:
            source_kind = item[7]
            commitment_id = item[8]
            source_tick = item[9]
            action_class = item[5]
            if source_kind == "current_message":
                if commitment_id is not None or source_tick != self.tick:
                    raise ValueError("current-message NP source coordinates are invalid")
            elif commitment_id is None or source_tick >= self.tick or action_class != "bilateral_commitment":
                raise ValueError("active-commitment NP source coordinates are invalid")
        return self


class ACClaims(KernelModeClaims):
    role: Literal["admission"] = "admission"
    tick: int = Field(ge=1, le=6)
    audit_hash: Digest
    deterministic_result_hash: Digest
    proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_admission_claims(self) -> Self:
        _validate_aligned(self.proposal_ids, self.proposal_hashes, "AC proposal_ids")
        _validate_ascending_unique(self.accepted_proposal_ids, "accepted_proposal_ids")
        if self.decision_count != len(self.proposal_ids):
            raise ValueError("AC decision_count must equal proposal_ids length")
        if not set(self.accepted_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("AC accepted_proposal_ids must be proposals")
        return self


class ELClaims(KernelModeClaims):
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    decision_tuples: tuple[EligibilityDecisionTuple, ...] = ()
    decision_count: int = Field(ge=0)
    eligible_proposal_ids: tuple[str, ...] = ()
    eligible_proposal_count: int = Field(ge=0)
    eligibility_hash: Digest

    @model_validator(mode="after")
    def validate_eligibility_claims(self) -> Self:
        decision_ids = tuple(item[0][0] for item in self.decision_tuples)
        _validate_ascending_unique(decision_ids, "EL decision proposal ids")
        _validate_ascending_unique(self.eligible_proposal_ids, "EL eligible_proposal_ids")
        if self.decision_count != len(self.decision_tuples):
            raise ValueError("EL decision_count must equal decision_tuples length")
        if self.eligible_proposal_count != len(self.eligible_proposal_ids):
            raise ValueError("EL eligible_proposal_count must equal eligible_proposal_ids length")
        eligible_from_decisions = tuple(
            item[0][0] for item in self.decision_tuples if item[2] == "eligible"
        )
        if eligible_from_decisions != self.eligible_proposal_ids:
            raise ValueError("EL eligible ids must equal eligible decision ids")
        for proposal, prior_projected, outcome, decision_hash in self.decision_tuples:
            expected = stable_hash(
                {"decision": [proposal, prior_projected, outcome]}
            )
            if decision_hash != expected:
                raise ValueError("EL decision_hash mismatch")
        expected_eligibility_hash = stable_hash(
            {
                "schema_version": "negotiation-eligibility.v1",
                "run_id": self.run_id,
                "session_id": self.session_id,
                "tick": self.tick,
                "decision_hashes": tuple(item[3] for item in self.decision_tuples),
                "eligible_proposal_ids": self.eligible_proposal_ids,
            }
        )
        if self.eligibility_hash != expected_eligibility_hash:
            raise ValueError("EL eligibility_hash mismatch")
        return self


class PCClaims(KernelModeClaims):
    role: Literal["projection"] = "projection"
    tick: int = Field(ge=1, le=6)
    audit_hash: Digest
    deterministic_result_hash: Digest
    candidate_proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    accepted_proposal_ids: tuple[str, ...] = ()
    decision_count: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_projection_claims(self) -> Self:
        _validate_aligned(
            self.candidate_proposal_ids,
            self.proposal_hashes,
            "PC candidate_proposal_ids",
        )
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
        if tuple(item.proposal_id for item in self.modifier_tuples) != self.accepted_proposal_ids:
            raise ValueError("MB requires exactly one modifier tuple per accepted proposal")
        return self


class NDClaims(KernelModeClaims):
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    attempted: bool
    input_proposal_ids: tuple[str, ...] = ()
    input_proposal_hashes: tuple[Digest, ...] = ()
    narrative_diffusion_audit_hash: Digest
    diffusion_request_hash: Digest
    before_result_hash: Digest
    after_result_hash: Digest
    tone_delta_tuples: tuple[ToneDeltaTuple, ...]
    country_delta_tuples: tuple[CountryDeltaTuple, ...] = ()
    application_tuples: tuple[DiffusionApplicationTuple, ...] = ()
    application_count: int = Field(ge=0)
    diffusion_evidence_hash: Digest

    @model_validator(mode="after")
    def validate_diffusion_claims(self) -> Self:
        _validate_aligned(
            self.input_proposal_ids,
            self.input_proposal_hashes,
            "ND input_proposal_ids",
        )
        if self.attempted != bool(self.input_proposal_ids):
            raise ValueError("ND attempted must equal nonempty input proposal predicate")
        if self.application_count != len(self.application_tuples):
            raise ValueError("ND application_count must equal application_tuples length")
        expected_tones = (
            ("firm", 30000),
            ("informational", -10000),
            ("stabilizing", -40000),
        )
        if self.tone_delta_tuples != expected_tones:
            raise ValueError("ND tone_delta_tuples must equal the fixed Q=10000 tuple")
        country_ids = tuple(item[0] for item in self.country_delta_tuples)
        _validate_ascending_unique(country_ids, "ND country ids")
        application_keys = tuple(
            (
                item[0].encode("utf-8"),
                item[1].encode("utf-8"),
                item[2].encode("utf-8"),
                item[3].encode("utf-8"),
                item[4].encode("utf-8"),
                item[11].encode("utf-8"),
            )
            for item in self.application_tuples
        )
        if len(set(application_keys)) != len(application_keys) or tuple(sorted(application_keys)) != application_keys:
            raise ValueError("ND application_tuples must be unique and canonical")
        for _, value in self.tone_delta_tuples + self.country_delta_tuples:
            _validate_int64(value, "ND fixed-point delta")
        for item in self.application_tuples:
            for value in item[5:11]:
                _validate_int64(value, "ND application fixed-point value")
        if not self.attempted and (
            self.application_count != 0
            or self.country_delta_tuples
            or self.application_tuples
            or self.before_result_hash != self.after_result_hash
        ):
            raise ValueError("unattempted ND claims must be an empty numeric no-op")
        return self


class CLClaims(KernelModeClaims):
    session_id: str | None = Field(default=None, min_length=1, max_length=160)
    tick: int | None = Field(default=None, ge=1, le=6)
    ledger_hash: Digest
    ledger_entry_count: int = Field(ge=0)
    commitments: tuple[CommitmentClaimTuple, ...] = ()

    @model_validator(mode="after")
    def validate_ledger_claims(self) -> Self:
        if self.ledger_entry_count != len(self.commitments):
            raise ValueError("CL ledger_entry_count must equal commitments length")
        commitment_ids = tuple(item[0] for item in self.commitments)
        _validate_ascending_unique(commitment_ids, "CL commitment ids")
        for item in self.commitments:
            parties = item[4]
            _validate_ascending_unique(parties, "CL party_agent_ids")
            if len(parties) != 2:
                raise ValueError("negotiation CL commitments must bind exactly two parties")
            if item[10] < 1 or item[10] > 6:
                raise ValueError("CL source_admission_tick must be in 1..6")
        if len(set(commitment_ids)) != len(self.commitments):
            raise ValueError("CL commitment ids must be unique")
        return self


class PAClaims(KernelModeClaims):
    tick: int | None = Field(default=None, ge=1, le=6)
    projection_mode: Literal["audit_only", "hybrid", "negotiation"]
    audit_hash: Digest
    consistency_audit_hash: Digest
    modifier_bundle_hash: Digest | None = None
    proposal_ids: tuple[str, ...] = ()
    proposal_hashes: tuple[Digest, ...] = ()
    record_input_hashes: tuple[Digest, ...] = ()
    record_claim_tuples: tuple[ProjectionRecordClaimTuple, ...] = ()
    projected_proposal_ids: tuple[str, ...] = ()
    projected_semantic_key_hashes: tuple[Digest, ...] = ()
    modifier_tuples: tuple[ModifierReference, ...] = ()
    modifier_count: int = Field(ge=0)
    record_count: int = Field(ge=0)
    before_result_hash: Digest
    final_result_hash: Digest

    @model_validator(mode="after")
    def validate_audit_claims(self) -> Self:
        _validate_aligned(self.proposal_ids, self.proposal_hashes, "PA proposal_ids")
        _validate_aligned(
            self.projected_proposal_ids,
            self.projected_semantic_key_hashes,
            "PA projected_proposal_ids",
        )
        if not (
            self.record_count
            == len(self.proposal_ids)
            == len(self.record_input_hashes)
            == len(self.record_claim_tuples)
        ):
            raise ValueError("PA record vectors and proposal vectors must have equal length")
        for index, record in enumerate(self.record_claim_tuples):
            if (
                record[0] != self.proposal_ids[index]
                or record[1] != self.proposal_hashes[index]
                or record[2] != self.record_input_hashes[index]
                or record[10] != self.final_result_hash
            ):
                raise ValueError("PA record claims must align with top-level vectors")
        if self.modifier_count != len(self.modifier_tuples):
            raise ValueError("PA modifier_count must equal modifier_tuples length")
        _validate_modifier_tuples(self.modifier_tuples, "PA modifier_tuples")
        if not set(self.projected_proposal_ids).issubset(self.proposal_ids):
            raise ValueError("PA projected_proposal_ids must be proposals")
        if tuple(item.proposal_id for item in self.modifier_tuples) != self.projected_proposal_ids:
            raise ValueError("PA requires exactly one modifier tuple per projected proposal")
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
    proposal_batch_hash: Digest
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
    proposal_batch_hashes: tuple[Digest, ...]
    admission_audit_hashes: tuple[Digest, ...]
    ledger_hashes: tuple[Digest, ...]
    eligibility_hashes: tuple[Digest, ...]
    projection_consistency_hashes: tuple[Digest | None, ...]
    modifier_bundle_hashes: tuple[Digest | None, ...]
    diffusion_evidence_hashes: tuple[Digest, ...]
    projection_audit_hashes: tuple[Digest | None, ...]
    message_chain_head: Digest | None
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
            self.proposal_batch_hashes,
            self.admission_audit_hashes,
            self.ledger_hashes,
            self.eligibility_hashes,
            self.projection_consistency_hashes,
            self.modifier_bundle_hashes,
            self.diffusion_evidence_hashes,
            self.projection_audit_hashes,
        )
        if any(len(sequence) != 6 for sequence in sequences):
            raise ValueError("NR tick-ordered hash tuples must contain six entries")
        return self


ModeClaims: TypeAlias = (
    ARClaims | PBClaims | FCClaims | RRClaims | NPClaims | ACClaims | CLClaims | ELClaims | PCClaims | MBClaims | NDClaims | PAClaims | HRClaims | NRClaims
)
_CLAIMS_BY_SCHEMA: Mapping[ProofSchema, type[KernelModeClaims]] = MappingProxyType({
    "kp.agent-runtime.v1": ARClaims,
    "kp.proposal-batch.v1": PBClaims,
    "kp.final-consistency.v1": FCClaims,
    "kp.negotiation-round.v1": RRClaims,
    "kp.negotiation-proposal-batch.v1": NPClaims,
    "kp.negotiation-admission-consistency.v1": ACClaims,
    "kp.negotiation-eligibility.v1": ELClaims,
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
    "kp.negotiation-proposal-batch.v1": "NP",
    "kp.negotiation-admission-consistency.v1": "AC",
    "kp.negotiation-eligibility.v1": "EL",
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
    "kp.negotiation-proposal-batch.v1": frozenset({"negotiation_proposal_batch"}),
    "kp.negotiation-admission-consistency.v1": frozenset({"consistency_audit"}),
    "kp.negotiation-eligibility.v1": frozenset({"negotiation_eligibility"}),
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
    "kp.proposal-batch.v1": frozenset({"kernel-proposal-batch.v1"}),
    "kp.final-consistency.v1": frozenset({"consistency-audit.v3"}),
    "kp.negotiation-round.v1": frozenset({"negotiation-round.v2"}),
    "kp.negotiation-proposal-batch.v1": frozenset({"negotiation-proposal-batch.v1"}),
    "kp.negotiation-admission-consistency.v1": frozenset({"consistency-audit.v3"}),
    "kp.negotiation-eligibility.v1": frozenset({"negotiation-eligibility.v1"}),
    "kp.negotiation-projection-consistency.v1": frozenset({"consistency-audit.v3"}),
    "kp.action-modifier-bundle.v1": frozenset({"hybrid-modifier-bundle.v2"}),
    "kp.narrative-diffusion.v1": frozenset({"narrative-diffusion.v2"}),
    "kp.commitment-ledger.v1": frozenset({"commitment-ledger.v2"}),
    "kp.projection-audit.v1": frozenset({"agent-action-projection-audit.v2", "negotiation-projection-audit.v2"}),
    "kp.hybrid-replay.v1": frozenset({"hybrid-replay-record.v2"}),
    "kp.negotiation-replay.v1": frozenset({"negotiation-replay.v2"}),
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
    authority_path: str
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
        if self.authority_path != AUTHORITY_PATH_BY_ENGINE_MODE[self.engine_mode]:
            raise ValueError("authority_path must match the fixed engine-mode authority path")
        expected_hash = stable_hash(self.model_dump(mode="json", exclude={"record_hash"}))
        if self.record_hash != expected_hash:
            raise ValueError("Kernel mode execution record_hash mismatch")
        return self


# Descriptive aliases keep callers from coupling to the short ADR table tokens.
AgentRuntimeClaims = ARClaims
ProposalBatchClaims = PBClaims
FinalConsistencyClaims = FCClaims
NegotiationRoundClaims = RRClaims
NegotiationProposalBatchClaims = NPClaims
NegotiationAdmissionConsistencyClaims = ACClaims
NegotiationEligibilityClaims = ELClaims
NegotiationProjectionConsistencyClaims = PCClaims
ActionModifierBundleClaims = MBClaims
NarrativeDiffusionClaims = NDClaims
CommitmentLedgerClaims = CLClaims
ProjectionAuditClaims = PAClaims
HybridReplayClaims = HRClaims
NegotiationReplayClaims = NRClaims
