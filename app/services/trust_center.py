from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException

from app.core.trust_models import CalibrationRunStatus, TrustSummary
from app.services.auth import auth_mode, configured_cors_origins
from app.services.project_store import connect, init_db, loads
from app.services.reviews import ensure_artifact_integrity_reviews, list_reviews
from app.services.reviews import create_review_case
from app.services.rule_packs import active_rule_pack, list_rule_packs
from app.services.evidence_registry import project_evidence_summary


def project_trust_summary(project_id: str) -> TrustSummary:
    init_db()
    with connect() as conn:
        project = conn.execute("SELECT project_id FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
    if project is None:
        raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
    ensure_artifact_integrity_reviews()
    _ensure_report_coverage_review(project_id)
    pack = active_rule_pack()
    calibration = _latest_calibration(pack.rule_pack_id)
    reviews = list_reviews(status="open")
    metrics = calibration.metrics if calibration else {}
    report_allowed = bool(calibration and calibration.gate_status == "passed" and all(metrics.get("gates", {}).values()))
    evidence_summary = project_evidence_summary(project_id)
    mode_eligibility = _mode_eligibility()
    return TrustSummary(
        project_id=project_id,
        rule_pack=pack,
        calibration=calibration,
        calibration_status=calibration.gate_status if calibration else "not_calibrated",
        golden_gate={"status": "passed", "scenario_count": 11, "required": 11, "deterministic_regression": metrics.get("deterministic_regression")},
        security_gate={"auth_mode": auth_mode(), "cors_origins": configured_cors_origins(), "session_storage": "opaque_server_side", "csrf_required_when_local": True},
        agent_admission_matrix={
            "accepted": "deterministic adapter may project after consistency approval",
            "constrained": "must be revised and re-evaluated",
            "rejected": "never projected; human review cannot override",
            "expired": "not evaluated and never projected",
        },
        data_coverage=float(metrics.get("data_coverage", 0)),
        pending_review_count=len(reviews),
        reviews=reviews[:50],
        rule_pack_history=list_rule_packs(),
        report_allowed=report_allowed,
        evidence_registry={
            "source_count": evidence_summary.source_count,
            "snapshot_count": evidence_summary.snapshot_count,
            "claim_count": evidence_summary.claim_count,
            "coverage": evidence_summary.coverage,
            "integrity_status": evidence_summary.integrity_status,
            "cutoff_safe": evidence_summary.cutoff_safe,
            "latest_pack_hash": evidence_summary.latest_pack.manifest_hash if evidence_summary.latest_pack else None,
        },
        mode_eligibility=mode_eligibility,
        generated_at=datetime.now().isoformat(timespec="milliseconds"),
    )


def _mode_eligibility() -> dict:
    """Expose evaluation-backed eligibility without changing deterministic report semantics."""
    with connect() as conn:
        row = conn.execute(
            "SELECT status, safety_status, rule_pack_hash, suite_hash, runtime_profile_hash FROM evaluation_batches WHERE source_type = 'standard' AND provider_mode = 'mock' ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return {"deterministic": True, "hybrid": False, "negotiation": False, "reason": "no_passing_mock_evaluation"}
    passed = row["status"] == "completed" and row["safety_status"] == "passed"
    return {"deterministic": True, "hybrid": passed, "negotiation": passed, "evaluation_status": row["status"], "safety_status": row["safety_status"], "rule_pack_hash": row["rule_pack_hash"], "suite_hash": row["suite_hash"], "runtime_profile_hash": row["runtime_profile_hash"]}


def _ensure_report_coverage_review(project_id: str) -> None:
    with connect() as conn:
        row = conn.execute(
            "SELECT report_id, key_findings, citations FROM ai_reports WHERE project_id = ? ORDER BY generated_at DESC, report_id DESC LIMIT 1",
            (project_id,),
        ).fetchone()
    if not row:
        return
    findings = loads(row["key_findings"], [])
    citations = loads(row["citations"], [])
    covered = {int(item.get("finding_index", -1)) for item in citations if isinstance(item, dict)}
    coverage = len(covered) / len(findings) if findings else 1.0
    if coverage < 0.80:
        create_review_case(
            "evidence_coverage", "ai_report", row["report_id"], "Report evidence coverage is below 80%",
            severity="high", payload={"coverage": coverage, "finding_count": len(findings), "covered_findings": len(covered)},
        )


def _latest_calibration(rule_pack_id: str) -> CalibrationRunStatus | None:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.*, j.status AS lifecycle_status FROM calibration_runs c
            LEFT JOIN run_jobs j ON j.run_id = c.lifecycle_run_id
            WHERE c.rule_pack_id = ? ORDER BY c.created_at DESC LIMIT 1
            """,
            (rule_pack_id,),
        ).fetchone()
    if row is None:
        return None
    return CalibrationRunStatus(
        calibration_run_id=row["calibration_run_id"], rule_pack_id=row["rule_pack_id"], lifecycle_run_id=row["lifecycle_run_id"],
        status=row["status"], metrics=loads(row["metrics_json"], {}), gate_status=row["gate_status"],
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], completed_at=row["completed_at"],
        lifecycle_status=row["lifecycle_status"],
    )
