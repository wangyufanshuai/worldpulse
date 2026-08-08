"""Canonical negotiation source verification and claims-only extraction.

The functions in this module are Run Control adapters.  They accept payloads
only after the generic Artifact layer has compared the outer byte SHA-256,
validate the complete closed source object and its content hashes, and return
the reduced immutable claims admitted by the pure Simulation Kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.negotiation_models import NegotiationMessage
from app.services.agent_contract.models import (
    AgentActionProposal,
    AgentConstraintContext,
    MockAgentBatch,
)
from app.services.agent_runtime.models import AgentInvocationAudit
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import (
    AgentActionDecision,
    ConsistencyAuditReport,
    ConsistencyFinding,
)
from app.services.hybrid_simulation.adapter import verify_modifier_bundle
from app.services.hybrid_simulation.models import (
    DeterministicActionModifier,
    HybridModifierBundle,
)
from app.services.simulation_kernel.mode_contracts import (
    ARClaims,
    CLClaims,
    ACClaims,
    ELClaims,
    FCClaims,
    HRClaims,
    MBClaims,
    NDClaims,
    NPClaims,
    NRClaims,
    PBClaims,
    PAClaims,
    PCClaims,
    CommitmentClaimTuple,
    ConsistencyDecisionClaimTuple,
    CountryDeltaTuple,
    DiffusionApplicationTuple,
    EligibilityDecisionTuple,
    NegotiationProposalSourceTuple,
    ModifierReference,
    ProjectionRecordClaimTuple,
    RRClaims,
    ToneDeltaTuple,
)


SHA256_PATTERN = r"^[0-9a-f]{64}$"
Digest: TypeAlias = Annotated[str, Field(pattern=SHA256_PATTERN)]
ActionClass: TypeAlias = Literal[
    "deterministic_modifier",
    "bilateral_commitment",
    "public_narrative",
    "audit_only",
    "alliance_response",
]
EligibilityOutcome: TypeAlias = Literal[
    "eligible",
    "not_admitted",
    "inactive_commitment",
    "audit_only",
    "alliance_response",
    "already_projected",
    "semantic_duplicate",
]
CommitmentStatus: TypeAlias = Literal[
    "proposed", "active", "rejected", "withdrawn", "expired"
]
Tone: TypeAlias = Literal["firm", "informational", "stabilizing"]
Audience: TypeAlias = Literal["domestic", "regional", "global"]
FIXED_POINT_SCALE = 10_000
INT64_MIN = -(2**63)
INT64_MAX = 2**63 - 1

ACTION_CLASS_BY_TYPE: Mapping[str, ActionClass] = {
    "diplomatic_signal": "deterministic_modifier",
    "sanction_proposal": "deterministic_modifier",
    "trade_reroute_request": "deterministic_modifier",
    "alliance_request": "bilateral_commitment",
    "humanitarian_offer": "bilateral_commitment",
    "deescalation_offer": "bilateral_commitment",
    "public_narrative": "public_narrative",
    "intelligence_request": "audit_only",
    "alliance_response": "alliance_response",
}


def _restore_lists(value: object) -> object:
    """Convert immutable tuple containers back to JSON arrays for legacy models."""

    if isinstance(value, tuple):
        return [_restore_lists(item) for item in value]
    if isinstance(value, dict):
        return {key: _restore_lists(item) for key, item in value.items()}
    return value


def _checked_int64(value: int, field_name: str) -> int:
    if value < INT64_MIN or value > INT64_MAX:
        raise ValueError(f"{field_name} overflows signed int64")
    return value


def _to_units(value: int | float, field_name: str) -> int:
    units = int(
        (Decimal(str(value)) * FIXED_POINT_SCALE).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    return _checked_int64(units, field_name)


def _mul_units(left: int, right: int, field_name: str) -> int:
    product = int(
        (Decimal(left) * Decimal(right) / FIXED_POINT_SCALE).quantize(
            Decimal("1"), rounding=ROUND_HALF_EVEN
        )
    )
    return _checked_int64(product, field_name)


class ClosedSource(BaseModel):
    """Strict scalar validation with canonical JSON arrays restored to tuples."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    @model_validator(mode="before")
    @classmethod
    def restore_json_arrays(cls, value: object) -> object:
        def restore(item: object) -> object:
            if isinstance(item, list):
                return tuple(restore(child) for child in item)
            if isinstance(item, dict):
                return {key: restore(child) for key, child in item.items()}
            return item

        return restore(value)


