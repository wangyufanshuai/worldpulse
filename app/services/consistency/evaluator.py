from __future__ import annotations

from datetime import datetime

from app.core.models import WarRoomRun
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext

from .actions import evaluate_action_proposals
from .hashing import stable_hash
from .models import ConsistencyAuditReport
from .rules import RULES


def evaluate_war_room_result(
    result: WarRoomRun,
    *,
    run_id: str,
    created_at: str | None = None,
    proposals: list[AgentActionProposal] | None = None,
    constraint_context: AgentConstraintContext | None = None,
) -> ConsistencyAuditReport:
    """Audit a War Room result without mutating it or recalculating the simulation."""

    result_payload = result.model_dump(mode="json")
    deterministic_result_hash = stable_hash(result_payload)
    proposals = proposals or []
    inactive_rule_names = {"capability_constraints", "resource_constraints"} if proposals else set()
    evaluations = [rule(result) for rule in RULES if rule.__name__ not in inactive_rule_names]
    proposal_decisions = evaluate_action_proposals(proposals, constraint_context) if proposals else []
    findings = [finding for evaluation in evaluations for finding in evaluation.findings]
    findings.extend(finding for decision in proposal_decisions for finding in decision.rule_findings)
    action_evaluated = sum(1 for decision in proposal_decisions if decision.decision != "not_evaluated")
    action_skipped = len(proposal_decisions) - action_evaluated
    evaluated_count = sum(1 for evaluation in evaluations if evaluation.evaluated) + action_evaluated
    skipped_count = sum(1 for evaluation in evaluations if not evaluation.evaluated) + action_skipped
    errors = sum(1 for finding in findings if finding.severity == "error")
    warnings = sum(1 for finding in findings if finding.severity == "warning")
    not_evaluated = sum(1 for finding in findings if finding.status == "not_evaluated")

    if not evaluated_count:
        overall_status = "not_evaluated"
    elif errors:
        overall_status = "failed"
    elif warnings or skipped_count:
        overall_status = "warning"
    else:
        overall_status = "passed"

    summary = {
        "error_count": errors,
        "warning_count": warnings,
        "not_evaluated_count": not_evaluated,
        "passed_rule_count": max(0, evaluated_count - sum(1 for evaluation in evaluations if evaluation.findings)),
        "message_zh": _summary_message(overall_status, errors, warnings, skipped_count),
        "read_only": True,
        "agent_action_count": len(proposals),
        "agent_actor_count": len({proposal.actor_id for proposal in proposals}),
        "accepted_action_count": sum(1 for decision in proposal_decisions if decision.decision == "accepted"),
        "rejected_action_count": sum(1 for decision in proposal_decisions if decision.decision == "rejected"),
        "needs_revision_action_count": sum(1 for decision in proposal_decisions if decision.decision == "needs_revision"),
        "not_evaluated_action_count": sum(1 for decision in proposal_decisions if decision.decision == "not_evaluated"),
        "constrained_action_count": sum(1 for decision in proposal_decisions if decision.outcome == "constrained"),
        "expired_action_count": sum(1 for decision in proposal_decisions if decision.outcome == "expired"),
        "action_pass_rate": round(
            sum(1 for decision in proposal_decisions if decision.outcome == "accepted") / len(proposal_decisions),
            4,
        ) if proposal_decisions else None,
        "action_audit_rule_version": "worldpulse-consistency.v1.2",
        "action_audit_count": len(proposal_decisions),
    }
    schema_version = "consistency-audit.v2" if proposals else "consistency-audit.v1"
    audit_payload = {
        "schema_version": schema_version,
        "evaluator_version": "worldpulse-consistency.v0.8",
        "overall_status": overall_status,
        "summary": summary,
        "findings": [finding.model_dump(mode="json") for finding in findings],
        "proposal_decisions": [decision.model_dump(mode="json") for decision in proposal_decisions],
        "evaluated_rule_count": evaluated_count,
        "skipped_rule_count": skipped_count,
        "deterministic_result_hash": deterministic_result_hash,
    }
    return ConsistencyAuditReport(
        **audit_payload,
        run_id=run_id,
        audit_hash=stable_hash(audit_payload),
        created_at=created_at or datetime.now().isoformat(timespec="milliseconds"),
    )


def _summary_message(status: str, errors: int, warnings: int, skipped: int) -> str:
    if status == "failed":
        return f"发现 {errors} 个确定性合同错误；结果保持只读，未执行自动修正。"
    if status == "warning":
        return f"已完成可用规则审计；{warnings} 个警告，{skipped} 条规则因缺少结构化输入未评估。"
    if status == "not_evaluated":
        return "没有足够的结构化输入执行一致性评估。"
    return "所有可用的一致性规则均通过；审计未修改确定性结果。"
