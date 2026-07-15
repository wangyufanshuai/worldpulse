from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from uuid import uuid4

from fastapi import HTTPException

from app.core.models import (
    RunArtifactSummary,
    RunJobCreateRequest,
    RunJobStatus,
    RunLifecycleEvent,
    WarRoomScenarioRequest,
)
from app.services.project_store import connect, dumps, init_db, loads
from app.services.security import redact_secrets, redact_structure


TERMINAL_STATUSES = {"completed", "cancelled", "failed"}
CLAIMABLE_STATUS = "queued"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def create_job(project_id: str, request: RunJobCreateRequest) -> RunJobStatus:
    init_db()
    scenario = _scenario_payload(request.scenario, request.seed)
    run_id = f"job_{uuid4().hex[:12]}"
    now = now_iso()
    with connect() as conn:
        project = conn.execute("SELECT project_id FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
        conn.execute(
            """
            INSERT INTO run_jobs
            (run_id, project_id, engine_mode, status, current_phase, progress, seed, parent_run_id, scenario_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                project_id,
                _engine_mode(request.engine_mode),
                "queued",
                "scenario_compile",
                0,
                request.seed,
                request.parent_run_id,
                dumps(scenario),
                now,
                now,
            ),
        )
    append_event(
        run_id,
        "WORKER",
        "scenario_compile",
        "Run lifecycle job queued",
        "已创建本地生命周期任务，等待独立 worker 领取。",
        payload={"status": "queued", "engine_mode": _engine_mode(request.engine_mode)},
    )
    return get_job(run_id)


def get_job(run_id: str) -> RunJobStatus:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
    return _job_from_row(row)


def list_events_after(run_id: str, after_seq: int = 0) -> list[RunLifecycleEvent]:
    return get_events(run_id, after_seq=after_seq)


def get_events(run_id: str, after_seq: int = 0) -> list[RunLifecycleEvent]:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_events WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
            (run_id, max(0, int(after_seq or 0))),
        ).fetchall()
    return [_event_from_row(row) for row in rows]


def append_event(
    run_id: str,
    event_type: str,
    phase: str,
    title: str,
    detail: str,
    *,
    tick: int | None = None,
    payload: dict | None = None,
) -> RunLifecycleEvent:
    init_db()
    created_at = now_iso()
    safe_title = redact_secrets(title, max_length=240) or "Lifecycle event"
    safe_detail = redact_secrets(detail, max_length=2000) or ""
    safe_payload = redact_structure(payload or {})
    with connect() as conn:
        job = conn.execute("SELECT run_id FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
        last = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM run_events WHERE run_id = ?", (run_id,)).fetchone()
        seq = int(last["seq"]) + 1
        conn.execute(
            """
            INSERT INTO run_events
            (run_id, seq, event_type, phase, tick, title, detail, payload, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, seq, event_type, phase, tick, safe_title, safe_detail, dumps(safe_payload), created_at),
        )
    return RunLifecycleEvent(
        run_id=run_id,
        seq=seq,
        event_type=event_type,
        phase=phase,
        tick=tick,
        title=safe_title,
        detail=safe_detail,
        payload=safe_payload,
        created_at=created_at,
    )


def claim_next_job(worker_id: str | None = None, *, lease_seconds: int = 300) -> RunJobStatus | None:
    init_db()
    worker_id = worker_id or f"worker_{uuid4().hex[:12]}"
    now = now_iso()
    lease_expires_at = _lease_expiry(lease_seconds)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM run_jobs WHERE status = ? ORDER BY created_at ASC LIMIT 1",
            (CLAIMABLE_STATUS,),
        ).fetchone()
        if row is None:
            return None
        updated = conn.execute(
            """
            UPDATE run_jobs
            SET status = ?, current_phase = ?, progress = ?, started_at = COALESCE(started_at, ?), updated_at = ?,
                worker_id = ?, lease_expires_at = ?, attempt_count = COALESCE(attempt_count, 0) + 1
            WHERE run_id = ? AND status = ?
            """,
            ("preparing", "scenario_compile", 5, now, now, worker_id, lease_expires_at, row["run_id"], CLAIMABLE_STATUS),
        )
        if updated.rowcount != 1:
            return None
    append_event(row["run_id"], "WORKER", "scenario_compile", "Worker claimed run", "独立本地 worker 已领取任务。", payload={"status": "preparing", "worker_id": worker_id, "lease_expires_at": lease_expires_at})
    return get_job(row["run_id"])


def heartbeat_job(run_id: str, worker_id: str | None, *, lease_seconds: int = 300) -> RunJobStatus:
    job = get_job(run_id)
    if job.status in TERMINAL_STATUSES:
        return job
    if job.worker_id and worker_id and job.worker_id != worker_id:
        raise HTTPException(status_code=409, detail="Lifecycle run is owned by another worker")
    now = now_iso()
    lease_expires_at = _lease_expiry(lease_seconds)
    with connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET worker_id = COALESCE(worker_id, ?), lease_expires_at = ?, updated_at = ? WHERE run_id = ?",
            (worker_id, lease_expires_at, now, run_id),
        )
    return get_job(run_id)


