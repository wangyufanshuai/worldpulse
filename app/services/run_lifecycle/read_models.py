"""Read models for lifecycle projection and audit views.

These queries are intentionally side-effect free.  They compose the public
Run Control contracts and verified Artifact Store reads without participating
in job state transitions or writing ``research_runs``.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.services.project_store import connect, init_db, loads

from . import artifacts as artifact_store
from .mappers import attempt_from_row, event_from_row, job_from_row


def projected_result_run_id(run_id: str) -> str | None:
    job = _get_job(run_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT run_id, data_snapshot FROM research_runs WHERE project_id = ? ORDER BY completed_at DESC",
            (job.project_id,),
        ).fetchall()
    for row in rows:
        if loads(row["data_snapshot"], {}).get("lifecycle_job_id") == run_id:
            return str(row["run_id"])
    return None


def audit_view(run_id: str) -> dict:
    job = _get_job(run_id)
    events = _events(run_id)
    artifacts = artifact_store.get_artifacts(run_id)
    steps = _steps(run_id)
    attempts = _attempts(run_id)
    hybrid_record = artifact_store.get_latest_artifact_content(run_id, "hybrid_replay_record")
    negotiation_summary = artifact_store.get_latest_artifact_content(run_id, "negotiation_summary")
    return {
        "run": job.model_dump(),
        "events": [event.model_dump() for event in events],
        "artifacts": [artifact.model_dump() for artifact in artifacts],
        "steps": [step.model_dump() for step in steps],
        "attempts": [attempt.model_dump() for attempt in attempts],
        "integrity": artifact_store.verify_artifacts(run_id),
        "consistency_audit": artifact_store.get_latest_artifact_content(run_id, "consistency_audit"),
        "action_projection_audit": artifact_store.get_latest_artifact_content(run_id, "agent_action_projection_audit"),
        "agent_runtime": artifact_store.get_latest_artifact_content(run_id, "agent_runtime_audit"),
        "metrics": artifact_store.get_latest_artifact_content(run_id, "lifecycle_metrics"),
        "hybrid": {
            "replay_record": hybrid_record,
            "modifier_bundle": artifact_store.get_latest_artifact_content(run_id, "deterministic_action_modifiers"),
            "baseline_result": artifact_store.get_latest_artifact_content(run_id, "war_room_result"),
            "final_result": artifact_store.get_latest_artifact_content(run_id, "hybrid_war_room_result"),
        } if hybrid_record else None,
        "negotiation": negotiation_summary,
    }


def _get_job(run_id: str) -> Any:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
    return job_from_row(row)


def _events(run_id: str) -> list:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? ORDER BY seq ASC",
            (run_id,),
        ).fetchall()
    return [event_from_row(row) for row in rows]


def _steps(run_id: str) -> list:
    from .steps import get_steps

    return get_steps(run_id)


def _attempts(run_id: str) -> list:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_attempts WHERE run_id = ? ORDER BY attempt_number ASC",
            (run_id,),
        ).fetchall()
    return [attempt_from_row(row) for row in rows]
