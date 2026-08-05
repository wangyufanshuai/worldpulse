from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


AuditStatus = Literal["passed", "warning", "failed", "not_evaluated"]
FindingStatus = Literal["warning", "failed", "not_evaluated"]
FindingCategory = Literal["schema", "capability", "resource", "causal", "temporal", "evidence"]
FindingSeverity = Literal["info", "warning", "error"]
ActionDecisionStatus = Literal["accepted", "rejected", "needs_revision", "not_evaluated"]
ActionOutcomeStatus = Literal["accepted", "rejected", "constrained", "expired"]
ProjectionStatus = Literal["not_projected", "projected", "constrained", "blocked", "expired"]

ACTION_AUDIT_RULE_VERSION = "worldpulse-consistency.v1.2"


class ConsistencyFinding(BaseModel):
    finding_id: str
    rule_id: str
    category: FindingCategory
    status: FindingStatus
    severity: FindingSeverity
    subject_type: str
    subject_id: str
    message_zh: str
    expected: Any = None
    actual: Any = None
    evidence_refs: list[str] = Field(default_factory=list)
    suggested_action: str = ""


class AgentActionDecision(BaseModel):
    proposal_id: str
    decision: ActionDecisionStatus
    rule_findings: list[ConsistencyFinding] = Field(default_factory=list)
    evidence_refs: list[str] = Field(default_factory=list)
    explanation_zh: str
    audit_hash: str
    # V1.2 additive audit contract. The legacy decision field remains intact
    # for v1/v2 consumers; outcome is the canonical lifecycle status.
    outcome: ActionOutcomeStatus = "accepted"
    input_hash: str = ""
    rule_version: str = ACTION_AUDIT_RULE_VERSION
    rejection_reason: str | None = None
    projection_status: ProjectionStatus = "not_projected"
    projection_hash: str | None = None


class AgentActionProjectionRecord(BaseModel):
    proposal_id: str
    input_hash: str
    rule_version: str
    outcome: ActionOutcomeStatus
    projection_status: ProjectionStatus
    projection_hash: str
    modifier_id: str | None = None
    rejection_reason: str | None = None
    final_result_hash: str


class AgentActionProjectionAudit(BaseModel):
    schema_version: str = "agent-action-projection-audit.v1"
    run_id: str
    consistency_audit_hash: str
    final_result_hash: str
    projection_mode: Literal["hybrid", "audit_only", "negotiation"]
    records: list[AgentActionProjectionRecord] = Field(default_factory=list)
    projected_count: int = 0
    constrained_count: int = 0
    blocked_count: int = 0
    expired_count: int = 0
    audit_hash: str


class ConsistencyAuditReport(BaseModel):
    schema_version: str = "consistency-audit.v1"
    evaluator_version: str = "worldpulse-consistency.v0.8"
    run_id: str
    overall_status: AuditStatus
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[ConsistencyFinding] = Field(default_factory=list)
    proposal_decisions: list[AgentActionDecision] = Field(default_factory=list)
    evaluated_rule_count: int
    skipped_rule_count: int
    deterministic_result_hash: str
    audit_hash: str
    created_at: str


@dataclass(frozen=True)
class RuleEvaluation:
    rule_id: str
    evaluated: bool
    findings: tuple[ConsistencyFinding, ...] = ()
