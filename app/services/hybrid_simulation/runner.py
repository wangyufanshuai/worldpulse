from __future__ import annotations

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency.hashing import stable_hash
from app.services.consistency.models import AgentActionDecision, ConsistencyAuditReport
from app.services.consistency.projection import build_action_projection_audit, verify_action_projection_audit
from app.services.consistency.models import AgentActionProjectionAudit
from app.services.war_room_engine import run_war_room

from .adapter import build_modifier_bundle, verify_modifier_bundle
from .diffing import build_hybrid_snapshot_diff
from .models import HybridModifierBundle, HybridReplayRecord, HybridSimulationOutcome


def run_hybrid_simulation(
    baseline: WarRoomRun,
    proposals: list[AgentActionProposal],
    audit: ConsistencyAuditReport,
    *,
    seed: int = 42,
) -> HybridSimulationOutcome:
    bundle = build_modifier_bundle(baseline, proposals, audit.proposal_decisions, seed=seed)
    verify_modifier_bundle(bundle)
    final_without_trace = run_war_room(WarRoomScenarioRequest(**bundle.scenario_patch))
    baseline_hash = stable_hash(baseline.model_dump(mode="json"))
    final_hash = stable_hash(final_without_trace.model_dump(mode="json"))
    baseline_diff = build_hybrid_snapshot_diff(baseline, final_without_trace)
    record_payload = {
        "schema_version": "hybrid-replay-record.v1",
        "baseline_result_hash": baseline_hash,
        "final_result_hash": final_hash,
        "consistency_audit_hash": audit.audit_hash,
        "modifier_bundle_hash": bundle.bundle_hash,
        "accepted_proposal_ids": bundle.accepted_proposal_ids,
        "baseline_diff": baseline_diff,
        "hash_scope": "WarRoomRun before hybrid_trace metadata",
    }
    record = HybridReplayRecord(**record_payload, replay_hash=stable_hash(record_payload))
    projection_audit = build_action_projection_audit(
        run_id=audit.run_id,
        consistency_audit_hash=audit.audit_hash,
        final_result_hash=final_hash,
        proposals=proposals,
        decisions=audit.proposal_decisions,
        projection_mode="hybrid",
        projected_ids=set(bundle.accepted_proposal_ids),
        modifier_hashes={item.proposal_id: item.modifier_hash for item in bundle.modifiers},
        modifier_ids={item.proposal_id: item.modifier_id for item in bundle.modifiers},
    )
    final_result = final_without_trace.model_copy(deep=True)
    final_result.ui_state = {
        **final_result.ui_state,
        "hybrid_trace": {
            "schema_version": record.schema_version,
            "baseline_result_hash": record.baseline_result_hash,
            "final_result_hash": record.final_result_hash,
            "consistency_audit_hash": record.consistency_audit_hash,
            "modifier_bundle_hash": record.modifier_bundle_hash,
            "accepted_proposal_ids": record.accepted_proposal_ids,
            "baseline_diff": record.baseline_diff,
            "replay_hash": record.replay_hash,
            "numeric_authority": "WorldPulse deterministic War Room engine",
        },
    }
    return HybridSimulationOutcome(
        final_result=final_result,
        modifier_bundle=bundle,
        replay_record=record,
        projection_audit=projection_audit,
    )


def replay_hybrid_from_artifacts(
    baseline_payload: dict,
    proposal_payload: dict,
    audit_payload: dict,
    modifier_payload: dict,
    replay_payload: dict,
    projection_audit_payload: dict | None = None,
) -> WarRoomRun:
    baseline = WarRoomRun(**baseline_payload)
    proposals = [AgentActionProposal(**item) for item in proposal_payload.get("proposals", [])]
    audit = ConsistencyAuditReport(**audit_payload)
    bundle = HybridModifierBundle(**modifier_payload)
    record = HybridReplayRecord(**replay_payload)
    projection_audit = AgentActionProjectionAudit.model_validate(projection_audit_payload) if projection_audit_payload else None
    verify_modifier_bundle(bundle)

    proposal_ids = {proposal.proposal_id for proposal in proposals}
    accepted_ids = sorted(decision.proposal_id for decision in audit.proposal_decisions if decision.decision == "accepted")
    if sorted(bundle.accepted_proposal_ids) != accepted_ids:
        raise ValueError("Stored modifier bundle does not match accepted audit decisions")
    if not set(bundle.accepted_proposal_ids).issubset(proposal_ids):
        raise ValueError("Stored modifier bundle references a missing proposal")
    if stable_hash(baseline.model_dump(mode="json")) != record.baseline_result_hash:
        raise ValueError("Stored hybrid baseline hash mismatch")
    if bundle.bundle_hash != record.modifier_bundle_hash or audit.audit_hash != record.consistency_audit_hash:
        raise ValueError("Stored hybrid audit chain hash mismatch")
    if projection_audit is not None:
        verify_action_projection_audit(projection_audit)
        if projection_audit.consistency_audit_hash != audit.audit_hash:
            raise ValueError("Stored action projection audit consistency hash mismatch")
        if projection_audit.final_result_hash != record.final_result_hash:
            raise ValueError("Stored action projection audit final hash mismatch")

    replayed = run_war_room(WarRoomScenarioRequest(**bundle.scenario_patch))
    if stable_hash(replayed.model_dump(mode="json")) != record.final_result_hash:
        raise ValueError("Offline hybrid replay did not reproduce the final result hash")
    return replayed
