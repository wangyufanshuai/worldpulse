"""Provider-free materialization of persisted negotiation facts into V2 proof sources.

The boundary in this module deliberately ignores stored V1 decisions, modifier
bundles, diffusion outputs, and result payloads as authorities.  It authenticates
the persisted provider transcript, reruns every governed deterministic stage,
and emits complete closed sources without writing lifecycle state.
"""

from __future__ import annotations

from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass, field
from typing import TypeAlias

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.core.negotiation_models import (
    AgentPackManifest,
    NarrativeDiffusionAudit,
    NegotiationCommitment,
    NegotiationMessage,
    NegotiationRound,
    NegotiationSession,
)
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import CONSISTENCY_EVALUATOR_VERSION
from app.services.hybrid_simulation.adapter import build_modifier_bundle
from app.services.negotiation.agent_pack import build_agent_pack, scheduled_profiles
from app.services.negotiation.diffusion import TONE_DELTAS, apply_narrative_diffusion
from app.services.negotiation.ports import NegotiationReadApplicationPort
from app.services.simulation_runtime import (
    SimulationRuntimeApplicationPort,
    simulation_runtime_service,
)

from .proof_sources import (
    ACTION_CLASS_BY_TYPE,
    CommitmentLedgerSource,
    ConsistencyAuditSource,
    HybridModifierBundleSource,
    NarrativeDiffusionSource,
    NegotiationEligibilitySource,
    NegotiationProposalBatchSource,
    NegotiationReplaySource,
    NegotiationRoundSource,
    ProjectionAuditSource,
    build_consistency_audit_source,
    build_hybrid_modifier_bundle_source,
    build_narrative_diffusion_source,
    build_negotiation_projection_source,
    build_negotiation_replay_source,
)


TICK_PROGRESS = (0.0, 0.10, 0.23, 0.47, 0.70, 1.0)
BILATERAL_ACTIONS = {
    "alliance_request",
    "deescalation_offer",
    "humanitarian_offer",
}
RESPONSE_STATUS = {
    "accept": "active",
    "reject": "rejected",
    "withdrawal": "withdrawn",
    "counteroffer": "rejected",
}


@dataclass(frozen=True)
class NegotiationTickMaterialization:
    """All closed V2 sources produced for one negotiation tick."""

    tick: int
    round: NegotiationRoundSource
    proposals: NegotiationProposalBatchSource
    admission: ConsistencyAuditSource
    ledger: CommitmentLedgerSource
    eligibility: NegotiationEligibilitySource
    projection_consistency: ConsistencyAuditSource | None
    modifier_bundle: HybridModifierBundleSource | None
    diffusion: NarrativeDiffusionSource
    projection_audit: ProjectionAuditSource | None

    @property
    def projected(self) -> bool:
        return self.projection_consistency is not None


NegotiationProofSource: TypeAlias = (
    NegotiationRoundSource
    | NegotiationProposalBatchSource
    | ConsistencyAuditSource
    | CommitmentLedgerSource
    | NegotiationEligibilitySource
    | HybridModifierBundleSource
    | NarrativeDiffusionSource
    | ProjectionAuditSource
    | NegotiationReplaySource
)


@dataclass(frozen=True)
class NegotiationProofMaterialization:
    """Complete, provider-free six-tick negotiation proof materialization."""

    run_id: str
    session: NegotiationSession
    agent_pack: AgentPackManifest
    baseline: WarRoomRun
    final: WarRoomRun
    ticks: tuple[NegotiationTickMaterialization, ...]
    final_audit: ConsistencyAuditSource
    replay: NegotiationReplaySource

    def ordered_sources(self) -> tuple[NegotiationProofSource, ...]:
        """Return the canonical Kernel order: 38 + 3P closed sources."""

        projections = tuple(
            item.projection_consistency for item in self.ticks if item.projection_consistency is not None
        )
        modifiers = tuple(item.modifier_bundle for item in self.ticks if item.modifier_bundle is not None)
        audits = tuple(item.projection_audit for item in self.ticks if item.projection_audit is not None)
        return (
            *(item.round for item in self.ticks),
            *(item.proposals for item in self.ticks),
            *(item.admission for item in self.ticks),
            *(item.ledger for item in self.ticks),
            *(item.eligibility for item in self.ticks),
            *projections,
            self.final_audit,
            *modifiers,
            *(item.diffusion for item in self.ticks),
            *audits,
            self.replay,
        )


@dataclass(frozen=True)
class NegotiationProofArtifactSpec:
    """Lifecycle persistence identity for one ordered closed source."""

    source: NegotiationProofSource
    proof_schema: str
    artifact_type: str
    schema_version: str
    content_hash: str
    tick: int | None