class AgentRuntimeResultSource(ClosedSource):
    """Complete legacy runtime result admitted by the V2 AR extractor."""

    schema_version: Literal["agent-runtime-result.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    provider: str = Field(min_length=1, max_length=160)
    model: str = Field(min_length=1, max_length=240)
    mode: Literal["live", "mock", "skipped"]
    fallback_reason: str | None
    runtime_config: dict[str, object]
    proposals: tuple[dict[str, object], ...]
    constraint_context: dict[str, object]
    invocations: tuple[dict[str, object], ...]
    total_calls: int = Field(ge=0)
    total_estimated_tokens: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    runtime_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        proposals, invocations = _validated_agent_runtime_vectors(self)
        if len({item.proposal_id for item in proposals}) != len(proposals):
            raise ValueError("AR proposal IDs must be unique")
        if len({item.invocation_id for item in invocations}) != len(invocations):
            raise ValueError("AR invocation IDs must be unique")
        expected_runtime_hash = stable_hash(
            {
                "provider": self.provider,
                "model": self.model,
                "mode": self.mode,
                "proposal_ids": [item.proposal_id for item in proposals],
                "invocations": [
                    {
                        "turn": item.turn,
                        "actor_id": item.actor_id,
                        "role_id": item.role_id,
                        "provider": item.provider,
                        "model": item.model,
                        "prompt_version": item.prompt_version,
                        "prompt_hash": item.prompt_hash,
                        "response_hash": item.response_hash,
                        "status": item.status,
                        "error_code": item.error_code,
                    }
                    for item in invocations
                ],
            }
        )
        if self.runtime_hash != expected_runtime_hash:
            raise ValueError("AR runtime_hash mismatch")
        return self


def _require_exact_keys(
    payload: Mapping[str, object], expected: set[str], field_name: str
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{field_name} must contain exactly its v1 fields")


def _validated_complete_proposal(
    raw: Mapping[str, object], *, run_id: str | None, field_name: str
) -> tuple[AgentActionProposal, dict[str, object]]:
    proposal_payload = dict(raw)
    _require_exact_keys(
        proposal_payload,
        set(AgentActionProposal.model_fields),
        field_name,
    )
    restored = _restore_lists(proposal_payload)
    proposal = AgentActionProposal.model_validate(restored, strict=True)
    if proposal.schema_version != "agent-action-proposal.v1":
        raise ValueError(f"{field_name} schema mismatch")
    if run_id is not None and proposal.run_id != run_id:
        raise ValueError(f"{field_name} run_id mismatch")
    canonical = proposal.model_dump(mode="json")
    if stable_hash({"proposal": restored}) != stable_hash({"proposal": canonical}):
        raise ValueError(f"{field_name} must already be canonical")
    return proposal, canonical


def _validated_complete_context(
    raw: Mapping[str, object], *, field_name: str
) -> tuple[AgentConstraintContext, dict[str, object]]:
    context_payload = dict(raw)
    _require_exact_keys(
        context_payload,
        set(AgentConstraintContext.model_fields),
        field_name,
    )
    if context_payload.get("schema_version") != "agent-constraint-context.v1":
        raise ValueError(f"{field_name} schema mismatch")
    restored = _restore_lists(context_payload)
    context = AgentConstraintContext.model_validate(restored, strict=True)
    canonical = context.model_dump(mode="json")
    if stable_hash({"context": restored}) != stable_hash({"context": canonical}):
        raise ValueError(f"{field_name} must already be canonical")
    return context, canonical


def _validated_agent_runtime_vectors(
    source: AgentRuntimeResultSource,
) -> tuple[tuple[AgentActionProposal, ...], tuple[AgentInvocationAudit, ...]]:
    _validated_complete_context(
        source.constraint_context,
        field_name="AR constraint context",
    )

    proposals: list[AgentActionProposal] = []
    for raw in source.proposals:
        proposal, _ = _validated_complete_proposal(
            raw,
            run_id=source.run_id,
            field_name="AR proposal",
        )
        proposals.append(proposal)

    invocations: list[AgentInvocationAudit] = []
    for raw in source.invocations:
        invocation_payload = dict(raw)
        _require_exact_keys(
            invocation_payload,
            set(AgentInvocationAudit.model_fields),
            "AR invocation",
        )
        invocation = AgentInvocationAudit.model_validate(
            _restore_lists(invocation_payload), strict=True
        )
        if invocation.schema_version != "agent-invocation-audit.v1":
            raise ValueError("AR invocation schema mismatch")
        if invocation.run_id != source.run_id:
            raise ValueError("AR invocation run_id mismatch")
        invocations.append(invocation)
    return tuple(proposals), tuple(invocations)


class MockAgentBatchSource(ClosedSource):
    """Complete mock-agent-batch.v1 source bound by mock PB lineage."""

    schema_version: Literal["mock-agent-batch.v1"]
    provider: Literal["mock-deterministic"]
    seed: int
    proposals: tuple[dict[str, object], ...]
    constraint_context: dict[str, object]
    batch_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        if type(self.seed) is not int:
            raise ValueError("mock batch seed must be a strict integer")
        proposals, canonical_proposals = _validated_mock_agent_batch_proposals(
            self, run_id=None
        )
        if len({item.proposal_id for item in proposals}) != len(proposals):
            raise ValueError("mock batch proposal IDs must be unique")
        _, canonical_context = _validated_complete_context(
            self.constraint_context,
            field_name="mock batch constraint context",
        )
        identity: dict[str, object] = {
            "provider": self.provider,
            "seed": self.seed,
            "proposal_ids": [item.proposal_id for item in proposals],
        }
        if canonical_proposals:
            identity["constraint_context"] = canonical_context
        if self.batch_hash != stable_hash(identity):
            raise ValueError("mock batch legacy batch_hash mismatch")
        return self


def _validated_mock_agent_batch_proposals(
    source: MockAgentBatchSource, *, run_id: str | None
) -> tuple[tuple[AgentActionProposal, ...], tuple[dict[str, object], ...]]:
    pairs = tuple(
        _validated_complete_proposal(
            raw,
            run_id=run_id,
            field_name="mock batch proposal",
        )
        for raw in source.proposals
    )
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


def mock_agent_batch_source_hash(source: MockAgentBatchSource) -> str:
    """Hash the complete, closed mock source independently from its legacy hash."""

    return stable_hash(source.model_dump(mode="json"))


class KernelProposalBatchSource(ClosedSource):
    """Complete proposal-batch wrapper admitted by the V2 PB extractor."""

    schema_version: Literal["kernel-proposal-batch.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    source_kind: Literal["mock_batch", "agent_runtime"]
    source_runtime_hash: Digest | None
    source_mock_batch_hash: Digest | None
    proposal_ids: tuple[str, ...]
    proposal_hashes: tuple[Digest, ...]
    proposals: tuple[dict[str, object], ...]
    proposal_count: int = Field(ge=0)
    batch_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        proposals, canonical_proposals = _validated_kernel_proposal_batch_vectors(self)
        proposal_ids = tuple(item.proposal_id for item in proposals)
        proposal_hashes = tuple(
            stable_hash(item.model_dump(mode="json")) for item in proposals
        )
        claims = PBClaims(
            run_id=self.run_id,
            source_kind=self.source_kind,
            source_runtime_hash=self.source_runtime_hash,
            source_mock_batch_hash=self.source_mock_batch_hash,
            batch_hash=self.batch_hash,
            proposal_ids=self.proposal_ids,
            proposal_hashes=self.proposal_hashes,
            proposal_count=self.proposal_count,
        )
        if (
            claims.proposal_ids != proposal_ids
            or claims.proposal_hashes != proposal_hashes
            or claims.proposal_count != len(proposals)
        ):
            raise ValueError("PB proposal vectors must match complete proposals")
        expected_batch_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "source_kind": self.source_kind,
                "source_runtime_hash": self.source_runtime_hash,
                "source_mock_batch_hash": self.source_mock_batch_hash,
                "proposal_ids": self.proposal_ids,
                "proposal_hashes": self.proposal_hashes,
                "proposals": canonical_proposals,
                "proposal_count": self.proposal_count,
            }
        )
        if self.batch_hash != expected_batch_hash:
            raise ValueError("PB batch_hash mismatch")
        return self

    def extract_claims(self) -> PBClaims:
        return PBClaims(
            run_id=self.run_id,
            source_kind=self.source_kind,
            source_runtime_hash=self.source_runtime_hash,
            source_mock_batch_hash=self.source_mock_batch_hash,
            batch_hash=self.batch_hash,
            proposal_ids=self.proposal_ids,
            proposal_hashes=self.proposal_hashes,
            proposal_count=self.proposal_count,
        )


def build_kernel_proposal_batch_source(
    *,
    run_id: str,
    proposals: tuple[AgentActionProposal, ...],
    source_kind: Literal["mock_batch", "agent_runtime"],
    mock_batch: MockAgentBatch | Mapping[str, object] | None = None,
    runtime_hash: str | None = None,
) -> KernelProposalBatchSource:
    """Build the canonical V2 PB wrapper from one complete source transcript."""

    ordered = tuple(
        sorted(proposals, key=lambda item: item.proposal_id.encode("utf-8"))
    )
    proposal_ids = tuple(item.proposal_id for item in ordered)
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("PB source proposals must have unique IDs")
    for proposal in ordered:
        if proposal.schema_version != "agent-action-proposal.v1" or proposal.run_id != run_id:
            raise ValueError("PB source proposal identity mismatch")
        target_ids = tuple(proposal.target_ids)
        if target_ids != tuple(
            sorted(set(target_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("PB source proposal targets are not canonical")

    source_mock_batch_hash: str | None = None
    source_runtime_hash: str | None = None
    if source_kind == "mock_batch":
        if mock_batch is None or runtime_hash is not None:
            raise ValueError("mock PB requires exactly one complete mock source")
        raw_mock = (
            mock_batch.model_dump(mode="json")
            if isinstance(mock_batch, MockAgentBatch)
            else dict(mock_batch)
        )
        parsed_mock = MockAgentBatchSource.model_validate(raw_mock)
        mock_proposals, _ = _validated_mock_agent_batch_proposals(
            parsed_mock,
            run_id=run_id,
        )
        mock_by_id = {
            item.proposal_id: item.model_dump(mode="json")
            for item in mock_proposals
        }
        ordered_by_id = {
            item.proposal_id: item.model_dump(mode="json") for item in ordered
        }
        if mock_by_id != ordered_by_id:
            raise ValueError("PB proposals drift from the complete mock source")
        source_mock_batch_hash = mock_agent_batch_source_hash(parsed_mock)
    else:
        if mock_batch is not None or runtime_hash is None:
            raise ValueError("runtime PB requires exactly one runtime hash")
        source_runtime_hash = runtime_hash

    proposal_hashes = tuple(
        stable_hash(item.model_dump(mode="json")) for item in ordered
    )
    payload = {
        "schema_version": "kernel-proposal-batch.v1",
        "run_id": run_id,
        "source_kind": source_kind,
        "source_runtime_hash": source_runtime_hash,
        "source_mock_batch_hash": source_mock_batch_hash,
        "proposal_ids": proposal_ids,
        "proposal_hashes": proposal_hashes,
        "proposals": tuple(item.model_dump(mode="json") for item in ordered),
        "proposal_count": len(ordered),
    }
    return KernelProposalBatchSource.model_validate(
        {**payload, "batch_hash": stable_hash(payload)}
    )


def _validated_kernel_proposal_batch_vectors(
    source: KernelProposalBatchSource,
) -> tuple[tuple[AgentActionProposal, ...], tuple[dict[str, object], ...]]:
    pairs: list[tuple[AgentActionProposal, dict[str, object]]] = []
    for raw in source.proposals:
        pairs.append(
            _validated_complete_proposal(
                raw,
                run_id=source.run_id,
                field_name="PB proposal",
            )
        )
    return tuple(item[0] for item in pairs), tuple(item[1] for item in pairs)


class NegotiationRoundSource(ClosedSource):
    """Complete negotiation-round.v2 source admitted by the RR extractor."""

    schema_version: Literal["negotiation-round.v2"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    round_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    input: dict[str, object]
    input_hash: Digest
    output: dict[str, object]
    output_hash: Digest
    round_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        input_payload, messages = _validated_round_input(self)
        output_payload = _validated_round_output(self)
        expected_round_id = (
            "round_"
            + stable_hash({"session": self.session_id, "tick": self.tick})[:20]
        )
        if self.round_id != expected_round_id:
            raise ValueError("RR round_id is not the canonical session/tick ID")
        expected_input_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "round_id": self.round_id,
                "tick": self.tick,
                "input": input_payload,
            }
        )
        expected_output_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "round_id": self.round_id,
                "tick": self.tick,
                "output": output_payload,
            }
        )
        if self.input_hash != expected_input_hash:
            raise ValueError("RR input_hash mismatch")
        if self.output_hash != expected_output_hash:
            raise ValueError("RR output_hash mismatch")
        expected_round_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "round_id": self.round_id,
                "tick": self.tick,
                "input_hash": self.input_hash,
                "output_hash": self.output_hash,
            }
        )
        if self.round_hash != expected_round_hash:
            raise ValueError("RR round_hash mismatch")
        if len(messages) > 1:
            for previous, current in zip(messages, messages[1:], strict=True):
                if current.previous_hash != previous.message_hash:
                    raise ValueError("RR local message predecessor chain mismatch")
        return self


def _validated_round_message(
    raw: Mapping[str, object], *, source: NegotiationRoundSource
) -> tuple[NegotiationMessage, dict[str, object], AgentActionProposal | None]:
    message_payload = dict(raw)
    _require_exact_keys(
        message_payload,
        set(NegotiationMessage.model_fields),
        "RR message",
    )
    restored = _restore_lists(message_payload)
    message = NegotiationMessage.model_validate(restored, strict=True)
    canonical = message.model_dump(mode="json")
    if stable_hash({"message": restored}) != stable_hash({"message": canonical}):
        raise ValueError("RR message must already be canonical")
    if message.session_id != source.session_id or message.round_id != source.round_id:
        raise ValueError("RR message session/round coordinate mismatch")
    if message.tick != source.tick:
        raise ValueError("RR message tick mismatch")
    if type(message.seq) is not int or message.seq < 1:
        raise ValueError("RR message seq must be a strict positive integer")
    if message.latency_ms < 0 or message.estimated_tokens < 0:
        raise ValueError("RR message runtime counters must be non-negative")
    payload = message.payload
    proposal: AgentActionProposal | None = None
    if message.proposal_id is None:
        if payload != {}:
            raise ValueError("RR message without proposal must have empty payload")
    else:
        if set(payload) != {"proposal"} or not isinstance(payload["proposal"], dict):
            raise ValueError("RR proposal message must have one complete proposal")
        proposal, canonical_proposal = _validated_complete_proposal(
            payload["proposal"],
            run_id=source.run_id,
            field_name="RR message proposal",
        )
        if proposal.proposal_id != message.proposal_id:
            raise ValueError("RR message proposal_id mismatch")
        if payload["proposal"] != canonical_proposal:
            raise ValueError("RR message proposal payload mismatch")
    expected_hash = stable_hash(
        {
            "tick": message.tick,
            "seq": message.seq,
            "sender_agent_id": message.sender_agent_id,
            "recipient_agent_ids": message.recipient_agent_ids,
            "message_type": message.message_type,
            "visibility": message.visibility,
            "parent_message_id": message.parent_message_id,
            "proposal": proposal.model_dump(mode="json") if proposal is not None else None,
            "narrative": message.narrative,
            "previous_hash": message.previous_hash,
        }
    )
    if message.message_hash != expected_hash:
        raise ValueError("RR message_hash mismatch")
    if message.message_id != f"msg_{expected_hash[:20]}":
        raise ValueError("RR message_id mismatch")
    return message, canonical, proposal


