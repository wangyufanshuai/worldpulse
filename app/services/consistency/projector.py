from __future__ import annotations

from typing import Protocol

from app.core.models import RunArtifactSummary

from .models import ConsistencyAuditReport


class LifecycleRepository(Protocol):
    def add_artifact(self, run_id: str, artifact_type: str, schema_version: str, content: dict) -> RunArtifactSummary: ...
    def append_event(self, run_id: str, event_type: str, phase: str, title: str, detail: str, *, payload: dict | None = None): ...


def project_consistency_audit(run_id: str, report: ConsistencyAuditReport, repository: LifecycleRepository) -> RunArtifactSummary:
    """Persist a report as an immutable lifecycle artifact and emit its audit event."""

    artifact = repository.add_artifact(
        run_id,
        "consistency_audit",
        report.schema_version,
        report.model_dump(mode="json"),
    )
    repository.append_event(
        run_id,
        "CONSISTENCY",
        "consistency_audit",
        "Consistency audit completed",
        report.summary.get("message_zh", "一致性审计已完成。"),
        payload={
            "overall_status": report.overall_status,
            "evaluated_rule_count": report.evaluated_rule_count,
            "skipped_rule_count": report.skipped_rule_count,
            "finding_count": len(report.findings),
            "audit_hash": report.audit_hash,
            "artifact_id": artifact.artifact_id,
            "read_only": True,
        },
    )
    return artifact