def recover_stale_jobs(*, recovered_by: str = "worker-recovery", now: str | None = None) -> list[RunJobStatus]:
    init_db()
    cutoff = now or now_iso()
    recovered: list[tuple[str, str, str]] = []
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT run_id, status, current_phase FROM run_jobs
            WHERE status IN ('preparing', 'running', 'pausing', 'cancelling')
              AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
            ORDER BY updated_at ASC
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            next_status = "paused" if row["status"] == "pausing" else "cancelled" if row["status"] == "cancelling" else "queued"
            completed_at = cutoff if next_status == "cancelled" else None
            conn.execute(
                """
                UPDATE run_jobs
                SET status = ?, worker_id = NULL, lease_expires_at = NULL, updated_at = ?, completed_at = COALESCE(?, completed_at)
                WHERE run_id = ? AND status = ?
                """,
                (next_status, cutoff, completed_at, row["run_id"], row["status"]),
            )
            recovered.append((row["run_id"], row["current_phase"], next_status))
    results = []
    for run_id, phase, next_status in recovered:
        append_event(
            run_id,
            "WORKER",
            phase,
            "Stale worker lease recovered",
            "检测到 worker 租约过期，任务已按阶段边界语义安全恢复。",
            payload={"status": next_status, "recovered_by": recovered_by},
        )
        results.append(get_job(run_id))
    return results


def update_job_status(
    run_id: str,
    *,
    status: str,
    phase: str | None = None,
    progress: float | None = None,
    result_run_id: str | None = None,
    error_code: str | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> RunJobStatus:
    current = get_job(run_id)
    next_phase = phase or current.current_phase
    next_progress = current.progress if progress is None else max(0.0, min(float(progress), 100.0))
    now = now_iso()
    completed_at = now if completed or status in TERMINAL_STATUSES else current.completed_at
    clear_owner = status in TERMINAL_STATUSES or status in {"paused", "queued"}
    with connect() as conn:
        conn.execute(
            """
            UPDATE run_jobs
            SET status = ?, current_phase = ?, progress = ?, result_run_id = COALESCE(?, result_run_id),
                error_code = ?, error_message = ?, updated_at = ?, completed_at = ?,
                worker_id = CASE WHEN ? THEN NULL ELSE worker_id END,
                lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END
            WHERE run_id = ?
            """,
            (status, next_phase, next_progress, result_run_id, error_code, redact_secrets(error_message), now, completed_at, clear_owner, clear_owner, run_id),
        )
    return get_job(run_id)


def mark_phase(run_id: str, phase: str, progress: float, event_type: str, title: str, detail: str, payload: dict | None = None) -> RunJobStatus:
    job = update_job_status(run_id, status="running", phase=phase, progress=progress)
    append_event(run_id, event_type, phase, title, detail, payload=payload or {"progress": progress})
    return job


def pause_job(run_id: str) -> RunJobStatus:
    job = get_job(run_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot pause {job.status} run")
    now = now_iso()
    next_status = "paused" if job.status == "queued" else "pausing"
    with connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET status = ?, pause_requested_at = ?, updated_at = ? WHERE run_id = ?",
            (next_status, now, now, run_id),
        )
    append_event(run_id, "WORKER", job.current_phase, "Pause requested", "暂停请求已记录，将在阶段边界生效。", payload={"status": next_status})
    return get_job(run_id)


def resume_job(run_id: str) -> RunJobStatus:
    job = get_job(run_id)
    if job.status not in {"paused", "pausing"}:
        raise HTTPException(status_code=409, detail=f"Cannot resume {job.status} run")
    now = now_iso()
    with connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET status = ?, pause_requested_at = NULL, worker_id = NULL, lease_expires_at = NULL, updated_at = ? WHERE run_id = ?",
            ("queued", now, run_id),
        )
    append_event(run_id, "WORKER", job.current_phase, "Run resumed", "任务已恢复排队，等待 worker 继续处理。", payload={"status": "queued"})
    return get_job(run_id)


def cancel_job(run_id: str) -> RunJobStatus:
    job = get_job(run_id)
    if job.status in TERMINAL_STATUSES:
        raise HTTPException(status_code=409, detail=f"Cannot cancel {job.status} run")
    now = now_iso()
    next_status = "cancelled" if job.status in {"queued", "paused"} else "cancelling"
    with connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET status = ?, cancel_requested_at = ?, updated_at = ?, completed_at = CASE WHEN ? = 'cancelled' THEN ? ELSE completed_at END, worker_id = CASE WHEN ? = 'cancelled' THEN NULL ELSE worker_id END, lease_expires_at = CASE WHEN ? = 'cancelled' THEN NULL ELSE lease_expires_at END WHERE run_id = ?",
            (next_status, now, now, next_status, now, next_status, next_status, run_id),
        )
    append_event(run_id, "WORKER", job.current_phase, "Cancel requested", "取消请求已记录；未完成任务不会投影到 research_runs。", payload={"status": next_status})
    return get_job(run_id)