def _validated_round_input(
    source: NegotiationRoundSource,
) -> tuple[dict[str, object], tuple[NegotiationMessage, ...]]:
    expected_keys = {
        "before_result_hash",
        "message_tuples",
        "messages",
        "messages_hash",
        "message_count",
        "proposal_ids",
        "accepted_proposal_ids",
        "proposal_batch_hash",
        "admission_audit_hash",
        "ledger_hash",
        "eligibility_hash",
        "eligible_proposal_ids",
    }
    raw = dict(source.input)
    _require_exact_keys(raw, expected_keys, "RR input")
    restored = _restore_lists(raw)
    if not isinstance(restored, dict):
        raise ValueError("RR input must be an object")
    messages_raw = restored["messages"]
    tuples_raw = restored["message_tuples"]
    if not isinstance(messages_raw, list) or not isinstance(tuples_raw, list):
        raise ValueError("RR message vectors must be arrays")
    parsed = tuple(
        _validated_round_message(item, source=source)
        for item in messages_raw
        if isinstance(item, dict)
    )
    if len(parsed) != len(messages_raw):
        raise ValueError("RR messages must be complete objects")
    messages = tuple(item[0] for item in parsed)
    canonical_messages = [item[1] for item in parsed]
    message_tuples = [
        [item.seq, item.message_id, item.message_hash] for item in messages
    ]
    if tuples_raw != message_tuples:
        raise ValueError("RR message tuples must align with complete messages")
    if (
        type(restored["message_count"]) is not int
        or restored["message_count"] < 0
        or restored["message_count"] != len(messages)
    ):
        raise ValueError("RR message_count mismatch")
    sequences = tuple(item.seq for item in messages)
    if sequences and sequences != tuple(range(sequences[0], sequences[0] + len(sequences))):
        raise ValueError("RR local message seq must be contiguous")
    proposal_ids = tuple(
        sorted(
            (item[2].proposal_id for item in parsed if item[2] is not None),
            key=lambda value: value.encode("utf-8"),
        )
    )
    for name in ("proposal_ids", "accepted_proposal_ids", "eligible_proposal_ids"):
        raw_values = restored[name]
        if not isinstance(raw_values, list) or any(
            not isinstance(value, str) for value in raw_values
        ):
            raise ValueError(f"RR {name} must be an array of strings")
    stored_proposal_ids = tuple(restored["proposal_ids"])
    if stored_proposal_ids != proposal_ids or len(
        set(stored_proposal_ids)
    ) != len(stored_proposal_ids):
        raise ValueError("RR proposal_ids must equal current-message proposals")
    for name in ("accepted_proposal_ids", "eligible_proposal_ids"):
        values = tuple(restored[name])
        if values != tuple(sorted(set(values), key=lambda value: value.encode("utf-8"))):
            raise ValueError(f"RR {name} must be unique and ascending")
    expected_messages_hash = stable_hash(
        {
            "schema_version": source.schema_version,
            "run_id": source.run_id,
            "session_id": source.session_id,
            "tick": source.tick,
            "message_tuples": message_tuples,
        }
    )
    if restored["messages_hash"] != expected_messages_hash:
        raise ValueError("RR messages_hash mismatch")
    canonical = dict(restored)
    canonical["messages"] = canonical_messages
    canonical["message_tuples"] = message_tuples
    return canonical, messages


def _validated_round_output(source: NegotiationRoundSource) -> dict[str, object]:
    expected_keys = {
        "projection_consistency_hash",
        "modifier_bundle_hash",
        "diffusion_evidence_hash",
        "projection_audit_hash",
        "no_projection_reason",
        "after_result_hash",
    }
    raw = dict(source.output)
    _require_exact_keys(raw, expected_keys, "RR output")
    restored = _restore_lists(raw)
    if not isinstance(restored, dict):
        raise ValueError("RR output must be an object")
    projected = restored["projection_consistency_hash"] is not None
    conditional = (
        restored["projection_consistency_hash"],
        restored["modifier_bundle_hash"],
        restored["projection_audit_hash"],
    )
    if projected:
        if any(value is None for value in conditional) or restored["no_projection_reason"] is not None:
            raise ValueError("RR projected output binding is incomplete")
    elif any(value is not None for value in conditional) or restored["no_projection_reason"] != "no_projection":
        raise ValueError("RR no-projection output binding is invalid")
    return restored


class NegotiationProposalBatchSource(ClosedSource):
    schema_version: Literal["negotiation-proposal-batch.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    source_hashes: tuple[Digest, Digest, Digest]
    proposal_claim_tuples: tuple[NegotiationProposalSourceTuple, ...]
    proposal_count: int = Field(ge=0)
    proposals: tuple[dict[str, object], ...]
    batch_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        claims = NPClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            source_hashes=self.source_hashes,
            proposal_claim_tuples=self.proposal_claim_tuples,
            proposal_count=self.proposal_count,
            batch_hash=self.batch_hash,
        )
        if self.proposal_count != len(self.proposals):
            raise ValueError("NP proposal_count must equal complete proposal count")
        for claim, raw_proposal in zip(claims.proposal_claim_tuples, self.proposals, strict=True):
            proposal = AgentActionProposal.model_validate(
                _restore_lists(raw_proposal), strict=True
            )
            proposal_payload = proposal.model_dump(mode="json")
            proposal_hash = stable_hash(proposal_payload)
            target_ids = tuple(proposal.target_ids)
            if len(set(target_ids)) != len(target_ids) or target_ids != tuple(
                sorted(target_ids, key=lambda value: value.encode("utf-8"))
            ):
                raise ValueError("NP complete proposal target_ids must be unique and ascending")
            expected_class = ACTION_CLASS_BY_TYPE.get(proposal.action_type)
            semantic_key_hash = stable_hash(
                {
                    "actor_id": proposal.actor_id,
                    "action_type": proposal.action_type,
                    "target_ids": target_ids,
                    "parameters": proposal.parameters,
                }
            )
            if (
                proposal.schema_version != "agent-action-proposal.v1"
                or proposal.run_id != self.run_id
                or claim[0] != proposal.proposal_id
                or claim[1] != proposal_hash
                or claim[4] != proposal.action_type
                or claim[5] != expected_class
                or claim[6] != semantic_key_hash
            ):
                raise ValueError("NP claim tuple does not match its complete proposal")
            if claim[7] == "current_message" and proposal.turn != self.tick:
                raise ValueError("NP current proposal turn must equal the current tick")
            if claim[7] == "active_commitment_origin" and proposal.turn != claim[9]:
                raise ValueError("NP active origin must retain its source-admission turn")

        expected_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "tick": self.tick,
                "source_hashes": self.source_hashes,
                "proposal_claim_tuples": self.proposal_claim_tuples,
                "proposal_count": self.proposal_count,
                "proposals": self.proposals,
            }
        )
        if self.batch_hash != expected_hash:
            raise ValueError("NP batch_hash mismatch")
        return self

    def extract_claims(self) -> NPClaims:
        return NPClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            source_hashes=self.source_hashes,
            proposal_claim_tuples=self.proposal_claim_tuples,
            proposal_count=self.proposal_count,
            batch_hash=self.batch_hash,
        )


class NegotiationEligibilityDecisionSource(ClosedSource):
    proposal_claim_tuple: NegotiationProposalSourceTuple
    prior_projected: bool
    outcome: EligibilityOutcome
    decision_hash: Digest

    @model_validator(mode="after")
    def validate_decision_hash(self) -> Self:
        expected = stable_hash(
            {
                "decision": [
                    self.proposal_claim_tuple,
                    self.prior_projected,
                    self.outcome,
                ]
            }
        )
        if self.decision_hash != expected:
            raise ValueError("EL decision_hash mismatch")
        return self

    def as_claim_tuple(self) -> EligibilityDecisionTuple:
        return (
            self.proposal_claim_tuple,
            self.prior_projected,
            self.outcome,
            self.decision_hash,
        )


class NegotiationEligibilitySource(ClosedSource):
    schema_version: Literal["negotiation-eligibility.v1"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    decisions: tuple[NegotiationEligibilityDecisionSource, ...]
    decision_count: int = Field(ge=0)
    eligible_proposal_ids: tuple[str, ...]
    eligible_proposal_count: int = Field(ge=0)
    eligibility_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        self.extract_claims()
        return self

    def extract_claims(self) -> ELClaims:
        return ELClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            decision_tuples=tuple(item.as_claim_tuple() for item in self.decisions),
            decision_count=self.decision_count,
            eligible_proposal_ids=self.eligible_proposal_ids,
            eligible_proposal_count=self.eligible_proposal_count,
            eligibility_hash=self.eligibility_hash,
        )


class CommitmentEventSource(ClosedSource):
    tick: int = Field(ge=1, le=6)
    seq: int = Field(ge=1)
    status: CommitmentStatus
    actor_agent_id: str = Field(min_length=1, max_length=160)
    source_message_id: str | None = Field(default=None, min_length=1, max_length=160)
    source_message_hash: Digest | None = None
    previous_event_hash: Digest | None = None
    event_hash: Digest


class CommitmentEntrySource(ClosedSource):
    commitment_id: str = Field(min_length=1, max_length=160)
    commitment_hash: Digest
    status: CommitmentStatus
    action_type: str = Field(min_length=1, max_length=120)
    party_agent_ids: tuple[str, ...]
    terms: dict[str, object]
    terms_hash: Digest
    source_proposal_id: str = Field(min_length=1, max_length=160)
    source_proposal_hash: Digest
    source_message_id: str = Field(min_length=1, max_length=160)
    source_message_hash: Digest
    source_admission_tick: int = Field(ge=1, le=6)
    source_admission_audit_hash: Digest
    events: tuple[CommitmentEventSource, ...]

    @model_validator(mode="after")
    def validate_entry_hashes_and_events(self) -> Self:
        if ACTION_CLASS_BY_TYPE.get(self.action_type) != "bilateral_commitment":
            raise ValueError("CL commitment action_type must be bilateral")
        if len(self.party_agent_ids) != 2 or tuple(
            sorted(set(self.party_agent_ids), key=lambda value: value.encode("utf-8"))
        ) != self.party_agent_ids:
            raise ValueError("CL party_agent_ids must be exactly two unique sorted ids")
        expected_terms_hash = stable_hash(
            {"schema_version": "commitment-ledger.v2", "terms": self.terms}
        )
        if self.terms_hash != expected_terms_hash:
            raise ValueError("CL terms_hash mismatch")
        if self.terms.get("action_type") != self.action_type:
            raise ValueError("CL terms action_type mismatch")
        proposal_payload = self.terms.get("proposal")
        if not isinstance(proposal_payload, dict):
            raise ValueError("CL terms must retain the complete source proposal")
        proposal = AgentActionProposal.model_validate(
            _restore_lists(proposal_payload), strict=True
        )
        if (
            proposal.proposal_id != self.source_proposal_id
            or stable_hash(proposal.model_dump(mode="json")) != self.source_proposal_hash
            or proposal.action_type != self.action_type
            or proposal.turn != self.source_admission_tick
        ):
            raise ValueError("CL complete source proposal binding mismatch")

        expected_commitment_hash = stable_hash(
            {
                "schema_version": "commitment-ledger.v2",
                "session_id": self.terms.get("session_id"),
                "action_type": self.action_type,
                "party_agent_ids": self.party_agent_ids,
                "terms_hash": self.terms_hash,
                "source_proposal_id": self.source_proposal_id,
                "source_proposal_hash": self.source_proposal_hash,
                "source_message_id": self.source_message_id,
                "source_message_hash": self.source_message_hash,
                "source_admission_tick": self.source_admission_tick,
                "source_admission_audit_hash": self.source_admission_audit_hash,
            }
        )
        if (
            self.commitment_hash != expected_commitment_hash
            or self.commitment_id != f"commit_{expected_commitment_hash[:20]}"
        ):
            raise ValueError("CL commitment id/hash mismatch")

        allowed_edges = {
            ("proposed", "active"),
            ("proposed", "rejected"),
            ("proposed", "withdrawn"),
            ("proposed", "expired"),
            ("active", "withdrawn"),
            ("active", "expired"),
        }
        previous_status: CommitmentStatus | None = None
        previous_hash: str | None = None
        for index, event in enumerate(self.events, start=1):
            if event.seq != index or event.previous_event_hash != previous_hash:
                raise ValueError("CL event sequence/hash chain mismatch")
            if index == 1:
                if event.status != "proposed":
                    raise ValueError("CL first event must be proposed")
            elif previous_status is None or (previous_status, event.status) not in allowed_edges:
                raise ValueError("CL event state transition is illegal")
            if (event.source_message_id is None) != (event.source_message_hash is None):
                raise ValueError("CL event message id/hash nullability mismatch")
            expected_event_hash = stable_hash(
                {
                    "schema_version": "commitment-ledger.v2",
                    "commitment_id": self.commitment_id,
                    "tick": event.tick,
                    "seq": event.seq,
                    "status": event.status,
                    "actor_agent_id": event.actor_agent_id,
                    "source_message_id": event.source_message_id,
                    "source_message_hash": event.source_message_hash,
                    "previous_event_hash": event.previous_event_hash,
                }
            )
            if event.event_hash != expected_event_hash:
                raise ValueError("CL event_hash mismatch")
            previous_status = event.status
            previous_hash = event.event_hash
        if not self.events or self.status != self.events[-1].status:
            raise ValueError("CL entry status must equal the final event status")
        return self

    def as_claim_tuple(self) -> CommitmentClaimTuple:
        return (
            self.commitment_id,
            self.commitment_hash,
            self.status,
            self.action_type,
            self.party_agent_ids,
            self.terms_hash,
            self.source_proposal_id,
            self.source_proposal_hash,
            self.source_message_id,
            self.source_message_hash,
            self.source_admission_tick,
            self.source_admission_audit_hash,
        )


