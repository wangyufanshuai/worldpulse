from __future__ import annotations

from datetime import datetime

from app.core.models import WarRoomRun

from .hashing import stable_hash
from .models import ConsistencyAuditReport
from .rules import RULES


def evaluate_war_room_result(
    result: WarRoomRun,
    *,
    run_id: str,
    created_at: str | None = None,
) -> ConsistencyAuditReport:
    """Audit a War Room result without mutating it or recalculating the simulation."""

    result_payload = result.model_dump(mode="json")
    deterministic_result_hash = stable_hash(result_payload)
    evaluations = [rule(result) for rule in RULES]
    findings = [finding for evaluation in evaluations for finding in evaluation.findings]
    evaluated_count = sum(1 for evaluation in evaluations if evaluation.evaluated)
    skipped_count = len(evaluations) - evaluated_count
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
        "agent_action_count": 0,
    }
    audit_payload = {
        "schema_version": "consistency-audit.v1",
        "evaluator_version": "worldpulse-consistency.v0.8",
        "overall_status": overall_status,
        "summary": summary,
        "findings": [finding.model_dump(mode="json") for finding in findings],
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