def retry_job(run_id: str) -> RunJobStatus:
    job = get_job(run_id)
    if job.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Cannot retry {job.status} run")
    return create_job(
        job.project_id,
        RunJobCreateRequest(
            engine_mode=job.engine_mode,
            scenario=job.scenario,
            seed=job.seed,
            parent_run_id=job.run_id,
        ),
    )


def add_artifact(run_id: str, artifact_type: str, schema_version: str, content: dict) -> RunArtifactSummary:
    init_db()
    body = dumps(content)
    sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    artifact = RunArtifactSummary(
        artifact_id=f"artifact_{uuid4().hex[:12]}",
        run_id=run_id,
        artifact_type=artifact_type,
        schema_version=schema_version,
        sha256=sha256,
        created_at=now_iso(),
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO run_artifacts
            (artifact_id, run_id, artifact_type, schema_version, content_json, sha256, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (artifact.artifact_id, artifact.run_id, artifact.artifact_type, artifact.schema_version, body, artifact.sha256, artifact.created_at),
        )
    return artifact


def get_artifacts(run_id: str) -> list[RunArtifactSummary]:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT artifact_id, run_id, artifact_type, schema_version, content_json, sha256, created_at FROM run_artifacts WHERE run_id = ? ORDER BY created_at ASC",
            (run_id,),
        ).fetchall()
    return [_artifact_from_row(row) for row in rows]


def get_latest_artifact_content(run_id: str, artifact_type: str) -> dict | None:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT content_json, sha256 FROM run_artifacts
            WHERE run_id = ? AND artifact_type = ?
            ORDER BY created_at DESC, rowid DESC LIMIT 1
            """,
            (run_id, artifact_type),
        ).fetchone()
    if row is None:
        return None
    if _artifact_digest(row["content_json"]) != row["sha256"]:
        raise HTTPException(status_code=409, detail=f"Artifact integrity verification failed: {artifact_type}")
    return loads(row["content_json"], {})


def verify_artifacts(run_id: str) -> dict:
    artifacts = get_artifacts(run_id)
    invalid = [item.artifact_type for item in artifacts if item.integrity_status != "verified"]
    return {
        "status": "verified" if not invalid else "failed",
        "verified_count": len(artifacts) - len(invalid),
        "invalid_count": len(invalid),
        "invalid_artifact_types": invalid,
    }


def get_projected_result_run_id(run_id: str) -> str | None:
    job = get_job(run_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT run_id, data_snapshot FROM research_runs WHERE project_id = ? ORDER BY completed_at DESC",
            (job.project_id,),
        ).fetchall()
    for row in rows:
        if loads(row["data_snapshot"], {}).get("lifecycle_job_id") == run_id:
            return str(row["run_id"])
    return None


def get_audit(run_id: str) -> dict:
    hybrid_record = get_latest_artifact_content(run_id, "hybrid_replay_record")
    return {
        "run": get_job(run_id).model_dump(),
        "events": [event.model_dump() for event in get_events(run_id)],
        "artifacts": [artifact.model_dump() for artifact in get_artifacts(run_id)],
        "integrity": verify_artifacts(run_id),
        "consistency_audit": get_latest_artifact_content(run_id, "consistency_audit"),
        "agent_runtime": get_latest_artifact_content(run_id, "agent_runtime_audit"),
        "metrics": get_latest_artifact_content(run_id, "lifecycle_metrics"),
        "hybrid": {
            "replay_record": hybrid_record,
            "modifier_bundle": get_latest_artifact_content(run_id, "deterministic_action_modifiers"),
            "baseline_result": get_latest_artifact_content(run_id, "war_room_result"),
            "final_result": get_latest_artifact_content(run_id, "hybrid_war_room_result"),
        } if hybrid_record else None,
    }


def _scenario_payload(raw: WarRoomScenarioRequest | dict, seed: int | None) -> dict:
    if isinstance(raw, WarRoomScenarioRequest):
        payload = raw.model_dump()
    else:
        payload = dict(raw or {})
    if seed is not None:
        payload["seed"] = seed
    return WarRoomScenarioRequest(**payload).model_dump()


def _engine_mode(value: str | None) -> str:
    normalized = str(value or "deterministic").lower()
    return normalized if normalized in {"deterministic", "mock_agent", "controlled_agent", "hybrid", "hybrid_recorded"} else "deterministic"


def _ensure_job_exists(run_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT run_id FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")


def _job_from_row(row) -> RunJobStatus:
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
    )


def _event_from_row(row) -> RunLifecycleEvent:
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


def _artifact_from_row(row) -> RunArtifactSummary:
    return RunArtifactSummary(
        artifact_id=row["artifact_id"],
        run_id=row["run_id"],
        artifact_type=row["artifact_type"],
        schema_version=row["schema_version"],
        sha256=row["sha256"],
        created_at=row["created_at"],
        integrity_status="verified" if "content_json" not in row.keys() or _artifact_digest(row["content_json"]) == row["sha256"] else "failed",
    )


def _artifact_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _lease_expiry(lease_seconds: int) -> str:
    seconds = max(10, min(int(lease_seconds), 3600))
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")
