from __future__ import annotations

from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext

from .hashing import stable_hash
from .models import AgentActionDecision
from .rules import _finding


ALLOWED_DIRECTIONS = {
    "diplomatic_signal": {"deescalate", "deter", "inform"},
    "alliance_request": {"coordinate", "assist"},
    "alliance_response": {"coordinate", "assist", "observe"},
    "sanction_proposal": {"deter", "stabilize"},
    "trade_reroute_request": {"reroute", "stabilize"},
    "public_narrative": {"inform", "stabilize", "deter"},
    "humanitarian_offer": {"assist", "stabilize"},
    "deescalation_offer": {"deescalate", "stabilize"},
    "intelligence_request": {"observe", "inform"},
}


def evaluate_action_proposals(
    proposals: list[AgentActionProposal],
    context: AgentConstraintContext | None,
) -> list[AgentActionDecision]:
    decisions = []
    consumed: dict[tuple[str, int], int] = {}
    for proposal in sorted(proposals, key=lambda item: (item.turn, item.proposal_id)):
        findings = []
        if context is None:
            findings.append(_finding(
                "CONSISTENCY.ACTION_CONTEXT.V1",
                category="capability",
                status="not_evaluated",
                severity="info",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="缺少显式仿真能力信封，动作不能进入准入状态。",
                expected="AgentConstraintContext",
                actual="unavailable",
                suggested_action="提供版本化能力信封和动作预算。",
            ))
            decisions.append(_decision(proposal, "not_evaluated", findings))
            continue

        allowed = context.actor_capabilities.get(proposal.actor_id)
        if allowed is None:
            findings.append(_finding(
                "CONSISTENCY.ACTION_CAPABILITY.V1",
                category="capability",
                status="not_evaluated",
                severity="info",
                subject_type="agent_actor",
                subject_id=proposal.actor_id,
                message_zh="能力信封中没有该 actor，动作未评估。",
                expected="actor in capability envelope",
                actual=proposal.actor_id,
                suggested_action="补充明确的仿真 actor 能力，不得根据常识推测。",
            ))
        elif proposal.action_type not in allowed:
            findings.append(_finding(
                "CONSISTENCY.ACTION_CAPABILITY.V1",
                category="capability",
                status="failed",
                severity="error",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="动作类型超出该 actor 的显式仿真能力信封。",
                expected=allowed,
                actual=proposal.action_type,
                evidence_refs=[proposal.actor_id],
                suggested_action="拒绝动作或使用经过批准的 actor/action 配置。",
            ))

        budget_key = (proposal.actor_id, proposal.turn)
        consumed[budget_key] = consumed.get(budget_key, 0) + 1
        budget = context.action_budgets.get(proposal.actor_id)
        if budget is None:
            findings.append(_finding(
                "CONSISTENCY.ACTION_RESOURCE_BUDGET.V1",
                category="resource",
                status="not_evaluated",
                severity="info",
                subject_type="agent_actor",
                subject_id=proposal.actor_id,
                message_zh="未提供该 actor 的每回合动作预算。",
                expected="non-negative action budget",
                actual="unavailable",
                suggested_action="补充显式动作预算后重新评估。",
            ))
        elif consumed[budget_key] > budget:
            findings.append(_finding(
                "CONSISTENCY.ACTION_RESOURCE_BUDGET.V1",
                category="resource",
                status="failed",
                severity="error",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="actor 在当前回合提交的动作数量超过预算。",
                expected={"maximum": budget},
                actual=consumed[budget_key],
                evidence_refs=[proposal.actor_id],
                suggested_action="拒绝超出预算的动作。",
            ))

        unknown_targets = sorted(set(proposal.target_ids) - set(context.known_entities))
        if unknown_targets:
            findings.append(_finding(
                "CONSISTENCY.ACTION_TARGETS.V1",
                category="causal",
                status="failed",
                severity="error",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="动作引用了不存在的目标实体。",
                expected="target in deterministic entity index",
                actual=unknown_targets,
                evidence_refs=proposal.target_ids,
                suggested_action="拒绝动作并修正 target_ids。",
            ))

        unknown_evidence = sorted(set(proposal.evidence_refs) - set(context.known_evidence_refs))
        if unknown_evidence:
            findings.append(_finding(
                "CONSISTENCY.ACTION_EVIDENCE.V1",
                category="evidence",
                status="warning",
                severity="warning",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="动作包含无法解析的证据引用，需要修订。",
                expected="evidence ref in immutable deterministic snapshot",
                actual=unknown_evidence,
                evidence_refs=proposal.evidence_refs,
                suggested_action="用已保存的实体、时间线或 artifact 引用替换。",
            ))

        allowed_directions = ALLOWED_DIRECTIONS[proposal.action_type]
        if proposal.expected_direction not in allowed_directions:
            findings.append(_finding(
                "CONSISTENCY.ACTION_DIRECTION.V1",
                category="causal",
                status="warning",
                severity="warning",
                subject_type="agent_action",
                subject_id=proposal.proposal_id,
                message_zh="动作方向与该 action_type 的合同不一致，需要修订。",
                expected=sorted(allowed_directions),
                actual=proposal.expected_direction,
                evidence_refs=[proposal.proposal_id],
                suggested_action="修订 expected_direction，不要填写目标风险数值。",
            ))

        if any(finding.severity == "error" for finding in findings):
            status = "rejected"
        elif any(finding.status == "not_evaluated" for finding in findings):
            status = "not_evaluated"
        elif any(finding.severity == "warning" for finding in findings):
            status = "needs_revision"
        else:
            status = "accepted"
        decisions.append(_decision(proposal, status, findings))
    return decisions


def _decision(proposal: AgentActionProposal, status: str, findings: list) -> AgentActionDecision:
    explanations = {
        "accepted": "结构、能力信封、动作预算、目标和证据引用均通过合同检查。",
        "rejected": "动作违反强制约束，已拒绝且不会修改确定性世界状态。",
        "needs_revision": "动作未违反强制约束，但证据或方向合同需要修订。",
        "not_evaluated": "缺少显式约束输入，动作保持未评估状态。",
    }
    payload = {
        "proposal_id": proposal.proposal_id,
        "decision": status,
        "rule_findings": [finding.model_dump(mode="json") for finding in findings],
        "evidence_refs": proposal.evidence_refs,
        "explanation_zh": explanations[status],
    }
    return AgentActionDecision(**payload, audit_hash=stable_hash(payload))