class CommitmentLedgerSource(ClosedSource):
    schema_version: Literal["commitment-ledger.v2"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str | None = Field(default=None, min_length=1, max_length=160)
    tick: int | None = Field(default=None, ge=1, le=6)
    entries: tuple[CommitmentEntrySource, ...]
    ledger_entry_count: int = Field(ge=0)
    ledger_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        entry_ids = tuple(item.commitment_id for item in self.entries)
        if entry_ids != tuple(sorted(set(entry_ids), key=lambda value: value.encode("utf-8"))):
            raise ValueError("CL entries must be unique and ascending by commitment id")
        if self.ledger_entry_count != len(self.entries):
            raise ValueError("CL ledger_entry_count mismatch")
        for entry in self.entries:
            if entry.terms.get("session_id") != self.session_id:
                raise ValueError("CL entry session binding mismatch")
        expected_hash = stable_hash(
            {
                "schema_version": self.schema_version,
                "run_id": self.run_id,
                "session_id": self.session_id,
                "tick": self.tick,
                "entries": tuple(item.model_dump(mode="json") for item in self.entries),
            }
        )
        if self.ledger_hash != expected_hash:
            raise ValueError("CL ledger_hash mismatch")
        self.extract_claims()
        return self

    def extract_claims(self) -> CLClaims:
        return CLClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            ledger_hash=self.ledger_hash,
            ledger_entry_count=self.ledger_entry_count,
            commitments=tuple(item.as_claim_tuple() for item in self.entries),
        )


ConsistencyRole: TypeAlias = Literal["final", "admission", "projection"]


def _require_closed_keys(
    value: object, expected: set[str], field_name: str
) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{field_name} must have its exact closed field set")


def _synthetic_consistency_time(role: ConsistencyRole, tick: int | None) -> str:
    offset = 0 if role == "final" else 2 * int(tick or 0) - (1 if role == "admission" else 0)
    value = datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return value.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _validate_inner_consistency_payload(
    raw: dict[str, object],
) -> ConsistencyAuditReport:
    _require_closed_keys(
        raw,
        set(ConsistencyAuditReport.model_fields),
        "Consistency inner audit",
    )
    raw_findings = raw.get("findings")
    if not isinstance(raw_findings, tuple):
        raise ValueError("Consistency findings must be a canonical array")
    for finding in raw_findings:
        _require_closed_keys(
            finding,
            set(ConsistencyFinding.model_fields),
            "Consistency finding",
        )
    raw_decisions = raw.get("proposal_decisions")
    if not isinstance(raw_decisions, tuple):
        raise ValueError("Consistency decisions must be a canonical array")
    for decision in raw_decisions:
        _require_closed_keys(
            decision,
            set(AgentActionDecision.model_fields),
            "Consistency decision",
        )
        decision_findings = decision.get("rule_findings")
        if not isinstance(decision_findings, tuple):
            raise ValueError("Consistency decision findings must be a canonical array")
        for finding in decision_findings:
            _require_closed_keys(
                finding,
                set(ConsistencyFinding.model_fields),
                "Consistency decision finding",
            )
    report = ConsistencyAuditReport.model_validate(_restore_lists(raw), strict=True)
    if report.schema_version != "consistency-audit.v2":
        raise ValueError("Consistency inner source must be exact v2")
    for decision in report.proposal_decisions:
        decision_payload = decision.model_dump(mode="json", exclude={"audit_hash"})
        if stable_hash(decision_payload) != decision.audit_hash:
            raise ValueError("Consistency decision audit hash mismatch")
    audit_payload = report.model_dump(
        mode="json", exclude={"run_id", "audit_hash", "created_at"}
    )
    if stable_hash(audit_payload) != report.audit_hash:
        raise ValueError("Consistency inner audit hash mismatch")
    return report


class ConsistencyAuditSource(ClosedSource):
    schema_version: Literal["consistency-audit.v3"]
    run_id: str = Field(min_length=1, max_length=160)
    role: ConsistencyRole
    tick: int | None = Field(default=None, ge=1, le=6)
    evaluator_version: str = Field(min_length=1, max_length=160)
    agent_pack_id: str | None = Field(default=None, min_length=1, max_length=160)
    agent_pack_hash: Digest | None = None
    constraint_context_hash: Digest | None = None
    proposal_ids: tuple[str, ...]
    proposal_hashes: tuple[Digest, ...]
    inner_audit: dict[str, object]
    inner_audit_hash: Digest
    audit_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        if (self.role == "final") != (self.tick is None):
            raise ValueError("Consistency role/tick nullability mismatch")
        context_nulls = (
            self.agent_pack_id is None,
            self.agent_pack_hash is None,
            self.constraint_context_hash is None,
        )
        if any(context_nulls) and not all(context_nulls):
            raise ValueError("Consistency context must be all-null or all-non-null")
        if len(self.proposal_ids) != len(self.proposal_hashes) or tuple(
            sorted(set(self.proposal_ids), key=lambda value: value.encode("utf-8"))
        ) != self.proposal_ids:
            raise ValueError("Consistency proposal vectors must align and be sorted")
        report = _validate_inner_consistency_payload(self.inner_audit)
        expected_inner_run_id = (
            self.run_id
            if self.role == "final"
            else f"{self.run_id}:tick:{self.tick}"
            if self.role == "admission"
            else f"{self.run_id}:projection:{self.tick}"
        )
        if (
            report.run_id != expected_inner_run_id
            or report.evaluator_version != self.evaluator_version
            or report.created_at != _synthetic_consistency_time(self.role, self.tick)
            or report.audit_hash != self.inner_audit_hash
        ):
            raise ValueError("Consistency inner/outer identity binding mismatch")
        expected_hash = stable_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected_hash:
            raise ValueError("Consistency v3 wrapper audit hash mismatch")
        return self

    def inner_report(self) -> ConsistencyAuditReport:
        return _validate_inner_consistency_payload(self.inner_audit)