def negotiation_proof_artifact_specs(
    materialization: NegotiationProofMaterialization,
) -> tuple[NegotiationProofArtifactSpec, ...]:
    """Map materialized sources to the one canonical lifecycle Artifact identity."""

    result: list[NegotiationProofArtifactSpec] = []
    for source in materialization.ordered_sources():
        if isinstance(source, NegotiationRoundSource):
            proof_schema = "kp.negotiation-round.v1"
            artifact_type = "negotiation_round"
            content_hash = source.round_hash
        elif isinstance(source, NegotiationProposalBatchSource):
            proof_schema = "kp.negotiation-proposal-batch.v1"
            artifact_type = "negotiation_proposal_batch"
            content_hash = source.batch_hash
        elif isinstance(source, ConsistencyAuditSource):
            if source.role == "admission":
                proof_schema = "kp.negotiation-admission-consistency.v1"
            elif source.role == "projection":
                proof_schema = "kp.negotiation-projection-consistency.v1"
            else:
                proof_schema = "kp.final-consistency.v1"
            artifact_type = "consistency_audit"
            content_hash = source.audit_hash
        elif isinstance(source, CommitmentLedgerSource):
            proof_schema = "kp.commitment-ledger.v1"
            artifact_type = "commitment_ledger"
            content_hash = source.ledger_hash
        elif isinstance(source, NegotiationEligibilitySource):
            proof_schema = "kp.negotiation-eligibility.v1"
            artifact_type = "negotiation_eligibility"
            content_hash = source.eligibility_hash
        elif isinstance(source, HybridModifierBundleSource):
            proof_schema = "kp.action-modifier-bundle.v1"
            artifact_type = "deterministic_action_modifiers"
            content_hash = source.bundle_hash
        elif isinstance(source, NarrativeDiffusionSource):
            proof_schema = "kp.narrative-diffusion.v1"
            artifact_type = "narrative_diffusion"
            content_hash = source.diffusion_evidence_hash
        elif isinstance(source, ProjectionAuditSource):
            proof_schema = "kp.projection-audit.v1"
            artifact_type = "negotiation_projection_audit"
            content_hash = source.audit_hash
        elif isinstance(source, NegotiationReplaySource):
            proof_schema = "kp.negotiation-replay.v1"
            artifact_type = "negotiation_replay"
            content_hash = source.replay_hash
        else:  # pragma: no cover - the closed union is exhaustive
            raise TypeError(f"Unsupported negotiation proof source: {type(source)!r}")
        result.append(
            NegotiationProofArtifactSpec(
                source=source,
                proof_schema=proof_schema,
                artifact_type=artifact_type,
                schema_version=source.schema_version,
                content_hash=content_hash,
                tick=getattr(source, "tick", None),
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class _CommitmentEventFact:
    tick: int
    status: str
    actor_agent_id: str
    source_message_id: str | None


@dataclass
class _CommitmentState:
    proposal: AgentActionProposal
    source_message: NegotiationMessage
    legacy_party_agent_ids: tuple[str, ...]
    party_agent_ids: tuple[str, str]
    source_admission_tick: int
    source_admission_audit_hash: str
    events: list[_CommitmentEventFact] = field(default_factory=list)

    @property
    def status(self) -> str:
        return self.events[-1].status

    @property
    def legacy_hash(self) -> str:
        return stable_hash(
            {
                "source_proposal_id": self.proposal.proposal_id,
                "parties": self.legacy_party_agent_ids,
                "terms": self.proposal.model_dump(mode="json"),
            }
        )

    @property
    def legacy_id(self) -> str:
        return f"commit_{self.legacy_hash[:20]}"


def materialize_negotiation_proof(
    run_id: str,
    baseline: WarRoomRun,
    *,
    repository: NegotiationReadApplicationPort | None = None,
    simulation_runtime: SimulationRuntimeApplicationPort | None = None,
    evaluator_version: str = CONSISTENCY_EVALUATOR_VERSION,
    agent_pack_id: str | None = None,
    agent_pack_hash: str | None = None,
    constraint_context_hash: str | None = None,
) -> NegotiationProofMaterialization:
    """Rebuild a complete V2 negotiation proof without invoking a Provider.

    The V1 storage rows are treated as an authenticated transcript and a
    compatibility oracle only.  Every decision and numeric result admitted to
    the returned proof is regenerated by the current deterministic services.
    """

    if repository is None:
        raise ValueError("Negotiation V2 materialization requires an explicit read repository")
    repo = repository
    runtime = simulation_runtime or simulation_runtime_service
    session = repo.get_session(run_id)
    if (
        session.run_id != run_id
        or session.status not in {"running", "completed"}
        or session.current_tick != 6
        or session.final_result_hash is None
    ):
        raise ValueError("Negotiation V2 materialization requires one completed six-tick session")
    pack = repo.get_agent_pack(session.agent_pack_id)
    _validate_agent_pack(pack, baseline, session)

    baseline_hash = stable_hash(baseline.model_dump(mode="json"))
    if session.baseline_result_hash != baseline_hash:
        raise ValueError("Negotiation materialization baseline hash mismatch")

    rounds = tuple(repo.list_rounds(session.session_id))
    messages = tuple(repo.list_messages(session.session_id))
    stored_commitments = tuple(repo.list_commitments(session.session_id))
    messages_by_tick, messages_by_id = _validate_storage_transcript(
        run_id=run_id,
        session=session,
        pack=pack,
        rounds=rounds,
        messages=messages,
    )
    context = _constraint_context(baseline, pack)
    resolved_agent_pack_id = agent_pack_id or pack.agent_pack_id
    resolved_agent_pack_hash = agent_pack_hash or pack.manifest_hash
    resolved_context_hash = constraint_context_hash or stable_hash(
        context.model_dump(mode="json")
    )

    state = baseline
    cumulative_deltas: dict[str, float] = {}
    commitments: dict[str, _CommitmentState] = {}
    prior_projection_audits: list[ProjectionAuditSource] = []
    materialized_ticks: list[NegotiationTickMaterialization] = []

    for tick, stored_round in enumerate(rounds, start=1):
        current_messages = messages_by_tick[tick]
        _expire_commitments(commitments, tick)
        _validate_current_message_boundaries(current_messages, pack)
        current_proposals = _current_proposals(current_messages, run_id=run_id, tick=tick)
        before_hash = stable_hash(state.model_dump(mode="json"))
        _validate_stored_round_input(
            stored_round,
            state_hash=before_hash,
            pack=pack,
            baseline=baseline,
            commitments=commitments,
        )

        admission_report = evaluate_war_room_result(
            state,
            run_id=f"{run_id}:tick:{tick}",
            proposals=list(current_proposals),
            constraint_context=context,
        )
        admission = build_consistency_audit_source(
            admission_report,
            run_id=run_id,
            role="admission",
            tick=tick,
            evaluator_version=evaluator_version,
            agent_pack_id=resolved_agent_pack_id,
            agent_pack_hash=resolved_agent_pack_hash,
            constraint_context_hash=resolved_context_hash,
            complete_proposals=current_proposals,
        )
        _apply_commitment_facts(
            commitments,
            current_messages=current_messages,
            messages_by_id=messages_by_id,
            decisions=admission.inner_report().proposal_decisions,
            admission_audit_hash=admission.audit_hash,
        )
        ledger = _build_commitment_ledger_source(
            run_id=run_id,
            session_id=session.session_id,
            tick=tick,
            commitments=commitments,
            messages_by_id=messages_by_id,
        )
        messages_hash = _messages_hash(
            run_id=run_id,
            session_id=session.session_id,
            tick=tick,
            messages=current_messages,
        )
        proposals = _build_proposal_batch_source(
            run_id=run_id,
            session_id=session.session_id,
            tick=tick,
            current_messages=current_messages,
            current_proposals=current_proposals,
            commitments=commitments,
            messages_hash=messages_hash,
            admission=admission,
            ledger=ledger,
        )
        eligibility = _build_eligibility_source(
            run_id=run_id,
            session_id=session.session_id,
            tick=tick,
            proposals=proposals,
            admission=admission,
            ledger=ledger,
            prior_projection_audits=tuple(prior_projection_audits),
        )

        proposal_by_id = {item.proposal_id: item for item in _proposals_from_batch(proposals)}
        candidates = tuple(proposal_by_id[proposal_id] for proposal_id in eligibility.eligible_proposal_ids)
        projection_consistency: ConsistencyAuditSource | None = None
        modifier_bundle: HybridModifierBundleSource | None = None
        projection_audit: ProjectionAuditSource | None = None

        if candidates:
            projection_report = evaluate_war_room_result(
                state,
                run_id=f"{run_id}:projection:{tick}",
                proposals=list(candidates),
                constraint_context=context,
            )
            projection_consistency = build_consistency_audit_source(
                projection_report,
                run_id=run_id,
                role="projection",
                tick=tick,
                evaluator_version=evaluator_version,
                agent_pack_id=resolved_agent_pack_id,
                agent_pack_hash=resolved_agent_pack_hash,
                constraint_context_hash=resolved_context_hash,
                complete_proposals=candidates,
            )
            projection_decisions = tuple(projection_consistency.inner_report().proposal_decisions)
            inner_bundle = build_modifier_bundle(
                state,
                list(candidates),
                list(projection_decisions),
                seed=pack.seed,
            )
            modifier_bundle = build_hybrid_modifier_bundle_source(
                run_id=run_id,
                consistency_audit_hash=projection_consistency.audit_hash,
                bundle=inner_bundle,
                tick=tick,
            )
            projected_state = runtime.run_war_room(WarRoomScenarioRequest(**inner_bundle.scenario_patch))
            accepted_ids = {
                item.proposal_id
                for item in projection_decisions
                if item.decision == "accepted"
            }
            narrative_proposals = tuple(
                item
                for item in candidates
                if item.proposal_id in accepted_ids and item.action_type == "public_narrative"
            )
            diffusion, after_state, cumulative_deltas = _materialize_diffusion(
                run_id=run_id,
                session_id=session.session_id,
                tick=tick,
                state=projected_state,
                proposals=narrative_proposals,
                cumulative_deltas=cumulative_deltas,
                seed=pack.seed,
                runtime=runtime,
            )
            after_hash = stable_hash(after_state.model_dump(mode="json"))
            projection_audit = build_negotiation_projection_source(
                run_id=run_id,
                session_id=session.session_id,
                tick=tick,
                consistency_audit_hash=projection_consistency.audit_hash,
                before_result_hash=before_hash,
                final_result_hash=after_hash,
                proposals=candidates,
                decisions=projection_decisions,
                modifier_bundle=modifier_bundle,
            )
            prior_projection_audits.append(projection_audit)
        else:
            diffusion, after_state, cumulative_deltas = _materialize_diffusion(
                run_id=run_id,
                session_id=session.session_id,
                tick=tick,
                state=state,
                proposals=(),
                cumulative_deltas=cumulative_deltas,
                seed=pack.seed,
                runtime=runtime,
            )
            after_hash = before_hash

        _validate_stored_round_result(stored_round, after_state, after_hash)
        round_source = _build_round_source(
            run_id=run_id,
            session_id=session.session_id,
            tick=tick,
            messages=current_messages,
            messages_hash=messages_hash,
            current_proposals=current_proposals,
            admission=admission,
            ledger=ledger,
            proposals=proposals,
            eligibility=eligibility,
            projection_consistency=projection_consistency,
            modifier_bundle=modifier_bundle,
            diffusion=diffusion,
            projection_audit=projection_audit,
            before_result_hash=before_hash,
            after_result_hash=after_hash,
        )
        materialized_ticks.append(
            NegotiationTickMaterialization(
                tick=tick,
                round=round_source,
                proposals=proposals,
                admission=admission,
                ledger=ledger,
                eligibility=eligibility,
                projection_consistency=projection_consistency,
                modifier_bundle=modifier_bundle,
                diffusion=diffusion,
                projection_audit=projection_audit,
            )
        )
        state = after_state

    _validate_stored_commitments(
        stored_commitments,
        session_id=session.session_id,
        commitments=commitments,
        messages_by_id=messages_by_id,
    )
    final_hash = stable_hash(state.model_dump(mode="json"))
    if session.final_result_hash != final_hash:
        raise ValueError("Negotiation regenerated final result does not match the stored checkpoint")
    final_report = evaluate_war_room_result(
        state,
        run_id=run_id,
        proposals=[],
        constraint_context=context,
    )
    final_audit = build_consistency_audit_source(
        final_report,
        run_id=run_id,
        role="final",
        tick=None,
        evaluator_version=evaluator_version,
        agent_pack_id=resolved_agent_pack_id,
        agent_pack_hash=resolved_agent_pack_hash,
        constraint_context_hash=resolved_context_hash,
        complete_proposals=(),
    )
    tick_sources = tuple(materialized_ticks)
    replay = build_negotiation_replay_source(
        run_id=run_id,
        session_id=session.session_id,
        baseline_result_hash=baseline_hash,
        final_result_hash=final_hash,
        round_hashes=tuple(item.round.round_hash for item in tick_sources),
        proposal_batch_hashes=tuple(item.proposals.batch_hash for item in tick_sources),
        admission_audit_hashes=tuple(item.admission.audit_hash for item in tick_sources),
        ledger_hashes=tuple(item.ledger.ledger_hash for item in tick_sources),
        eligibility_hashes=tuple(item.eligibility.eligibility_hash for item in tick_sources),
        projection_consistency_hashes=tuple(
            item.projection_consistency.audit_hash if item.projection_consistency is not None else None
            for item in tick_sources
        ),
        modifier_bundle_hashes=tuple(
            item.modifier_bundle.bundle_hash if item.modifier_bundle is not None else None for item in tick_sources
        ),
        diffusion_evidence_hashes=tuple(item.diffusion.diffusion_evidence_hash for item in tick_sources),
        projection_audit_hashes=tuple(
            item.projection_audit.audit_hash if item.projection_audit is not None else None for item in tick_sources
        ),
        message_chain_head=messages[-1].message_hash if messages else None,
    )
    result = NegotiationProofMaterialization(
        run_id=run_id,
        session=session,
        agent_pack=pack,
        baseline=baseline,
        final=state,
        ticks=tick_sources,
        final_audit=final_audit,
        replay=replay,
    )
    expected_source_count = 38 + 3 * sum(item.projected for item in tick_sources)
    if len(result.ordered_sources()) != expected_source_count:
        raise AssertionError("Negotiation materializer emitted a noncanonical proof count")
    return result


def _validate_agent_pack(
    pack: AgentPackManifest,
    baseline: WarRoomRun,
    session: NegotiationSession,
) -> None:
    expected = build_agent_pack(baseline, pack.seed)
    if (
        pack.agent_pack_id != session.agent_pack_id
        or pack.manifest_hash != session.agent_pack_hash
        or pack.model_dump(mode="json", exclude={"created_at"})
        != expected.model_dump(mode="json", exclude={"created_at"})
    ):
        raise ValueError("Negotiation Agent Pack identity or deterministic contents drifted")


def _validate_storage_transcript(
    *,
    run_id: str,
    session: NegotiationSession,
    pack: AgentPackManifest,
    rounds: tuple[NegotiationRound, ...],
    messages: tuple[NegotiationMessage, ...],
) -> tuple[dict[int, tuple[NegotiationMessage, ...]], dict[str, NegotiationMessage]]:
    if len(rounds) != 6 or tuple(item.tick for item in rounds) != tuple(range(1, 7)):
        raise ValueError("Negotiation storage must contain exactly ticks 1..6")
    round_by_tick = {item.tick: item for item in rounds}
    for item in rounds:
        expected_round_id = "round_" + stable_hash({"session": session.session_id, "tick": item.tick})[:20]
        if (
            item.status != "completed"
            or item.session_id != session.session_id
            or item.round_id != expected_round_id
            or item.input_hash != stable_hash(item.input)
            or item.output_hash is None
            or item.output_hash != stable_hash(item.output)
            or item.result_state_hash is None
        ):
            raise ValueError(f"Negotiation stored round integrity mismatch at tick {item.tick}")

    if tuple(item.seq for item in messages) != tuple(range(1, len(messages) + 1)):
        raise ValueError("Negotiation messages must form one global contiguous sequence")
    if len({item.message_id for item in messages}) != len(messages):
        raise ValueError("Negotiation message IDs must be unique")
    messages_by_id = {item.message_id: item for item in messages}
    grouped: dict[int, list[NegotiationMessage]] = {tick: [] for tick in range(1, 7)}
    previous_hash: str | None = None
    for message in messages:
        stored_round = round_by_tick.get(message.tick)
        if (
            stored_round is None
            or message.session_id != session.session_id
            or message.round_id != stored_round.round_id
        ):
            raise ValueError(f"Negotiation message coordinate mismatch at seq {message.seq}")
        proposal = _proposal_from_message(message, run_id=run_id, tick=message.tick)
        expected_hash = stable_hash(
            {
                "tick": message.tick,
                "seq": message.seq,
                "sender_agent_id": message.sender_agent_id,
                "recipient_agent_ids": message.recipient_agent_ids,
                "message_type": message.message_type,
                "visibility": message.visibility,
                "parent_message_id": message.parent_message_id,
                "proposal": proposal.model_dump(mode="json") if proposal else None,
                "narrative": message.narrative,
                "previous_hash": previous_hash,
            }
        )
        if (
            message.previous_hash != previous_hash
            or message.message_hash != expected_hash
            or message.message_id != f"msg_{expected_hash[:20]}"
        ):
            raise ValueError(f"Negotiation message hash-chain mismatch at seq {message.seq}")
        if message.parent_message_id is not None:
            parent = messages_by_id.get(message.parent_message_id)
            if parent is None or parent.seq >= message.seq:
                raise ValueError(f"Negotiation message parent ordering mismatch at seq {message.seq}")
        grouped[message.tick].append(message)
        previous_hash = message.message_hash

    result: dict[int, tuple[NegotiationMessage, ...]] = {}
    for tick in range(1, 7):
        tick_messages = tuple(grouped[tick])
        scheduled = scheduled_profiles(pack, tick)
        scheduled_ids = [item.agent_id for item in scheduled]
        if round_by_tick[tick].scheduled_agents != scheduled_ids:
            raise ValueError(f"Negotiation stored schedule drifted at tick {tick}")
        sender_ids = [item.sender_agent_id for item in tick_messages]
        if sorted(sender_ids) != sorted(scheduled_ids) or len(set(sender_ids)) != len(sender_ids):
            raise ValueError(f"Negotiation message membership drifted at tick {tick}")
        result[tick] = tick_messages
    return result, messages_by_id


def _validate_current_message_boundaries(
    messages: Sequence[NegotiationMessage],
    pack: AgentPackManifest,
) -> None:
    known_agents = {item.agent_id: item for item in pack.profiles}
    for message in messages:
        proposal = (
            AgentActionProposal.model_validate(message.payload["proposal"], strict=True)
            if message.proposal_id is not None
            else None
        )
        if proposal is None or proposal.action_type not in BILATERAL_ACTIONS:
            continue
        if (
            message.visibility != "direct"
            or len(message.recipient_agent_ids) != 1
            or message.recipient_agent_ids[0] == message.sender_agent_id
            or proposal.actor_id != message.sender_agent_id
            or len(proposal.target_ids) != 1
            or not proposal.target_ids[0].startswith("country:")
        ):
            raise ValueError("Negotiation bilateral origin violates the closed direct-message boundary")
        recipient = known_agents.get(message.recipient_agent_ids[0])
        target_country = proposal.target_ids[0].split(":", 1)[1]
        if recipient is None or recipient.country_code != target_country:
            raise ValueError("Negotiation bilateral target does not bind its recipient Agent")


def _proposal_from_message(
    message: NegotiationMessage,
    *,
    run_id: str,
    tick: int,
) -> AgentActionProposal | None:
    if message.proposal_id is None:
        if message.payload != {}:
            raise ValueError("Negotiation message without proposal has a nonempty payload")
        return None
    if set(message.payload) != {"proposal"} or not isinstance(message.payload["proposal"], dict):
        raise ValueError("Negotiation proposal message is not a complete closed payload")
    raw = message.payload["proposal"]
    if set(raw) != set(AgentActionProposal.model_fields):
        raise ValueError("Negotiation stored proposal field set drifted")
    proposal = AgentActionProposal.model_validate(raw, strict=True)
    canonical = proposal.model_dump(mode="json")
    targets = tuple(proposal.target_ids)
    if (
        raw != canonical
        or proposal.proposal_id != message.proposal_id
        or proposal.run_id != run_id
        or proposal.turn != tick
        or targets != tuple(sorted(set(targets), key=lambda value: value.encode("utf-8")))
    ):
        raise ValueError("Negotiation stored proposal identity or canonical order drifted")
    return proposal


def _current_proposals(
    messages: Sequence[NegotiationMessage],
    *,
    run_id: str,
    tick: int,
) -> tuple[AgentActionProposal, ...]:
    proposals = tuple(
        proposal
        for item in messages
        if (proposal := _proposal_from_message(item, run_id=run_id, tick=tick)) is not None
    )
    ordered = tuple(sorted(proposals, key=lambda item: item.proposal_id.encode("utf-8")))
    if len({item.proposal_id for item in ordered}) != len(ordered):
        raise ValueError("Negotiation current proposal IDs must be unique")
    return ordered


def _constraint_context(
    state: WarRoomRun,
    pack: AgentPackManifest,
) -> AgentConstraintContext:
    entities = (
        {f"country:{item.code}" for item in state.country_agents}
        | {f"chain:{item.key}" for item in state.supply_chains}
        | {f"timeline:{item.day}" for item in state.timeline}
        | {"scenario"}
    )
    return AgentConstraintContext(
        actor_capabilities={item.agent_id: item.capabilities for item in pack.profiles},
        action_budgets={item.agent_id: item.action_budget for item in pack.profiles},
        known_entities=sorted(entities),
        known_evidence_refs=sorted(entities),
    )


def _validate_stored_round_input(
    stored_round: NegotiationRound,
    *,
    state_hash: str,
    pack: AgentPackManifest,
    baseline: WarRoomRun,
    commitments: dict[str, _CommitmentState],
) -> None:
    tick = stored_round.tick
    expected_day = int(round(baseline.scenario.duration_days * TICK_PROGRESS[tick - 1]))
    payload = stored_round.input
    if (
        payload.get("tick") != tick
        or payload.get("simulation_day") != expected_day
        or payload.get("state_hash") != state_hash
        or payload.get("agent_pack_hash") != pack.manifest_hash
        or payload.get("scheduled_agents") != stored_round.scheduled_agents
            or stored_round.simulation_day != expected_day
        or stored_round.previous_state_hash != state_hash
    ):
        raise ValueError(f"Negotiation stored round input drifted at tick {tick}")


def _apply_commitment_facts(
    commitments: dict[str, _CommitmentState],
    *,
    current_messages: tuple[NegotiationMessage, ...],
    messages_by_id: dict[str, NegotiationMessage],
    decisions: Sequence,
    admission_audit_hash: str,
) -> None:
    decisions_by_id = {item.proposal_id: item for item in decisions}
    for message in current_messages:
        proposal = (
            AgentActionProposal.model_validate(message.payload["proposal"], strict=True)
            if message.proposal_id is not None
            else None
        )
        if proposal is not None and proposal.action_type in BILATERAL_ACTIONS:
            decision = decisions_by_id.get(proposal.proposal_id)
            if decision is not None and decision.outcome == "accepted":
                if proposal.proposal_id in commitments:
                    raise ValueError("Negotiation commitment proposal was admitted twice")
                legacy_parties = (message.sender_agent_id, *message.recipient_agent_ids)
                canonical_parties = tuple(sorted(set(legacy_parties), key=lambda value: value.encode("utf-8")))
                if len(legacy_parties) != 2 or len(canonical_parties) != 2:
                    raise ValueError("Negotiation V2 commitments require exactly two parties")
                commitments[proposal.proposal_id] = _CommitmentState(
                    proposal=proposal,
                    source_message=message,
                    legacy_party_agent_ids=legacy_parties,
                    party_agent_ids=(canonical_parties[0], canonical_parties[1]),
                    source_admission_tick=message.tick,
                    source_admission_audit_hash=admission_audit_hash,
                    events=[
                        _CommitmentEventFact(
                            tick=message.tick,
                            status="proposed",
                            actor_agent_id=message.sender_agent_id,
                            source_message_id=message.message_id,
                        )
                    ],
                )

        if message.message_type not in RESPONSE_STATUS or message.parent_message_id is None:
            continue
        parent = messages_by_id.get(message.parent_message_id)
        if parent is None or parent.proposal_id is None:
            continue
        commitment = commitments.get(parent.proposal_id)
        if commitment is None or not _response_is_authorized(parent, message):
            continue
        status = RESPONSE_STATUS[message.message_type]
        legal_edges = {
            "proposed": {"active", "rejected", "withdrawn", "expired"},
            "active": {"withdrawn", "expired"},
        }
        if status not in legal_edges.get(commitment.status, set()):
            continue
        if status == "active" and _conflicts_with_active_alliance(commitment, commitments):
            status = "rejected"
        commitment.events.append(
            _CommitmentEventFact(
                tick=message.tick,
                status=status,
                actor_agent_id=message.sender_agent_id,
                source_message_id=message.message_id,
            )
        )


def _expire_commitments(
    commitments: dict[str, _CommitmentState],
    tick: int,
) -> None:
    for commitment in sorted(
        commitments.values(), key=lambda item: item.legacy_id.encode("utf-8")
    ):
        if commitment.status not in {"proposed", "active"}:
            continue
        expires_after = commitment.proposal.expires_after_turn
        if expires_after is None or tick <= expires_after:
            continue
        commitment.events.append(
            _CommitmentEventFact(
                tick=tick,
                status="expired",
                actor_agent_id="run_control",
                source_message_id=None,
            )
        )


def _response_is_authorized(
    parent: NegotiationMessage,
    response: NegotiationMessage,
) -> bool:
    return bool(
        parent.message_type in {"proposal", "public_statement"}
        and parent.visibility == "direct"
        and len(parent.recipient_agent_ids) == 1
        and response.message_type in RESPONSE_STATUS
        and response.visibility == "direct"
        and response.parent_message_id == parent.message_id
        and response.tick > parent.tick
        and response.sender_agent_id == parent.recipient_agent_ids[0]
        and response.recipient_agent_ids == [parent.sender_agent_id]
    )


def _conflicts_with_active_alliance(
    candidate: _CommitmentState,
    commitments: dict[str, _CommitmentState],
) -> bool:
    if candidate.proposal.action_type != "alliance_request":
        return False
    parties = set(candidate.party_agent_ids)
    return any(
        item is not candidate
        and item.status == "active"
        and item.proposal.action_type == "alliance_request"
        and set(item.party_agent_ids) == parties
        for item in commitments.values()
    )


def _build_commitment_ledger_source(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    commitments: dict[str, _CommitmentState],
    messages_by_id: dict[str, NegotiationMessage],
) -> CommitmentLedgerSource:
    entries: list[dict[str, object]] = []
    for commitment in commitments.values():
        proposal_payload = commitment.proposal.model_dump(mode="json")
        proposal_hash = stable_hash(proposal_payload)
        terms = {
            "session_id": session_id,
            "action_type": commitment.proposal.action_type,
            "proposal": proposal_payload,
        }
        terms_hash = stable_hash({"schema_version": "commitment-ledger.v2", "terms": terms})
        commitment_preimage = {
            "schema_version": "commitment-ledger.v2",
            "session_id": session_id,
            "action_type": commitment.proposal.action_type,
            "party_agent_ids": commitment.party_agent_ids,
            "terms_hash": terms_hash,
            "source_proposal_id": commitment.proposal.proposal_id,
            "source_proposal_hash": proposal_hash,
            "source_message_id": commitment.source_message.message_id,
            "source_message_hash": commitment.source_message.message_hash,
            "source_admission_tick": commitment.source_admission_tick,
            "source_admission_audit_hash": commitment.source_admission_audit_hash,
        }
        commitment_hash = stable_hash(commitment_preimage)
        commitment_id = f"commit_{commitment_hash[:20]}"
        previous_event_hash: str | None = None
        events: list[dict[str, object]] = []
        for seq, event in enumerate(commitment.events, start=1):
            source_message = (
                messages_by_id[event.source_message_id]
                if event.source_message_id is not None
                else None
            )
            event_preimage = {
                "schema_version": "commitment-ledger.v2",
                "commitment_id": commitment_id,
                "tick": event.tick,
                "seq": seq,
                "status": event.status,
                "actor_agent_id": event.actor_agent_id,
                "source_message_id": event.source_message_id,
                "source_message_hash": (
                    source_message.message_hash if source_message is not None else None
                ),
                "previous_event_hash": previous_event_hash,
            }
            event_hash = stable_hash(event_preimage)
            events.append(
                {
                    "tick": event.tick,
                    "seq": seq,
                    "status": event.status,
                    "actor_agent_id": event.actor_agent_id,
                    "source_message_id": event.source_message_id,
                    "source_message_hash": (
                        source_message.message_hash if source_message is not None else None
                    ),
                    "previous_event_hash": previous_event_hash,
                    "event_hash": event_hash,
                }
            )
            previous_event_hash = event_hash
        entries.append(
            {
                "commitment_id": commitment_id,
                "commitment_hash": commitment_hash,
                "status": commitment.status,
                "action_type": commitment.proposal.action_type,
                "party_agent_ids": commitment.party_agent_ids,
                "terms": terms,
                "terms_hash": terms_hash,
                "source_proposal_id": commitment.proposal.proposal_id,
                "source_proposal_hash": proposal_hash,
                "source_message_id": commitment.source_message.message_id,
                "source_message_hash": commitment.source_message.message_hash,
                "source_admission_tick": commitment.source_admission_tick,
                "source_admission_audit_hash": commitment.source_admission_audit_hash,
                "events": tuple(events),
            }
        )
    entries.sort(key=lambda item: str(item["commitment_id"]).encode("utf-8"))
    payload = {
        "schema_version": "commitment-ledger.v2",
        "run_id": run_id,
        "session_id": session_id,
        "tick": tick,
        "entries": tuple(entries),
        "ledger_entry_count": len(entries),
    }
    ledger_hash = stable_hash(
        {
            "schema_version": "commitment-ledger.v2",
            "run_id": run_id,
            "session_id": session_id,
            "tick": tick,
            "entries": tuple(entries),
        }
    )
    return CommitmentLedgerSource.model_validate({**payload, "ledger_hash": ledger_hash})


def _messages_hash(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    messages: tuple[NegotiationMessage, ...],
) -> str:
    return stable_hash(
        {
            "schema_version": "negotiation-round.v2",
            "run_id": run_id,
            "session_id": session_id,
            "tick": tick,
            "message_tuples": [[item.seq, item.message_id, item.message_hash] for item in messages],
        }
    )


def _proposal_claim(
    proposal: AgentActionProposal,
    *,
    source_message: NegotiationMessage,
    source_kind: str,
    commitment_id: str | None,
    source_admission_tick: int,
    source_admission_audit_hash: str,
) -> tuple:
    action_class = ACTION_CLASS_BY_TYPE.get(proposal.action_type)
    if action_class is None:
        raise ValueError(f"Unsupported negotiation action type: {proposal.action_type}")
    proposal_hash = stable_hash(proposal.model_dump(mode="json"))
    semantic_hash = stable_hash(
        {
            "actor_id": proposal.actor_id,
            "action_type": proposal.action_type,
            "target_ids": tuple(proposal.target_ids),
            "parameters": proposal.parameters,
        }
    )
    return (
        proposal.proposal_id,
        proposal_hash,
        source_message.message_id,
        source_message.message_hash,
        proposal.action_type,
        action_class,
        semantic_hash,
        source_kind,
        commitment_id,
        source_admission_tick,
        source_admission_audit_hash,
    )


def _build_proposal_batch_source(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    current_messages: tuple[NegotiationMessage, ...],
    current_proposals: tuple[AgentActionProposal, ...],
    commitments: dict[str, _CommitmentState],
    messages_hash: str,
    admission: ConsistencyAuditSource,
    ledger: CommitmentLedgerSource,
) -> NegotiationProposalBatchSource:
    message_by_proposal = {item.proposal_id: item for item in current_messages if item.proposal_id is not None}
    pairs: list[tuple[AgentActionProposal, tuple]] = []
    for proposal in current_proposals:
        pairs.append(
            (
                proposal,
                _proposal_claim(
                    proposal,
                    source_message=message_by_proposal[proposal.proposal_id],
                    source_kind="current_message",
                    commitment_id=None,
                    source_admission_tick=tick,
                    source_admission_audit_hash=admission.audit_hash,
                ),
            )
        )
    ledger_by_source = {item.source_proposal_id: item for item in ledger.entries if item.status == "active"}
    for proposal_id, commitment in commitments.items():
        entry = ledger_by_source.get(proposal_id)
        if entry is None or commitment.source_admission_tick >= tick:
            continue
        pairs.append(
            (
                commitment.proposal,
                _proposal_claim(
                    commitment.proposal,
                    source_message=commitment.source_message,
                    source_kind="active_commitment_origin",
                    commitment_id=entry.commitment_id,
                    source_admission_tick=commitment.source_admission_tick,
                    source_admission_audit_hash=commitment.source_admission_audit_hash,
                ),
            )
        )
    pairs.sort(key=lambda item: item[0].proposal_id.encode("utf-8"))
    proposal_ids = tuple(item[0].proposal_id for item in pairs)
    if len(set(proposal_ids)) != len(proposal_ids):
        raise ValueError("Negotiation NP source membership contains duplicate proposal IDs")
    payload = {
        "schema_version": "negotiation-proposal-batch.v1",
        "run_id": run_id,
        "session_id": session_id,
        "tick": tick,
        "source_hashes": (messages_hash, admission.audit_hash, ledger.ledger_hash),
        "proposal_claim_tuples": tuple(item[1] for item in pairs),
        "proposal_count": len(pairs),
        "proposals": tuple(item[0].model_dump(mode="json") for item in pairs),
    }
    return NegotiationProposalBatchSource.model_validate({**payload, "batch_hash": stable_hash(payload)})


def _proposals_from_batch(
    source: NegotiationProposalBatchSource,
) -> tuple[AgentActionProposal, ...]:
    return tuple(AgentActionProposal.model_validate(item, strict=True) for item in source.proposals)


def _build_eligibility_source(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    proposals: NegotiationProposalBatchSource,
    admission: ConsistencyAuditSource,
    ledger: CommitmentLedgerSource,
    prior_projection_audits: tuple[ProjectionAuditSource, ...],
) -> NegotiationEligibilitySource:
    claims = proposals.extract_claims().proposal_claim_tuples
    report = admission.inner_report()
    accepted_ids = {item.proposal_id for item in report.proposal_decisions if item.decision == "accepted"}
    admission_hashes = dict(zip(admission.proposal_ids, admission.proposal_hashes, strict=True))
    prior_ids = {proposal_id for audit in prior_projection_audits for proposal_id in audit.projected_proposal_ids}
    prior_semantics = {
        semantic_hash for audit in prior_projection_audits for semantic_hash in audit.projected_semantic_key_hashes
    }
    ledger_entries = tuple(ledger.entries)
    expected: dict[str, str | None] = {}
    preliminary: dict[str, list[str]] = {}
    for claim in claims:
        proposal_id, proposal_hash = claim[0], claim[1]
        action_class, semantic_hash = claim[5], claim[6]
        source_kind, commitment_id = claim[7], claim[8]
        if source_kind == "current_message" and (
            proposal_id not in accepted_ids or admission_hashes.get(proposal_id) != proposal_hash
        ):
            expected[proposal_id] = "not_admitted"
            continue
        active_entry = None
        if source_kind == "active_commitment_origin":
            active_entry = next(
                (item for item in ledger_entries if item.commitment_id == commitment_id),
                None,
            )
            if active_entry is None or active_entry.status != "active":
                raise ValueError("Negotiation active-origin NP is absent from current CL")
        if action_class == "audit_only":
            expected[proposal_id] = "audit_only"
            continue
        if action_class == "alliance_response":
            expected[proposal_id] = "alliance_response"
            continue
        if action_class == "bilateral_commitment" and active_entry is None:
            active_matches = tuple(
                item
                for item in ledger_entries
                if item.status == "active"
                and item.source_proposal_id == proposal_id
                and item.source_proposal_hash == proposal_hash
            )
            if len(active_matches) != 1:
                expected[proposal_id] = "inactive_commitment"
                continue
        if proposal_id in prior_ids:
            expected[proposal_id] = "already_projected"
            continue
        if semantic_hash in prior_semantics:
            expected[proposal_id] = "semantic_duplicate"
            continue
        expected[proposal_id] = None
        preliminary.setdefault(semantic_hash, []).append(proposal_id)
    for group in preliminary.values():
        winner = min(group, key=lambda value: value.encode("utf-8"))
        for proposal_id in group:
            expected[proposal_id] = "eligible" if proposal_id == winner else "semantic_duplicate"

    decisions = []
    eligible_ids: list[str] = []
    decision_hashes: list[str] = []
    for claim in claims:
        proposal_id = claim[0]
        outcome = expected[proposal_id]
        if outcome is None:
            raise AssertionError("Negotiation eligibility outcome was not finalized")
        prior_projected = proposal_id in prior_ids
        decision_hash = stable_hash({"decision": [claim, prior_projected, outcome]})
        decisions.append(
            {
                "proposal_claim_tuple": claim,
                "prior_projected": prior_projected,
                "outcome": outcome,
                "decision_hash": decision_hash,
            }
        )
        decision_hashes.append(decision_hash)
        if outcome == "eligible":
            eligible_ids.append(proposal_id)
    payload = {
        "schema_version": "negotiation-eligibility.v1",
        "run_id": run_id,
        "session_id": session_id,
        "tick": tick,
        "decisions": tuple(decisions),
        "decision_count": len(decisions),
        "eligible_proposal_ids": tuple(eligible_ids),
        "eligible_proposal_count": len(eligible_ids),
    }
    eligibility_hash = stable_hash(
        {
            "schema_version": "negotiation-eligibility.v1",
            "run_id": run_id,
            "session_id": session_id,
            "tick": tick,
            "decision_hashes": tuple(decision_hashes),
            "eligible_proposal_ids": tuple(eligible_ids),
        }
    )
    return NegotiationEligibilitySource.model_validate({**payload, "eligibility_hash": eligibility_hash})


def _materialize_diffusion(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    state: WarRoomRun,
    proposals: tuple[AgentActionProposal, ...],
    cumulative_deltas: dict[str, float],
    seed: int,
    runtime: SimulationRuntimeApplicationPort,
) -> tuple[NarrativeDiffusionSource, WarRoomRun, dict[str, float]]:
    before_hash = stable_hash(state.model_dump(mode="json"))
    if proposals:
        request, audit, cumulative = apply_narrative_diffusion(
            state,
            list(proposals),
            cumulative_deltas,
            seed=seed,
        )
        after = runtime.run_war_room(request)
    else:
        request = _scenario_request(state, seed=seed)
        core = {
            "schema_version": "narrative-diffusion.v1",
            "seed": seed,
            "tone_deltas": TONE_DELTAS,
            "country_deltas": {},
            "applications": [],
        }
        audit = NarrativeDiffusionAudit(**core, audit_hash=stable_hash(core))
        cumulative = dict(cumulative_deltas)
        after = state
    after_hash = stable_hash(after.model_dump(mode="json"))
    source = build_narrative_diffusion_source(
        run_id=run_id,
        session_id=session_id,
        tick=tick,
        proposals=proposals,
        audit=audit,
        diffusion_request=request,
        before_result_hash=before_hash,
        after_result_hash=after_hash,
    )
    return source, after, cumulative


def _scenario_request(state: WarRoomRun, *, seed: int) -> WarRoomScenarioRequest:
    return WarRoomScenarioRequest(
        scenario_key=state.scenario.key,
        duration_days=state.scenario.duration_days,
        intensity=state.scenario.intensity,
        propagation=state.scenario.propagation,
        target_countries=list(state.scenario.target_countries),
        target_chains=list(state.scenario.target_chains),
        policy_actions=list(state.scenario.policy_actions),
        country_overrides=deepcopy(state.scenario.country_overrides),
        chain_overrides=deepcopy(state.scenario.chain_overrides),
        seed=seed,
    )


def _validate_stored_round_result(
    stored_round: NegotiationRound,
    regenerated: WarRoomRun,
    regenerated_hash: str,
) -> None:
    stored_payload = stored_round.output
    stored_result = stored_payload.get("result")
    if not isinstance(stored_result, dict):
        raise ValueError(f"Negotiation stored result is missing at tick {stored_round.tick}")
    if (
        stored_round.result_state_hash != regenerated_hash
        or stored_payload.get("result_hash") != regenerated_hash
        or stable_hash(stored_result) != regenerated_hash
        or stable_hash(regenerated.model_dump(mode="json")) != regenerated_hash
    ):
        raise ValueError(f"Negotiation deterministic rematerialization drifted at tick {stored_round.tick}")


def _build_round_source(
    *,
    run_id: str,
    session_id: str,
    tick: int,
    messages: tuple[NegotiationMessage, ...],
    messages_hash: str,
    current_proposals: tuple[AgentActionProposal, ...],
    admission: ConsistencyAuditSource,
    ledger: CommitmentLedgerSource,
    proposals: NegotiationProposalBatchSource,
    eligibility: NegotiationEligibilitySource,
    projection_consistency: ConsistencyAuditSource | None,
    modifier_bundle: HybridModifierBundleSource | None,
    diffusion: NarrativeDiffusionSource,
    projection_audit: ProjectionAuditSource | None,
    before_result_hash: str,
    after_result_hash: str,
) -> NegotiationRoundSource:
    round_id = f"round_{stable_hash({'session': session_id, 'tick': tick})[:20]}"
    message_tuples = [[item.seq, item.message_id, item.message_hash] for item in messages]
    accepted_ids = tuple(
        item.proposal_id for item in admission.inner_report().proposal_decisions if item.decision == "accepted"
    )
    projected = bool(eligibility.eligible_proposal_ids)
    if projected != all(item is not None for item in (projection_consistency, modifier_bundle, projection_audit)):
        raise AssertionError("Negotiation projection source set is incomplete")
    input_payload = {
        "before_result_hash": before_result_hash,
        "message_tuples": message_tuples,
        "messages": [item.model_dump(mode="json") for item in messages],
        "messages_hash": messages_hash,
        "message_count": len(messages),
        "proposal_ids": tuple(item.proposal_id for item in current_proposals),
        "accepted_proposal_ids": accepted_ids,
        "proposal_batch_hash": proposals.batch_hash,
        "admission_audit_hash": admission.audit_hash,
        "ledger_hash": ledger.ledger_hash,
        "eligibility_hash": eligibility.eligibility_hash,
        "eligible_proposal_ids": eligibility.eligible_proposal_ids,
    }
    output_payload = {
        "projection_consistency_hash": (
            projection_consistency.audit_hash if projection_consistency is not None else None
        ),
        "modifier_bundle_hash": (modifier_bundle.bundle_hash if modifier_bundle is not None else None),
        "diffusion_evidence_hash": diffusion.diffusion_evidence_hash,
        "projection_audit_hash": (projection_audit.audit_hash if projection_audit is not None else None),
        "no_projection_reason": None if projected else "no_projection",
        "after_result_hash": after_result_hash,
    }
    identity = {
        "schema_version": "negotiation-round.v2",
        "run_id": run_id,
        "session_id": session_id,
        "round_id": round_id,
        "tick": tick,
    }
    input_hash = stable_hash({**identity, "input": input_payload})
    output_hash = stable_hash({**identity, "output": output_payload})
    payload = {
        **identity,
        "input": input_payload,
        "input_hash": input_hash,
        "output": output_payload,
        "output_hash": output_hash,
        "round_hash": stable_hash(
            {
                **identity,
                "input_hash": input_hash,
                "output_hash": output_hash,
            }
        ),
    }
    return NegotiationRoundSource.model_validate(payload)


def _validate_stored_commitments(
    stored: tuple[NegotiationCommitment, ...],
    *,
    session_id: str,
    commitments: dict[str, _CommitmentState],
    messages_by_id: dict[str, NegotiationMessage],
) -> None:
    by_proposal = {item.source_proposal_id: item for item in stored}
    if len(by_proposal) != len(stored) or set(by_proposal) != set(commitments):
        raise ValueError("Negotiation stored commitment membership drifted")
    for proposal_id, expected in commitments.items():
        actual = by_proposal[proposal_id]
        proposal_payload = expected.proposal.model_dump(mode="json")
        if (
            actual.session_id != session_id
            or actual.commitment_id != expected.legacy_id
            or actual.commitment_hash != expected.legacy_hash
            or actual.source_message_id != expected.source_message.message_id
            or actual.action_type != expected.proposal.action_type
            or tuple(actual.party_agent_ids) != expected.legacy_party_agent_ids
            or actual.terms != proposal_payload
            or not actual.events
            or actual.status != actual.events[-1].status
        ):
            raise ValueError(f"Negotiation stored commitment drifted: {proposal_id}")
        previous_status: str | None = None
        legal_edges = {
            ("proposed", "active"),
            ("proposed", "rejected"),
            ("proposed", "withdrawn"),
            ("proposed", "expired"),
            ("active", "withdrawn"),
            ("active", "expired"),
        }
        for index, event in enumerate(actual.events, start=1):
            source_message = messages_by_id.get(event.source_message_id)
            if source_message is None:
                raise ValueError(
                    f"Negotiation stored commitment event source is unknown: {event.event_id}"
                )
            event_payload = {
                "commitment_id": actual.commitment_id,
                "tick": event.tick,
                "seq": event.seq,
                "status": event.status,
                "actor_agent_id": event.actor_agent_id,
                "source_message_id": event.source_message_id,
                "reason": event.reason,
            }
            expected_event_hash = stable_hash(event_payload)
            if (
                event.commitment_id != actual.commitment_id
                or event.session_id != session_id
                or event.seq != index
                or (index == 1 and event.status != "proposed")
                or (index > 1 and (previous_status, event.status) not in legal_edges)
                or event.actor_agent_id != source_message.sender_agent_id
                or (
                    index == 1
                    and event.source_message_id != expected.source_message.message_id
                )
                or event.event_hash != expected_event_hash
                or event.event_id != f"cevt_{expected_event_hash[:20]}"
            ):
                raise ValueError(f"Negotiation stored commitment event drifted: {event.event_id}")
            previous_status = event.status
