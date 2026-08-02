"""Evaluation runtime coordination adapter.

The coordinator owns scheduling, child-run harvesting and finalization. It
uses the application service for public reads and a small set of explicit
compatibility hooks while persistence repositories are migrated separately.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import os
from typing import Any
from uuid import uuid4

from fastapi import HTTPException

from app.core.models import RunJobCreateRequest, WarRoomScenarioRequest
from app.db.postgres import is_postgres_url
from app.services.consistency.hashing import stable_hash
from app.services.evaluation.gates import list_verification_results, verify_member
from app.services.evaluation.mappers import batch_from_row
from app.services.project_store import connect, dumps, loads
from app.services.run_lifecycle import repository as lifecycle_repository

TERMINAL = {"completed", "cancelled", "failed"}
def reconcile_evaluation(service: Any, *, worker_id: str | None = None) -> int:
    """Schedule pending members and harvest terminal real v2 child runs."""
    changed = 0
    worker_id = worker_id or f"evaluation_{uuid4().hex[:12]}"
    now = datetime.now().isoformat(timespec="milliseconds")
    lease = (datetime.now() + timedelta(seconds=60)).isoformat(timespec="milliseconds")
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        lock_clause = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
        batch_row = conn.execute(
            f"""SELECT * FROM evaluation_batches
                WHERE status IN ('queued','running','pausing','cancelling')
                  AND (coordinator_lease_expires_at IS NULL OR coordinator_lease_expires_at < ? OR coordinator_worker_id = ?)
                ORDER BY created_at LIMIT 1{lock_clause}""",
            (now, worker_id),
        ).fetchone()
        if batch_row is not None:
            conn.execute(
                """UPDATE evaluation_batches
                   SET coordinator_worker_id=?, coordinator_lease_expires_at=?,
                       coordinator_attempt_count=coordinator_attempt_count+1
                   WHERE batch_id=?""",
                (worker_id, lease, batch_row["batch_id"]),
            )
    batches = [batch_row] if batch_row is not None else []
    for batch_row in batches:
        batch = batch_from_row(batch_row)
        if batch.status in {"queued", "running"}:
            project_id = service._ensure_system_project(batch.organization_id)
            with connect() as conn:
                inflight = int(conn.execute("SELECT COUNT(*) FROM evaluation_members WHERE batch_id = ? AND status IN ('queued','running')", (batch.batch_id,)).fetchone()[0])
                capacity = max(1, min(8, int(os.getenv("WORLDPULSE_EVALUATION_MAX_IN_FLIGHT", "2")))) - inflight
                pending = conn.execute("SELECT m.*, c.input_json FROM evaluation_members m JOIN evaluation_cases c ON c.case_id = m.case_id WHERE m.batch_id = ? AND m.status = 'pending' ORDER BY m.created_at LIMIT ?", (batch.batch_id, min(1, max(0, capacity)))).fetchall()
            for member in pending:
                scenario = WarRoomScenarioRequest(**{**loads(member["input_json"], {}), "seed": int(member["seed"])})
                request = RunJobCreateRequest(engine_mode=member["engine_mode"], scenario=scenario, seed=int(member["seed"]))
                job = lifecycle_repository.create_job(project_id, request, evaluation_batch_id=batch.batch_id, evaluation_member_id=member["member_id"], runtime_profile=batch.runtime_profile)
                with connect() as conn:
                    conn.execute("UPDATE evaluation_members SET run_id = ?, status = 'queued', updated_at = ? WHERE member_id = ? AND status = 'pending'", (job.run_id, datetime.now().isoformat(timespec="milliseconds"), member["member_id"]))
                changed += 1
            with connect() as conn:
                conn.execute("UPDATE evaluation_batches SET status = 'running', updated_at = ? WHERE batch_id = ? AND status = 'queued'", (datetime.now().isoformat(timespec="milliseconds"), batch.batch_id))
        for member in service.list_members(batch.batch_id):
            if not member.run_id or member.status in TERMINAL:
                continue
            try:
                job = lifecycle_repository.get_job(member.run_id)
            except HTTPException:
                continue
            if job.status not in TERMINAL:
                mapped = "paused" if job.status in {"paused", "pausing"} else "running" if job.status in {"preparing", "running", "cancelling"} else "queued"
                if mapped != member.status:
                    with connect() as conn:
                        conn.execute("UPDATE evaluation_members SET status = ?, updated_at = ? WHERE member_id = ?", (mapped, datetime.now().isoformat(timespec="milliseconds"), member.member_id))
                    changed += 1
                continue
            artifact_type = "hybrid_war_room_result" if member.engine_mode == "hybrid" else "negotiation_final_result" if member.engine_mode == "negotiation" else "war_room_result"
            result = lifecycle_repository.get_latest_artifact_content(member.run_id, artifact_type) or {}
            result_hash = stable_hash(result) if result else None
            status = "completed" if job.status == "completed" else job.status
            with connect() as conn:
                conn.execute("UPDATE evaluation_members SET status = ?, result_hash = ?, artifact_refs_json = ?, metrics_json = ?, error_code = ?, error_message = ?, updated_at = ?, completed_at = CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE completed_at END WHERE member_id = ?", (status, result_hash, dumps([artifact_type]), dumps({"provider_calls": 0 if batch.runtime_profile.get("provider") == "mock" else None, "artifact_integrity": lifecycle_repository.verify_artifacts(member.run_id)}), job.error_code, job.error_message, datetime.now().isoformat(timespec="milliseconds"), status, datetime.now().isoformat(timespec="milliseconds"), member.member_id))
            changed += 1
        current = service.get_batch(batch.batch_id)
        members = service.list_members(batch.batch_id)
        completed_now = sum(item.status == "completed" for item in members)
        failed_now = sum(item.status in {"failed", "cancelled"} for item in members)
        with connect() as conn:
            conn.execute(
                "UPDATE evaluation_batches SET completed_members=?, failed_members=?, updated_at=? WHERE batch_id=?",
                (completed_now, failed_now, datetime.now().isoformat(timespec="milliseconds"), batch.batch_id),
            )
        if current.status == "pausing" and all(item.status in {"pending", "paused", *TERMINAL} for item in members):
            with connect() as conn:
                conn.execute("UPDATE evaluation_batches SET status = 'paused', updated_at = ? WHERE batch_id = ?", (datetime.now().isoformat(timespec="milliseconds"), batch.batch_id))
        elif current.status == "cancelling" and all(item.status in TERMINAL for item in members):
            now = datetime.now().isoformat(timespec="milliseconds")
            with connect() as conn:
                conn.execute("UPDATE evaluation_batches SET status = 'cancelled', failed_members = ?, updated_at = ?, completed_at = ? WHERE batch_id = ?", (len(members), now, now, batch.batch_id))
                conn.execute("UPDATE evaluation_batches SET coordinator_worker_id=NULL, coordinator_lease_expires_at=NULL WHERE batch_id=? AND coordinator_worker_id=?", (batch.batch_id, worker_id))
            continue
        service._finalize_if_ready(batch.batch_id)
        with connect() as conn:
            conn.execute(
                "UPDATE evaluation_batches SET coordinator_worker_id=NULL, coordinator_lease_expires_at=NULL WHERE batch_id=? AND coordinator_worker_id=?",
                (batch.batch_id, worker_id),
            )
    return changed

def finalize_evaluation_batch(service: Any, batch_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM evaluation_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        member_rows = conn.execute("SELECT status FROM evaluation_members WHERE batch_id = ?", (batch_id,)).fetchall()
    if row is None:
        return
    total = len(member_rows)
    completed = sum(1 for item in member_rows if item["status"] == "completed")
    failed = sum(1 for item in member_rows if item["status"] in {"failed", "cancelled"})
    if completed + failed < total:
        return
    batch = batch_from_row(row)
    members = service.list_members(batch_id)
    deterministic = {item.case_id: item.result_hash for item in members if item.engine_mode == "deterministic" and item.status == "completed"}
    for member in members:
        if member.status == "completed":
            verify_member(batch, member, expected_baseline_hash=deterministic.get(member.case_id))
    verification = list_verification_results(batch_id)
    by_key: dict[str, list] = {}
    for item in verification:
        by_key.setdefault(item.check_key, []).append(item)
    safety_pass = failed == 0 and len(verification) == completed * 10 and all(item.status in {"passed", "not_applicable"} for item in verification)
    critical_items = by_key.get("critical_violation_recall", [])
    critical_total = sum(int(item.observed.get("critical", 0)) for item in critical_items)
    critical_caught = sum(int(item.observed.get("caught", 0)) for item in critical_items)
    metrics: dict[str, Any] = {
        "member_count": total,
        "completed": completed,
        "failed": failed,
        "numeric_authority_accepted": sum(int(item.observed.get("accepted", 0)) for item in by_key.get("numeric_authority_accepted", [])),
        "critical_false_accept": sum(int(item.observed.get("false_accepts", 0)) for item in by_key.get("critical_false_accept", [])),
        "critical_violation_recall": 1.0 if critical_total == 0 else critical_caught / critical_total,
        "illegal_projection": sum(int(item.observed.get("illegal_projections", 0)) for item in by_key.get("illegal_projection", [])),
        "deterministic_baseline_match": int(all(item.status != "failed" for item in by_key.get("baseline_hash_match", []))),
        "audit_chain_complete": int(all(item.status != "failed" for item in by_key.get("runtime_lineage", []))),
        "artifact_replay_integrity": int(all(item.status != "failed" for key in ("artifact_lineage_integrity", "offline_replay") for item in by_key.get(key, []))),
        "replay_provider_calls": sum(int(item.observed.get("provider_calls", 0)) for item in by_key.get("offline_replay", [])),
        "organization_scope_violations": sum(int(item.observed.get("violations", 0)) for item in by_key.get("organization_scope", [])),
        "verification_result_count": len(verification),
    }
    if batch.evaluation_track == "historical_blind":
        try:
            historical_metrics = service._historical_observation_metrics(batch, members)
            metrics["historical_observation"] = historical_metrics
        except Exception as exc:
            safety_pass = False
            metrics["historical_observation"] = {"status": "failed", "error": type(exc).__name__, "blind_labels_redacted": True}
            from app.services.reviews import create_review_case
            create_review_case("historical_label_integrity", "evaluation_batch", batch_id, "Historical label comparison failed closed", severity="critical", payload={"error": type(exc).__name__})
    report_hash = stable_hash({"batch_id": batch_id, "metrics": metrics})
    now = datetime.now().isoformat(timespec="milliseconds")
    with connect() as conn:
        conn.execute("UPDATE evaluation_batches SET status = ?, completed_members = ?, failed_members = ?, safety_status = ?, quality_status = ?, metrics_json = ?, report_hash = ?, updated_at = ?, completed_at = ? WHERE batch_id = ?", ("completed" if failed == 0 else "failed", completed, failed, "passed" if safety_pass else "failed", "observed", dumps(metrics), report_hash, now, now, batch_id))
        for key in ("numeric_authority_accepted", "critical_false_accept", "critical_violation_recall", "illegal_projection", "deterministic_baseline_match", "audit_chain_complete", "artifact_replay_integrity", "replay_provider_calls", "organization_scope_violations"):
            value = metrics[key]
            passed = (value == 0 if key in {"numeric_authority_accepted", "critical_false_accept", "illegal_projection", "replay_provider_calls", "organization_scope_violations"} else value == 1 or value == 1.0)
            conn.execute("INSERT INTO evaluation_metrics(metric_id,batch_id,scope,metric_key,value_json,passed,metric_hash,created_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(metric_hash) DO NOTHING", (f"metric_{uuid4().hex[:16]}", batch_id, "safety", key, dumps(value), 1 if passed and safety_pass else 0, stable_hash({"batch_id": batch_id, "metric": key, "value": value}), now))
    service.append_event(batch_id, "SNAPSHOT", "evaluation_report", "Evaluation batch finalized", "Safety gate is fail-closed and metrics are immutable", {"safety_status": "passed" if safety_pass else "failed", "report_hash": report_hash})