def build_consistency_audit_source(
    report: ConsistencyAuditReport,
    *,
    run_id: str,
    role: ConsistencyRole,
    tick: int | None,
    evaluator_version: str,
    agent_pack_id: str | None,
    agent_pack_hash: str | None,
    constraint_context_hash: str | None,
    complete_proposals: tuple[AgentActionProposal, ...] = (),
) -> ConsistencyAuditSource:
    """Canonicalize one evaluated report into the closed V2 proof source."""

    report_core = report.model_dump(
        mode="json",
        exclude={"run_id", "audit_hash", "created_at"},
    )
    if stable_hash(report_core) != report.audit_hash:
        raise ValueError("Consistency source report audit hash mismatch")
    if report.evaluator_version != evaluator_version:
        raise ValueError("Consistency source evaluator version mismatch")
    proposals = tuple(
        sorted(complete_proposals, key=lambda item: item.proposal_id.encode("utf-8"))
    )
    proposal_ids = tuple(item.proposal_id for item in proposals)
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("Consistency source proposals must have unique IDs")
    for proposal in proposals:
        if proposal.schema_version != "agent-action-proposal.v1" or proposal.run_id != run_id:
            raise ValueError("Consistency source proposal identity mismatch")
        target_ids = tuple(proposal.target_ids)
        if target_ids != tuple(
            sorted(set(target_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("Consistency source proposal targets are not canonical")
    decisions_by_id: dict[str, AgentActionDecision] = {}
    for item in report.proposal_decisions:
        decision_payload = item.model_dump(mode="json", exclude={"audit_hash"})
        decisions_by_id[item.proposal_id] = AgentActionDecision.model_validate(
            {**decision_payload, "audit_hash": stable_hash(decision_payload)}
        )
    if len(decisions_by_id) != len(report.proposal_decisions) or set(
        decisions_by_id
    ) != set(proposal_ids):
        raise ValueError("Consistency source decisions must equal proposal membership")
    inner_core = {
        **report_core,
        "schema_version": "consistency-audit.v2",
        "evaluator_version": evaluator_version,
        "proposal_decisions": [
            decisions_by_id[proposal_id].model_dump(mode="json")
            for proposal_id in proposal_ids
        ],
    }
    expected_inner_run_id = (
        run_id
        if role == "final"
        else f"{run_id}:tick:{tick}"
        if role == "admission"
        else f"{run_id}:projection:{tick}"
    )
    inner_audit_hash = stable_hash(inner_core)
    inner_report = ConsistencyAuditReport.model_validate(
        {
            **inner_core,
            "run_id": expected_inner_run_id,
            "audit_hash": inner_audit_hash,
            "created_at": _synthetic_consistency_time(role, tick),
        }
    )
    proposal_hashes = tuple(
        stable_hash(item.model_dump(mode="json")) for item in proposals
    )
    outer = {
        "schema_version": "consistency-audit.v3",
        "run_id": run_id,
        "role": role,
        "tick": tick,
        "evaluator_version": evaluator_version,
        "agent_pack_id": agent_pack_id,
        "agent_pack_hash": agent_pack_hash,
        "constraint_context_hash": constraint_context_hash,
        "proposal_ids": proposal_ids,
        "proposal_hashes": proposal_hashes,
        "inner_audit": inner_report.model_dump(mode="json"),
        "inner_audit_hash": inner_audit_hash,
    }
    return ConsistencyAuditSource.model_validate(
        {**outer, "audit_hash": stable_hash(outer)}
    )


class HybridModifierBundleSource(ClosedSource):
    schema_version: Literal["hybrid-modifier-bundle.v2"]
    run_id: str = Field(min_length=1, max_length=160)
    tick: int | None = Field(default=None, ge=1, le=6)
    consistency_audit_hash: Digest
    inner_bundle: dict[str, object]
    inner_bundle_hash: Digest
    accepted_proposal_ids: tuple[str, ...]
    modifiers: tuple[dict[str, object], ...]
    scenario_patch: dict[str, object]
    modifier_tuples: tuple[ModifierReference, ...]
    modifier_count: int = Field(ge=0)
    bundle_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        inner = HybridModifierBundle.model_validate(
            _restore_lists(self.inner_bundle), strict=True
        )
        verify_modifier_bundle(inner)
        if (
            inner.schema_version != "hybrid-modifier-bundle.v1"
            or inner.bundle_hash != self.inner_bundle_hash
            or inner.scenario_patch != _restore_lists(self.scenario_patch)
        ):
            raise ValueError("MB inner bundle/hash/scenario patch mismatch")
        if tuple(
            sorted(set(self.accepted_proposal_ids), key=lambda value: value.encode("utf-8"))
        ) != self.accepted_proposal_ids:
            raise ValueError("MB accepted proposal ids must be unique and ascending")
        outer_modifiers = tuple(
            DeterministicActionModifier.model_validate(
                _restore_lists(item), strict=True
            )
            for item in self.modifiers
        )
        for modifier in outer_modifiers:
            modifier_payload = modifier.model_dump(
                mode="json", exclude={"modifier_hash", "modifier_id"}
            )
            expected_modifier_hash = stable_hash(modifier_payload)
            if (
                expected_modifier_hash != modifier.modifier_hash
                or modifier.modifier_id != f"modifier_{expected_modifier_hash[:16]}"
            ):
                raise ValueError("MB outer modifier hash mismatch")
        inner_by_id = {
            item.proposal_id: item.model_dump(mode="json") for item in inner.modifiers
        }
        outer_by_id = {
            item.proposal_id: item.model_dump(mode="json") for item in outer_modifiers
        }
        if (
            set(inner.accepted_proposal_ids) != set(self.accepted_proposal_ids)
            or len(set(inner.accepted_proposal_ids)) != len(inner.accepted_proposal_ids)
            or inner_by_id != outer_by_id
            or len(inner_by_id) != len(inner.modifiers)
            or len(outer_by_id) != len(outer_modifiers)
        ):
            raise ValueError("MB inner/outer accepted proposal or modifier mapping mismatch")
        expected_modifiers = tuple(
            sorted(
                (
                    ModifierReference(
                        proposal_id=item.proposal_id,
                        modifier_id=item.modifier_id,
                        modifier_hash=item.modifier_hash,
                    )
                    for item in outer_modifiers
                ),
                key=lambda item: (
                    item.proposal_id.encode("utf-8"),
                    item.modifier_id.encode("utf-8"),
                    item.modifier_hash.encode("utf-8"),
                ),
            )
        )
        if (
            self.modifier_tuples != expected_modifiers
            or self.modifier_count != len(expected_modifiers)
        ):
            raise ValueError("MB modifier tuple/count mismatch")
        expected_hash = stable_hash(
            self.model_dump(mode="json", exclude={"bundle_hash"})
        )
        if self.bundle_hash != expected_hash:
            raise ValueError("MB bundle_hash mismatch")
        self.extract_claims()
        return self

    def extract_claims(self) -> MBClaims:
        return MBClaims(
            run_id=self.run_id,
            tick=self.tick,
            bundle_hash=self.bundle_hash,
            inner_bundle_hash=self.inner_bundle_hash,
            consistency_audit_hash=self.consistency_audit_hash,
            accepted_proposal_ids=self.accepted_proposal_ids,
            modifier_tuples=self.modifier_tuples,
            modifier_count=self.modifier_count,
        )


class ProjectionAuditRecordSource(ClosedSource):
    proposal_id: str = Field(min_length=1, max_length=160)
    proposal_hash: Digest
    input_hash: Digest
    decision: Literal["accepted", "rejected", "needs_revision", "not_evaluated"]
    rule_version: str = Field(min_length=1, max_length=160)
    outcome: Literal["accepted", "rejected", "constrained", "expired"]
    rejection_reason: str | None = Field(default=None, min_length=1, max_length=800)
    projection_status: Literal[
        "not_projected", "projected", "constrained", "blocked", "expired"
    ]
    projection_hash: Digest | None = None
    modifier_id: str | None = Field(default=None, min_length=1, max_length=160)
    final_result_hash: Digest

    @model_validator(mode="after")
    def validate_truth_table(self) -> Self:
        expected_status = {
            "rejected": "blocked",
            "constrained": "constrained",
            "expired": "expired",
        }
        if self.outcome == "accepted":
            if self.projection_status == "projected":
                if (
                    self.projection_hash is None
                    or self.modifier_id is None
                    or self.rejection_reason is not None
                ):
                    raise ValueError("PA projected accepted record violates truth table")
            elif self.projection_status == "not_projected":
                if (
                    self.projection_hash is not None
                    or self.modifier_id is not None
                    or self.rejection_reason is not None
                ):
                    raise ValueError("PA audit-only accepted record violates truth table")
            else:
                raise ValueError("PA accepted record has an illegal projection status")
        elif (
            self.projection_status != expected_status[self.outcome]
            or self.projection_hash is not None
            or self.modifier_id is not None
            or self.rejection_reason is None
        ):
            raise ValueError("PA rejected/constrained/expired record violates truth table")
        return self

    def as_claim_tuple(self) -> ProjectionRecordClaimTuple:
        return (
            self.proposal_id,
            self.proposal_hash,
            self.input_hash,
            self.decision,
            self.rule_version,
            self.outcome,
            self.rejection_reason,
            self.projection_status,
            self.projection_hash,
            self.modifier_id,
            self.final_result_hash,
        )


class ProjectionAuditSource(ClosedSource):
    schema_version: Literal[
        "agent-action-projection-audit.v2",
        "negotiation-projection-audit.v2",
    ]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str | None = Field(default=None, min_length=1, max_length=160)
    tick: int | None = Field(default=None, ge=1, le=6)
    projection_mode: Literal["audit_only", "hybrid", "negotiation"]
    consistency_audit_hash: Digest
    modifier_bundle_hash: Digest | None = None
    proposal_ids: tuple[str, ...]
    proposal_hashes: tuple[Digest, ...]
    proposal_count: int = Field(ge=0)
    projected_proposal_ids: tuple[str, ...]
    projected_semantic_key_hashes: tuple[Digest, ...]
    projected_count: int = Field(ge=0)
    modifier_tuples: tuple[ModifierReference, ...]
    modifier_count: int = Field(ge=0)
    records: tuple[ProjectionAuditRecordSource, ...]
    record_count: int = Field(ge=0)
    before_result_hash: Digest
    final_result_hash: Digest
    audit_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        if self.schema_version == "negotiation-projection-audit.v2":
            if (
                self.projection_mode != "negotiation"
                or self.session_id is None
                or self.tick is None
                or self.modifier_bundle_hash is None
            ):
                raise ValueError("negotiation PA coordinates/mode are invalid")
        elif self.session_id is not None or self.tick is not None:
            raise ValueError("non-negotiation PA must have null session and tick")
        elif self.projection_mode == "negotiation":
            raise ValueError("agent-action PA may not use negotiation projection mode")
        if self.projection_mode == "audit_only" and self.modifier_bundle_hash is not None:
            raise ValueError("audit-only PA may not carry a modifier bundle")
        if self.projection_mode == "hybrid" and self.modifier_bundle_hash is None:
            raise ValueError("hybrid PA requires a modifier bundle")
        if not (
            self.proposal_count
            == len(self.proposal_ids)
            == len(self.proposal_hashes)
            == len(self.records)
            == self.record_count
        ):
            raise ValueError("PA proposal/record vectors and counts must align")
        if not (
            self.projected_count
            == len(self.projected_proposal_ids)
            == len(self.projected_semantic_key_hashes)
        ):
            raise ValueError("PA projected vectors and count must align")
        if tuple(item.proposal_id for item in self.records) != self.proposal_ids:
            raise ValueError("PA record order must equal proposal id order")
        if tuple(item.proposal_hash for item in self.records) != self.proposal_hashes:
            raise ValueError("PA record hashes must equal proposal hashes")
        if any(
            item.input_hash != item.proposal_hash
            or item.final_result_hash != self.final_result_hash
            for item in self.records
        ):
            raise ValueError("PA record input/final hashes are invalid")
        projected_records = tuple(
            item for item in self.records if item.projection_status == "projected"
        )
        if tuple(item.proposal_id for item in projected_records) != self.projected_proposal_ids:
            raise ValueError("PA projected records and projected ids mismatch")
        modifier_by_proposal = {
            item.proposal_id: item for item in self.modifier_tuples
        }
        if len(modifier_by_proposal) != len(self.modifier_tuples):
            raise ValueError("PA modifier proposal ids must be unique")
        for record in projected_records:
            modifier = modifier_by_proposal.get(record.proposal_id)
            if (
                modifier is None
                or record.modifier_id != modifier.modifier_id
                or record.projection_hash != modifier.modifier_hash
            ):
                raise ValueError("PA projected record/modifier binding mismatch")
        claims = self.extract_claims()
        if claims.modifier_count != len(self.modifier_tuples):
            raise ValueError("PA modifier count mismatch")
        expected_hash = stable_hash(
            self.model_dump(mode="json", exclude={"audit_hash"})
        )
        if self.audit_hash != expected_hash:
            raise ValueError("PA audit_hash mismatch")
        return self

    def extract_claims(self) -> PAClaims:
        return PAClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            projection_mode=self.projection_mode,
            audit_hash=self.audit_hash,
            consistency_audit_hash=self.consistency_audit_hash,
            modifier_bundle_hash=self.modifier_bundle_hash,
            proposal_ids=self.proposal_ids,
            proposal_hashes=self.proposal_hashes,
            proposal_count=self.proposal_count,
            record_input_hashes=tuple(item.input_hash for item in self.records),
            record_claim_tuples=tuple(item.as_claim_tuple() for item in self.records),
            projected_proposal_ids=self.projected_proposal_ids,
            projected_semantic_key_hashes=self.projected_semantic_key_hashes,
            projected_count=self.projected_count,
            modifier_tuples=self.modifier_tuples,
            modifier_count=self.modifier_count,
            record_count=self.record_count,
            before_result_hash=self.before_result_hash,
            final_result_hash=self.final_result_hash,
        )


def build_audit_only_projection_source(
    *,
    run_id: str,
    consistency_audit_hash: str,
    final_result_hash: str,
    proposals: tuple[AgentActionProposal, ...],
    decisions: tuple[AgentActionDecision, ...],
) -> ProjectionAuditSource:
    """Build a closed V2 PA proving that Agent output changed no numeric state."""

    ordered = tuple(
        sorted(proposals, key=lambda item: item.proposal_id.encode("utf-8"))
    )
    proposal_ids = tuple(item.proposal_id for item in ordered)
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("audit-only PA proposals must have unique IDs")
    decisions_by_id = {item.proposal_id: item for item in decisions}
    if len(decisions_by_id) != len(decisions) or set(decisions_by_id) != set(
        proposal_ids
    ):
        raise ValueError("audit-only PA decisions must equal proposal membership")

    proposal_hashes = tuple(
        stable_hash(item.model_dump(mode="json")) for item in ordered
    )
    records: list[dict[str, object]] = []
    status_by_outcome = {
        "rejected": "blocked",
        "constrained": "constrained",
        "expired": "expired",
    }
    for index, proposal in enumerate(ordered):
        if proposal.schema_version != "agent-action-proposal.v1" or proposal.run_id != run_id:
            raise ValueError("audit-only PA proposal identity mismatch")
        target_ids = tuple(proposal.target_ids)
        if target_ids != tuple(
            sorted(set(target_ids), key=lambda value: value.encode("utf-8"))
        ):
            raise ValueError("audit-only PA proposal targets are not canonical")
        decision = decisions_by_id[proposal.proposal_id]
        proposal_hash = proposal_hashes[index]
        if decision.input_hash != proposal_hash:
            raise ValueError("audit-only PA decision input hash mismatch")
        projection_status = (
            "not_projected"
            if decision.outcome == "accepted"
            else status_by_outcome[decision.outcome]
        )
        records.append(
            {
                "proposal_id": proposal.proposal_id,
                "proposal_hash": proposal_hash,
                "input_hash": proposal_hash,
                "decision": decision.decision,
                "rule_version": decision.rule_version,
                "outcome": decision.outcome,
                "rejection_reason": decision.rejection_reason,
                "projection_status": projection_status,
                "projection_hash": None,
                "modifier_id": None,
                "final_result_hash": final_result_hash,
            }
        )

    payload = {
        "schema_version": "agent-action-projection-audit.v2",
        "run_id": run_id,
        "session_id": None,
        "tick": None,
        "projection_mode": "audit_only",
        "consistency_audit_hash": consistency_audit_hash,
        "modifier_bundle_hash": None,
        "proposal_ids": proposal_ids,
        "proposal_hashes": proposal_hashes,
        "proposal_count": len(ordered),
        "projected_proposal_ids": (),
        "projected_semantic_key_hashes": (),
        "projected_count": 0,
        "modifier_tuples": (),
        "modifier_count": 0,
        "records": tuple(records),
        "record_count": len(records),
        "before_result_hash": final_result_hash,
        "final_result_hash": final_result_hash,
    }
    return ProjectionAuditSource.model_validate(
        {**payload, "audit_hash": stable_hash(payload)}
    )


class ToneDeltasSource(ClosedSource):
    firm: float
    informational: float
    stabilizing: float


class DiffusionApplicationSource(ClosedSource):
    proposal_id: str = Field(min_length=1, max_length=160)
    target_country: str = Field(min_length=1, max_length=160)
    receiver_country: str = Field(min_length=1, max_length=160)
    tone: Tone
    audience: Audience
    base_delta: float
    propagation_multiplier: float
    alliance_multiplier: float
    effective_multiplier: float
    applied_delta: float
    cumulative_delta: float


class NarrativeDiffusionCoreSource(ClosedSource):
    schema_version: Literal["narrative-diffusion.v1"]
    seed: int
    tone_deltas: ToneDeltasSource
    country_deltas: dict[str, float]
    applications: tuple[DiffusionApplicationSource, ...]


class DiffusionRequestSource(ClosedSource):
    scenario_key: str = Field(min_length=1, max_length=160)
    duration_days: int = Field(ge=1, le=365)
    intensity: float = Field(ge=0, le=1)
    propagation: float = Field(ge=0, le=1)
    target_countries: tuple[str, ...]
    target_chains: tuple[str, ...]
    policy_actions: tuple[str, ...]
    country_overrides: dict[str, dict[str, float]]
    chain_overrides: dict[str, dict[str, float]]
    seed: int


class NarrativeDiffusionSource(ClosedSource):
    schema_version: Literal["narrative-diffusion.v2"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1, le=6)
    attempted: bool
    input_proposal_ids: tuple[str, ...]
    input_proposal_hashes: tuple[Digest, ...]
    core_audit: NarrativeDiffusionCoreSource
    narrative_diffusion_audit_hash: Digest
    diffusion_request: DiffusionRequestSource
    diffusion_request_hash: Digest
    before_result_hash: Digest
    after_result_hash: Digest
    tone_delta_tuples: tuple[ToneDeltaTuple, ...]
    country_delta_tuples: tuple[CountryDeltaTuple, ...]
    application_tuples: tuple[DiffusionApplicationTuple, ...]
    application_count: int = Field(ge=0)
    diffusion_evidence_hash: Digest

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        if self.core_audit.seed != self.diffusion_request.seed:
            raise ValueError("ND core/request seed mismatch")
        if len(set(self.input_proposal_ids)) != len(self.input_proposal_ids) or tuple(
            sorted(self.input_proposal_ids, key=lambda value: value.encode("utf-8"))
        ) != self.input_proposal_ids:
            raise ValueError("ND input proposal ids must be unique and ascending")
        if len(self.input_proposal_ids) != len(self.input_proposal_hashes):
            raise ValueError("ND input proposal id/hash vectors must align")
        if self.attempted != bool(self.input_proposal_ids):
            raise ValueError("ND attempted must equal the nonempty input predicate")

        core_payload = self.core_audit.model_dump(mode="json")
        if self.narrative_diffusion_audit_hash != stable_hash(core_payload):
            raise ValueError("ND narrative diffusion audit hash mismatch")
        request_payload = self.diffusion_request.model_dump(mode="json")
        expected_request_hash = stable_hash(
            {
                "schema_version": "narrative-diffusion.v2",
                "diffusion_request": request_payload,
            }
        )
        if self.diffusion_request_hash != expected_request_hash:
            raise ValueError("ND diffusion request hash mismatch")

        expected_tones: tuple[ToneDeltaTuple, ...] = (
            ("firm", _to_units(self.core_audit.tone_deltas.firm, "firm tone")),
            (
                "informational",
                _to_units(
                    self.core_audit.tone_deltas.informational,
                    "informational tone",
                ),
            ),
            (
                "stabilizing",
                _to_units(self.core_audit.tone_deltas.stabilizing, "stabilizing tone"),
            ),
        )
        if expected_tones != (
            ("firm", 30000),
            ("informational", -10000),
            ("stabilizing", -40000),
        ) or self.tone_delta_tuples != expected_tones:
            raise ValueError("ND fixed tone tuple mismatch")

        expected_countries: tuple[CountryDeltaTuple, ...] = tuple(
            (
                country_id,
                _to_units(delta, f"country delta {country_id}"),
            )
            for country_id, delta in sorted(
                self.core_audit.country_deltas.items(),
                key=lambda item: item[0].encode("utf-8"),
            )
        )
        if self.country_delta_tuples != expected_countries:
            raise ValueError("ND country fixed-point tuple mismatch")

        application_claims: list[DiffusionApplicationTuple] = []
        cumulative_by_receiver: dict[str, int] = {}
        country_totals: dict[str, int] = {}
        input_ids = set(self.input_proposal_ids)
        tone_units = dict(expected_tones)
        for application in self.core_audit.applications:
            if application.proposal_id not in input_ids:
                raise ValueError("ND application proposal is not an authenticated input")
            complete_application = application.model_dump(mode="json")
            base = _to_units(application.base_delta, "application base delta")
            propagation = _to_units(
                application.propagation_multiplier,
                "application propagation multiplier",
            )
            alliance = _to_units(
                application.alliance_multiplier,
                "application alliance multiplier",
            )
            effective = _to_units(
                application.effective_multiplier,
                "application effective multiplier",
            )
            applied = _to_units(application.applied_delta, "application applied delta")
            cumulative = _to_units(
                application.cumulative_delta,
                "application cumulative delta",
            )
            expected_effective = min(
                FIXED_POINT_SCALE,
                _mul_units(propagation, alliance, "application effective multiplier"),
            )
            if base != tone_units[application.tone] or effective != expected_effective:
                raise ValueError("ND application base/effective arithmetic mismatch")
            candidate = _mul_units(base, effective, "application candidate delta")
            prior = cumulative_by_receiver.get(
                application.receiver_country,
                _checked_int64(cumulative - applied, "application initial cumulative"),
            )
            unclamped = _checked_int64(prior + candidate, "application cumulative update")
            expected_cumulative = max(-80000, min(80000, unclamped))
            expected_applied = _checked_int64(
                expected_cumulative - prior,
                "application applied update",
            )
            if cumulative != expected_cumulative or applied != expected_applied:
                raise ValueError("ND application cumulative arithmetic mismatch")
            cumulative_by_receiver[application.receiver_country] = cumulative
            country_totals[application.receiver_country] = _checked_int64(
                country_totals.get(application.receiver_country, 0) + applied,
                "ND country total",
            )
            application_hash = stable_hash(
                {
                    "schema_version": "narrative-diffusion.v2",
                    "application": complete_application,
                }
            )
            application_claims.append(
                (
                    application.proposal_id,
                    application.target_country,
                    application.receiver_country,
                    application.tone,
                    application.audience,
                    base,
                    propagation,
                    alliance,
                    effective,
                    applied,
                    cumulative,
                    application_hash,
                )
            )

        expected_applications = tuple(
            sorted(
                application_claims,
                key=lambda item: (
                    item[0].encode("utf-8"),
                    item[1].encode("utf-8"),
                    item[2].encode("utf-8"),
                    item[3].encode("utf-8"),
                    item[4].encode("utf-8"),
                    item[11],
                ),
            )
        )
        if (
            self.application_count != len(expected_applications)
            or self.application_tuples != expected_applications
        ):
            raise ValueError("ND application tuple/count mismatch")
        if dict(expected_countries) != country_totals:
            raise ValueError("ND country totals do not equal application deltas")
        if not self.attempted and (
            self.country_delta_tuples
            or self.application_tuples
            or self.before_result_hash != self.after_result_hash
        ):
            raise ValueError("ND empty input must be a complete numeric no-op")

        expected_evidence_hash = stable_hash(
            self.model_dump(mode="json", exclude={"diffusion_evidence_hash"})
        )
        if self.diffusion_evidence_hash != expected_evidence_hash:
            raise ValueError("ND diffusion evidence hash mismatch")
        self.extract_claims()
        return self

    def extract_claims(self) -> NDClaims:
        return NDClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            tick=self.tick,
            attempted=self.attempted,
            input_proposal_ids=self.input_proposal_ids,
            input_proposal_hashes=self.input_proposal_hashes,
            narrative_diffusion_audit_hash=self.narrative_diffusion_audit_hash,
            diffusion_request_hash=self.diffusion_request_hash,
            before_result_hash=self.before_result_hash,
            after_result_hash=self.after_result_hash,
            tone_delta_tuples=self.tone_delta_tuples,
            country_delta_tuples=self.country_delta_tuples,
            application_tuples=self.application_tuples,
            application_count=self.application_count,
            diffusion_evidence_hash=self.diffusion_evidence_hash,
        )


class HybridReplaySource(ClosedSource):
    """Complete provider-free hybrid-replay-record.v2 source."""

    schema_version: Literal["hybrid-replay-record.v2"]
    run_id: str = Field(min_length=1, max_length=160)
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
    accepted_proposal_ids: tuple[str, ...]

    @field_validator("provider_calls_required", mode="before")
    @classmethod
    def require_exact_zero_provider_calls(cls, value: object) -> object:
        if type(value) is not int or value != 0:
            raise ValueError("HR provider_calls_required must be the integer 0")
        return value

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        self.extract_claims()
        expected_replay_hash = stable_hash(
            self.model_dump(mode="json", exclude={"replay_hash"})
        )
        if self.replay_hash != expected_replay_hash:
            raise ValueError("HR replay_hash mismatch")
        return self

    def extract_claims(self) -> HRClaims:
        return HRClaims(
            run_id=self.run_id,
            engine_mode=self.engine_mode,
            replay_source_kind=self.replay_source_kind,
            provider_calls_required=self.provider_calls_required,
            replay_hash=self.replay_hash,
            baseline_result_hash=self.baseline_result_hash,
            final_result_hash=self.final_result_hash,
            full_source_run_hash=self.full_source_run_hash,
            proposal_batch_hash=self.proposal_batch_hash,
            consistency_audit_hash=self.consistency_audit_hash,
            modifier_bundle_hash=self.modifier_bundle_hash,
            projection_audit_hash=self.projection_audit_hash,
            ledger_hash=self.ledger_hash,
            accepted_proposal_ids=self.accepted_proposal_ids,
        )


class NegotiationReplaySource(ClosedSource):
    """Complete provider-free negotiation-replay.v2 source."""

    schema_version: Literal["negotiation-replay.v2"]
    run_id: str = Field(min_length=1, max_length=160)
    session_id: str = Field(min_length=1, max_length=160)
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
    provider_calls_required: Literal[0]
    replay_hash: Digest

    @field_validator("provider_calls_required", mode="before")
    @classmethod
    def require_exact_zero_provider_calls(cls, value: object) -> object:
        if type(value) is not int or value != 0:
            raise ValueError("NR provider_calls_required must be the integer 0")
        return value

    @model_validator(mode="after")
    def validate_complete_source(self) -> Self:
        self.extract_claims()
        expected_replay_hash = stable_hash(
            self.model_dump(mode="json", exclude={"replay_hash"})
        )
        if self.replay_hash != expected_replay_hash:
            raise ValueError("NR replay_hash mismatch")
        return self

    def extract_claims(self) -> NRClaims:
        return NRClaims(
            run_id=self.run_id,
            session_id=self.session_id,
            replay_hash=self.replay_hash,
            baseline_result_hash=self.baseline_result_hash,
            final_result_hash=self.final_result_hash,
            round_hashes=self.round_hashes,
            proposal_batch_hashes=self.proposal_batch_hashes,
            admission_audit_hashes=self.admission_audit_hashes,
            ledger_hashes=self.ledger_hashes,
            eligibility_hashes=self.eligibility_hashes,
            projection_consistency_hashes=self.projection_consistency_hashes,
            modifier_bundle_hashes=self.modifier_bundle_hashes,
            diffusion_evidence_hashes=self.diffusion_evidence_hashes,
            projection_audit_hashes=self.projection_audit_hashes,
            message_chain_head=self.message_chain_head,
            provider_calls_required=self.provider_calls_required,
        )


def extract_ar_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
) -> ARClaims:
    """Verify a complete runtime source and derive immutable AR claims."""

    source = AgentRuntimeResultSource.model_validate(dict(payload))
    if source.run_id != run_id:
        raise ValueError("AR source run_id mismatch")
    proposals, invocations = _validated_agent_runtime_vectors(source)
    proposal_pairs = tuple(
        sorted(
            (
                (item.proposal_id, stable_hash(item.model_dump(mode="json")))
                for item in proposals
            ),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    invocation_pairs = tuple(
        sorted(
            (
                (item.invocation_id, stable_hash(item.model_dump(mode="json")))
                for item in invocations
            ),
            key=lambda item: item[0].encode("utf-8"),
        )
    )
    return ARClaims(
        run_id=source.run_id,
        runtime_hash=source.runtime_hash,
        proposal_ids=tuple(item[0] for item in proposal_pairs),
        proposal_hashes=tuple(item[1] for item in proposal_pairs),
        proposal_count=len(proposal_pairs),
        invocation_ids=tuple(item[0] for item in invocation_pairs),
        invocation_hashes=tuple(item[1] for item in invocation_pairs),
        invocation_count=len(invocation_pairs),
    )


def extract_pb_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    expected_runtime_hash: str | None = None,
    mock_batch_payload: Mapping[str, object] | None = None,
) -> PBClaims:
    """Verify a complete proposal batch and its independently verified source."""

    source = KernelProposalBatchSource.model_validate(dict(payload))
    if source.run_id != run_id:
        raise ValueError("PB source run_id mismatch")
    if source.source_kind == "agent_runtime":
        if (
            expected_runtime_hash is None
            or mock_batch_payload is not None
            or source.source_runtime_hash != expected_runtime_hash
        ):
            raise ValueError("PB agent_runtime source binding mismatch")
    else:
        if mock_batch_payload is None or expected_runtime_hash is not None:
            raise ValueError("PB mock_batch source binding mismatch")
        mock_source = MockAgentBatchSource.model_validate(dict(mock_batch_payload))
        _, mock_proposals = _validated_mock_agent_batch_proposals(
            mock_source,
            run_id=run_id,
        )
        _, pb_proposals = _validated_kernel_proposal_batch_vectors(source)
        mock_by_id = {item["proposal_id"]: item for item in mock_proposals}
        pb_by_id = {item["proposal_id"]: item for item in pb_proposals}
        if len(mock_by_id) != len(mock_proposals) or mock_by_id != pb_by_id:
            raise ValueError("PB proposals drift from complete mock batch")
        if source.source_mock_batch_hash != mock_agent_batch_source_hash(mock_source):
            raise ValueError("PB mock_batch source binding mismatch")
    return source.extract_claims()


def extract_rr_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str,
    tick: int,
    expected_first_seq: int,
    expected_previous_hash: str | None,
) -> RRClaims:
    """Verify a complete round and bind its first message to the prior RR."""

    if type(expected_first_seq) is not int or expected_first_seq < 1:
        raise ValueError("RR expected_first_seq must be a strict positive integer")
    if expected_previous_hash is not None and (
        not isinstance(expected_previous_hash, str)
        or len(expected_previous_hash) != 64
        or any(
            character not in "0123456789abcdef"
            for character in expected_previous_hash
        )
    ):
        raise ValueError("RR expected_previous_hash must be a lowercase SHA-256 digest")
    if (expected_first_seq == 1) != (expected_previous_hash is None):
        raise ValueError("RR authoritative message boundary is inconsistent")
    if type(tick) is not int or tick < 1 or tick > 6:
        raise ValueError("RR authoritative tick must be a strict integer in 1..6")
    if tick == 1 and (
        expected_first_seq != 1 or expected_previous_hash is not None
    ):
        raise ValueError("RR first tick must begin at the message-chain origin")

    source = NegotiationRoundSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.session_id != session_id
        or source.tick != tick
    ):
        raise ValueError("RR authoritative coordinate binding mismatch")

    input_payload, messages = _validated_round_input(source)
    output_payload = _validated_round_output(source)
    if messages and (
        messages[0].seq != expected_first_seq
        or messages[0].previous_hash != expected_previous_hash
    ):
        raise ValueError("RR first message does not extend the authenticated chain")

    return RRClaims.model_validate(
        {
            "run_id": source.run_id,
            "session_id": source.session_id,
            "round_id": source.round_id,
            "tick": source.tick,
            "input_hash": source.input_hash,
            "output_hash": source.output_hash,
            "round_hash": source.round_hash,
            "before_result_hash": input_payload["before_result_hash"],
            "after_result_hash": output_payload["after_result_hash"],
            "message_tuples": input_payload["message_tuples"],
            "messages_hash": input_payload["messages_hash"],
            "message_count": input_payload["message_count"],
            "proposal_ids": input_payload["proposal_ids"],
            "accepted_proposal_ids": input_payload["accepted_proposal_ids"],
            "proposal_batch_hash": input_payload["proposal_batch_hash"],
            "admission_audit_hash": input_payload["admission_audit_hash"],
            "ledger_hash": input_payload["ledger_hash"],
            "eligibility_hash": input_payload["eligibility_hash"],
            "eligible_proposal_ids": input_payload["eligible_proposal_ids"],
            "projection_consistency_hash": output_payload[
                "projection_consistency_hash"
            ],
            "modifier_bundle_hash": output_payload["modifier_bundle_hash"],
            "diffusion_evidence_hash": output_payload["diffusion_evidence_hash"],
            "projection_audit_hash": output_payload["projection_audit_hash"],
            "no_projection_reason": output_payload["no_projection_reason"],
        },
        strict=True,
    )


