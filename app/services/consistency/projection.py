from __future__ import annotations

from app.services.agent_contract.models import AgentActionProposal

from .hashing import stable_hash
from .models import AgentActionDecision, AgentActionProjectionAudit, AgentActionProjectionRecord


def build_action_projection_audit(
    *,
    run_id: str,
    consistency_audit_hash: str,
    final_result_hash: str,
    proposals: list[AgentActionProposal],
    decisions: list[AgentActionDecision],
    projection_mode: str,
    projected_ids: set[str] | None = None,
    modifier_hashes: dict[str, str] | None = None,
    modifier_ids: dict[str, str] | None = None,
) -> AgentActionProjectionAudit:
    projected_ids = projected_ids or set()
    modifier_hashes = modifier_hashes or {}
    modifier_ids = modifier_ids or {}
    proposal_ids = {proposal.proposal_id for proposal in proposals}
    records: list[AgentActionProjectionRecord] = []
    for decision in sorted(decisions, key=lambda item: item.proposal_id):
        if decision.proposal_id not in proposal_ids:
            continue
        if decision.proposal_id in projected_ids:
            status = "projected"
        elif decision.outcome == "constrained":
            status = "constrained"
        elif decision.outcome == "expired":
            status = "expired"
        elif decision.decision == "rejected":
            status = "blocked"
        else:
            status = "not_projected"
        projection_payload = {
            "proposal_id": decision.proposal_id,
            "input_hash": decision.input_hash,
            "rule_version": decision.rule_version,
            "outcome": decision.outcome,
            "projection_status": status,
            "final_result_hash": final_result_hash,
            "modifier_hash": modifier_hashes.get(decision.proposal_id),
        }
        records.append(AgentActionProjectionRecord(
            proposal_id=decision.proposal_id,
            input_hash=decision.input_hash,
            rule_version=decision.rule_version,
            outcome=decision.outcome,
            projection_status=status,
            projection_hash=modifier_hashes.get(decision.proposal_id) or stable_hash(projection_payload),
            modifier_id=modifier_ids.get(decision.proposal_id),
            rejection_reason=decision.rejection_reason,
            final_result_hash=final_result_hash,
        ))
    payload = {
        "schema_version": "agent-action-projection-audit.v1",
        "run_id": run_id,
        "consistency_audit_hash": consistency_audit_hash,
        "final_result_hash": final_result_hash,
        "projection_mode": projection_mode,
        "records": [record.model_dump(mode="json") for record in records],
        "projected_count": sum(record.projection_status == "projected" for record in records),
        "constrained_count": sum(record.projection_status == "constrained" for record in records),
        "blocked_count": sum(record.projection_status == "blocked" for record in records),
        "expired_count": sum(record.projection_status == "expired" for record in records),
    }
    return AgentActionProjectionAudit(**payload, audit_hash=stable_hash(payload))
