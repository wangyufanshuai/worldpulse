from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


AuditStatus = Literal["passed", "warning", "failed", "not_evaluated"]
FindingStatus = Literal["warning", "failed", "not_evaluated"]
FindingCategory = Literal["schema", "capability", "resource", "causal", "temporal", "evidence"]
FindingSeverity = Literal["info", "warning", "error"]


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


class ConsistencyAuditReport(BaseModel):
    schema_version: str = "consistency-audit.v1"
    evaluator_version: str = "worldpulse-consistency.v0.8"
    run_id: str
    overall_status: AuditStatus
    summary: dict[str, Any] = Field(default_factory=dict)
    findings: list[ConsistencyFinding] = Field(default_factory=list)
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