def extract_np_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str,
    tick: int,
    messages_hash: str,
    admission_audit_hash: str,
    ledger_hash: str,
) -> NPClaims:
    source = NegotiationProposalBatchSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.session_id != session_id
        or source.tick != tick
        or source.source_hashes
        != (messages_hash, admission_audit_hash, ledger_hash)
    ):
        raise ValueError("NP authoritative coordinate/source binding mismatch")
    return source.extract_claims()


def extract_consistency_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    role: ConsistencyRole,
    tick: int | None,
    evaluator_version: str,
    agent_pack_id: str | None,
    agent_pack_hash: str | None,
    constraint_context_hash: str | None,
    complete_proposals: tuple[Mapping[str, object], ...],
) -> FCClaims | ACClaims | PCClaims:
    source = ConsistencyAuditSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.role != role
        or source.tick != tick
        or source.evaluator_version != evaluator_version
        or source.agent_pack_id != agent_pack_id
        or source.agent_pack_hash != agent_pack_hash
        or source.constraint_context_hash != constraint_context_hash
    ):
        raise ValueError("Consistency authoritative coordinate/context binding mismatch")
    proposals = tuple(
        AgentActionProposal.model_validate(_restore_lists(dict(item)), strict=True)
        for item in complete_proposals
    )
    for proposal in proposals:
        target_ids = tuple(proposal.target_ids)
        if (
            proposal.schema_version != "agent-action-proposal.v1"
            or proposal.run_id != run_id
            or len(set(target_ids)) != len(target_ids)
            or target_ids
            != tuple(sorted(target_ids, key=lambda value: value.encode("utf-8")))
        ):
            raise ValueError("Consistency complete proposal coordinate/order mismatch")
    proposal_ids = tuple(item.proposal_id for item in proposals)
    proposal_hashes = tuple(
        stable_hash(item.model_dump(mode="json")) for item in proposals
    )
    if source.proposal_ids != proposal_ids or source.proposal_hashes != proposal_hashes:
        raise ValueError("Consistency complete proposal vector binding mismatch")
    report = source.inner_report()
    if tuple(item.proposal_id for item in report.proposal_decisions) != proposal_ids:
        raise ValueError("Consistency inner decision order must equal proposal order")
    decisions_by_id = {item.proposal_id: item for item in report.proposal_decisions}
    if len(decisions_by_id) != len(report.proposal_decisions) or set(
        decisions_by_id
    ) != set(proposal_ids):
        raise ValueError("Consistency inner decision/proposal membership mismatch")
    decision_tuples: tuple[ConsistencyDecisionClaimTuple, ...] = tuple(
        (
            proposal_id,
            proposal_hashes[index],
            decisions_by_id[proposal_id].decision,
            decisions_by_id[proposal_id].input_hash,
            decisions_by_id[proposal_id].rule_version,
            decisions_by_id[proposal_id].outcome,
            decisions_by_id[proposal_id].rejection_reason,
            decisions_by_id[proposal_id].projection_status,
            decisions_by_id[proposal_id].projection_hash,
        )
        for index, proposal_id in enumerate(proposal_ids)
    )
    accepted_ids = tuple(item[0] for item in decision_tuples if item[2] == "accepted")
    if role == "final":
        return FCClaims.model_validate(
            {
                "run_id": run_id,
                "evaluator_version": evaluator_version,
                "agent_pack_id": agent_pack_id,
                "agent_pack_hash": agent_pack_hash,
                "constraint_context_hash": constraint_context_hash,
                "inner_audit_hash": source.inner_audit_hash,
                "deterministic_result_hash": report.deterministic_result_hash,
                "audit_hash": source.audit_hash,
                "proposal_ids": proposal_ids,
                "proposal_hashes": proposal_hashes,
                "accepted_proposal_ids": accepted_ids,
                "decision_tuples": decision_tuples,
                "decision_count": len(decision_tuples),
            },
            strict=True,
        )
    if agent_pack_id is None or agent_pack_hash is None or constraint_context_hash is None:
        raise ValueError("admission/projection Consistency requires non-null context")
    if tick is None:
        raise ValueError("admission/projection Consistency requires a tick")
    if role == "admission":
        return ACClaims.model_validate(
            {
                "run_id": run_id,
                "evaluator_version": evaluator_version,
                "agent_pack_id": agent_pack_id,
                "agent_pack_hash": agent_pack_hash,
                "constraint_context_hash": constraint_context_hash,
                "inner_audit_hash": source.inner_audit_hash,
                "deterministic_result_hash": report.deterministic_result_hash,
                "role": "admission",
                "tick": tick,
                "audit_hash": source.audit_hash,
                "proposal_ids": proposal_ids,
                "proposal_hashes": proposal_hashes,
                "accepted_proposal_ids": accepted_ids,
                "decision_tuples": decision_tuples,
                "decision_count": len(decision_tuples),
            },
            strict=True,
        )
    return PCClaims.model_validate(
        {
            "run_id": run_id,
            "evaluator_version": evaluator_version,
            "agent_pack_id": agent_pack_id,
            "agent_pack_hash": agent_pack_hash,
            "constraint_context_hash": constraint_context_hash,
            "inner_audit_hash": source.inner_audit_hash,
            "deterministic_result_hash": report.deterministic_result_hash,
            "role": "projection",
            "tick": tick,
            "audit_hash": source.audit_hash,
            "candidate_proposal_ids": proposal_ids,
            "proposal_hashes": proposal_hashes,
            "accepted_proposal_ids": accepted_ids,
            "decision_tuples": decision_tuples,
            "decision_count": len(decision_tuples),
        },
        strict=True,
    )


