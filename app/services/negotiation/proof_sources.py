"""Canonical negotiation source verification and claims-only extraction.

The functions in this module are Run Control adapters.  They accept payloads
only after the generic Artifact layer has compared the outer byte SHA-256,
validate the complete closed source object and its content hashes, and return
the reduced immutable claims admitted by the pure Simulation Kernel.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Annotated, Literal, Self, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency.hashing import stable_hash
from app.services.simulation_kernel.mode_contracts import (
    CLClaims,
    ELClaims,
    NDClaims,
    NPClaims,
    CommitmentClaimTuple,
    CountryDeltaTuple,
    DiffusionApplicationTuple,
    EligibilityDecisionTuple,
    NegotiationProposalSourceTuple,
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
