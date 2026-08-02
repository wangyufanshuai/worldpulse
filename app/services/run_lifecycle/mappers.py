"""Persistence-to-domain mapping for the Run Control Plane.

The functions accept SQLite rows, PostgreSQL ``HybridRow`` objects, and
mapping-shaped test doubles.  They do not open connections or perform state
transitions.
"""

from __future__ import annotations

from typing import Any, Literal

from app.core.models import RunArtifactSummary, RunAttemptRecord, RunJobStatus, RunLifecycleEvent
from app.services.project_store import loads

from .integrity import artifact_digest


def job_from_row(row: Any) -> RunJobStatus:
    return RunJobStatus(
        run_id=row["run_id"],
        project_id=row["project_id"],
        engine_mode=row["engine_mode"],
        status=row["status"],
        current_phase=row["current_phase"],
        progress=float(row["progress"] or 0),
        seed=row["seed"],
        parent_run_id=row["parent_run_id"],
        result_run_id=row["result_run_id"],
        scenario=loads(row["scenario_json"], {}),
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        started_at=row["started_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        cancel_requested_at=row["cancel_requested_at"],
        pause_requested_at=row["pause_requested_at"],
        worker_id=row["worker_id"],
        lease_expires_at=row["lease_expires_at"],
        attempt_count=int(row["attempt_count"] or 0),
        current_attempt_id=row["current_attempt_id"],
        max_attempts=int(row["max_attempts"] or 3),
        next_attempt_at=row["next_attempt_at"],
        terminal_reason=row["terminal_reason"],
        job_kind=row["job_kind"] if "job_kind" in row.keys() else "war_room",
        agent_pack_id=row["agent_pack_id"] if "agent_pack_id" in row.keys() else None,
        agent_pack_hash=row["agent_pack_hash"] if "agent_pack_hash" in row.keys() else None,
        scenario_draft_id=row["scenario_draft_id"] if "scenario_draft_id" in row.keys() else None,
        scenario_draft_hash=row["scenario_draft_hash"] if "scenario_draft_hash" in row.keys() else None,
        scenario_evidence_pack_hash=row["scenario_evidence_pack_hash"] if "scenario_evidence_pack_hash" in row.keys() else None,
        rule_pack_id=row["rule_pack_id"] if "rule_pack_id" in row.keys() else None,
        rule_pack_hash=row["rule_pack_hash"] if "rule_pack_hash" in row.keys() else None,
        evaluation_batch_id=row["evaluation_batch_id"] if "evaluation_batch_id" in row.keys() else None,
        evaluation_member_id=row["evaluation_member_id"] if "evaluation_member_id" in row.keys() else None,
        runtime_profile=loads(row["runtime_profile_json"], {}) if "runtime_profile_json" in row.keys() else {},
        runtime_profile_hash=row["runtime_profile_hash"] if "runtime_profile_hash" in row.keys() else None,
    )


def event_from_row(row: Any) -> RunLifecycleEvent:
    return RunLifecycleEvent(
        run_id=row["run_id"],
        seq=int(row["seq"]),
        event_type=row["event_type"],
        phase=row["phase"],
        tick=row["tick"],
        title=row["title"],
        detail=row["detail"],
        payload=loads(row["payload"], {}),
        created_at=row["created_at"],
    )


def artifact_from_row(row: Any) -> RunArtifactSummary:
    integrity: Literal["verified", "failed"] = (
        "verified"
        if "content_json" not in row.keys() or artifact_digest(row["content_json"]) == row["sha256"]
        else "failed"
    )
    return RunArtifactSummary(
        artifact_id=row["artifact_id"],
        run_id=row["run_id"],
        artifact_type=row["artifact_type"],
        schema_version=row["schema_version"],
        sha256=row["sha256"],
        created_at=row["created_at"],
        attempt_id=row["attempt_id"] if "attempt_id" in row.keys() else None,
        step_id=row["step_id"] if "step_id" in row.keys() else None,
        artifact_version=int(row["artifact_version"] or 1) if "artifact_version" in row.keys() else 1,
        supersedes_artifact_id=row["supersedes_artifact_id"] if "supersedes_artifact_id" in row.keys() else None,
        integrity_status=integrity,
    )


def attempt_from_row(row: Any) -> RunAttemptRecord:
    return RunAttemptRecord(
        attempt_id=row["attempt_id"],
        run_id=row["run_id"],
        worker_id=row["worker_id"],
        attempt_number=int(row["attempt_number"]),
        status=row["status"],
        resume_from_step=row["resume_from_step"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        error_code=row["error_code"],
        error_message=row["error_message"],
    )