def extract_el_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str,
    tick: int,
    proposal_claims: NPClaims,
) -> ELClaims:
    source = NegotiationEligibilitySource.model_validate(dict(payload))
    claims = source.extract_claims()
    if (
        claims.run_id != run_id
        or claims.session_id != session_id
        or claims.tick != tick
        or tuple(item[0] for item in claims.decision_tuples)
        != proposal_claims.proposal_claim_tuples
    ):
        raise ValueError("EL authoritative coordinate/NP binding mismatch")
    return claims


def extract_cl_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str | None,
    tick: int | None,
) -> CLClaims:
    source = CommitmentLedgerSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.session_id != session_id
        or source.tick != tick
    ):
        raise ValueError("CL authoritative coordinate binding mismatch")
    if (session_id is None) != (tick is None):
        raise ValueError("CL hybrid and negotiation coordinates may not be mixed")
    return source.extract_claims()


def extract_mb_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    tick: int | None,
    consistency_audit_hash: str,
) -> MBClaims:
    source = HybridModifierBundleSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.tick != tick
        or source.consistency_audit_hash != consistency_audit_hash
    ):
        raise ValueError("MB authoritative coordinate/Consistency binding mismatch")
    return source.extract_claims()


def extract_pa_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str | None,
    tick: int | None,
    projection_mode: Literal["audit_only", "hybrid", "negotiation"],
    consistency_audit_hash: str,
    complete_proposals: tuple[Mapping[str, object], ...],
    modifier_claims: MBClaims | None,
) -> PAClaims:
    source = ProjectionAuditSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.session_id != session_id
        or source.tick != tick
        or source.projection_mode != projection_mode
        or source.consistency_audit_hash != consistency_audit_hash
    ):
        raise ValueError("PA authoritative coordinate/Consistency binding mismatch")
    proposals = tuple(
        AgentActionProposal.model_validate(_restore_lists(dict(item)), strict=True)
        for item in complete_proposals
    )
    for proposal in proposals:
        target_ids = tuple(proposal.target_ids)
        if (
            proposal.schema_version != "agent-action-proposal.v1"
            or proposal.run_id != run_id
            or len(set(target_ids)) != len(target_ids)
            or target_ids
            != tuple(sorted(target_ids, key=lambda value: value.encode("utf-8")))
        ):
            raise ValueError("PA complete proposal coordinate/order mismatch")
    proposal_ids = tuple(item.proposal_id for item in proposals)
    proposal_hashes = tuple(
        stable_hash(item.model_dump(mode="json")) for item in proposals
    )
    if source.proposal_ids != proposal_ids or source.proposal_hashes != proposal_hashes:
        raise ValueError("PA complete proposal vector binding mismatch")
    proposal_by_id = {item.proposal_id: item for item in proposals}
    if len(proposal_by_id) != len(proposals):
        raise ValueError("PA complete proposal ids must be unique")
    expected_semantics = tuple(
        stable_hash(
            {
                "actor_id": proposal_by_id[proposal_id].actor_id,
                "action_type": proposal_by_id[proposal_id].action_type,
                "target_ids": tuple(proposal_by_id[proposal_id].target_ids),
                "parameters": proposal_by_id[proposal_id].parameters,
            }
        )
        for proposal_id in source.projected_proposal_ids
    )
    if source.projected_semantic_key_hashes != expected_semantics:
        raise ValueError("PA projected semantic hash mismatch")
    if modifier_claims is None:
        if source.modifier_bundle_hash is not None or source.modifier_tuples:
            raise ValueError("PA without MB claims may not carry modifier evidence")
    elif (
        source.modifier_bundle_hash != modifier_claims.bundle_hash
        or source.modifier_tuples != modifier_claims.modifier_tuples
        or source.projected_proposal_ids != modifier_claims.accepted_proposal_ids
    ):
        raise ValueError("PA/MB claims binding mismatch")
    return source.extract_claims()


def extract_nd_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str,
    tick: int,
    effective_seed: int,
) -> NDClaims:
    source = NarrativeDiffusionSource.model_validate(dict(payload))
    if (
        source.run_id != run_id
        or source.session_id != session_id
        or source.tick != tick
        or source.core_audit.seed != effective_seed
        or source.diffusion_request.seed != effective_seed
    ):
        raise ValueError("ND authoritative coordinate/seed binding mismatch")
    return source.extract_claims()


def extract_hr_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    engine_mode: Literal["hybrid", "hybrid_recorded"],
) -> HRClaims:
    """Verify the complete hybrid replay manifest and authoritative mode."""

    source = HybridReplaySource.model_validate(dict(payload))
    if source.run_id != run_id or source.engine_mode != engine_mode:
        raise ValueError("HR authoritative run/mode binding mismatch")
    return source.extract_claims()


def extract_nr_claims(
    payload: Mapping[str, object],
    *,
    run_id: str,
    session_id: str,
) -> NRClaims:
    """Verify the complete negotiation replay manifest and coordinates."""

    source = NegotiationReplaySource.model_validate(dict(payload))
    if source.run_id != run_id or source.session_id != session_id:
        raise ValueError("NR authoritative run/session binding mismatch")
    return source.extract_claims()
