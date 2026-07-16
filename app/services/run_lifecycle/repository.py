from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
from uuid import uuid4

from fastapi import HTTPException

from app.core.models import (
    LifecycleHealthSummary,
    RunAttemptRecord,
    RunArtifactSummary,
    RunJobCreateRequest,
    RunJobStatus,
    RunLifecycleEvent,
    WarRoomScenarioRequest,
)
from app.services.consistency.hashing import stable_hash
from app.db.postgres import is_postgres_url
from app.services.project_store import connect, dumps, init_db, loads
from app.services.security import redact_secrets, redact_structure
from app.services.rule_packs import active_rule_pack, get_rule_pack


TERMINAL_STATUSES = {"completed", "cancelled", "failed"}
CLAIMABLE_STATUS = "queued"


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def create_job(
    project_id: str,
    request: RunJobCreateRequest,
    *,
    idempotency_key: str | None = None,
    pinned_rule_pack_id: str | None = None,
) -> RunJobStatus:
    init_db()
    scenario = _scenario_payload(request.scenario, request.seed)
    engine_mode = _engine_mode(request.engine_mode)
    normalized_key = _normalize_idempotency_key(idempotency_key)
    rule_pack = get_rule_pack(pinned_rule_pack_id) if pinned_rule_pack_id else active_rule_pack()
    request_hash = stable_hash(
        {
            "project_id": project_id,
            "engine_mode": engine_mode,
            "scenario": scenario,
            "seed": request.seed,
            "parent_run_id": request.parent_run_id,
            "max_attempts": request.max_attempts,
            "rule_pack_hash": rule_pack.manifest_hash,
        }
    )
    run_id = f"job_{uuid4().hex[:12]}"
    now = now_iso()
    existing_run_id: str | None = None
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        project = conn.execute("SELECT project_id FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
        if project is None:
            raise HTTPException(status_code=404, detail=f"Unknown project: {project_id}")
        if normalized_key:
            existing = conn.execute(
                "SELECT run_id, request_hash FROM run_jobs WHERE project_id = ? AND idempotency_key = ?",
                (project_id, normalized_key),
            ).fetchone()
            if existing is not None:
                if existing["request_hash"] != request_hash:
                    raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different request")
                existing_run_id = existing["run_id"]
        if existing_run_id is None:
            from app.services.operations import enforce_project_run_quota

            enforce_project_run_quota(project_id, connection=conn)
            conn.execute(
            """
            INSERT INTO run_jobs
            (run_id, project_id, engine_mode, status, current_phase, progress, seed, parent_run_id,
             scenario_json, created_at, updated_at, max_attempts, request_hash, idempotency_key,
             job_kind, rule_pack_id, rule_pack_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'war_room', ?, ?)
            """,
            (
                run_id,
                project_id,
                engine_mode,
                "queued",
                "scenario_compile",
                0,
                request.seed,
                request.parent_run_id,
                dumps(scenario),
                now,
                now,
                request.max_attempts,
                request_hash,
                normalized_key,
                rule_pack.rule_pack_id,
                rule_pack.manifest_hash,
                ),
            )
    if existing_run_id is not None:
        return get_job(existing_run_id)
    append_event(
        run_id,
        "WORKER",
        "scenario_compile",
        "Run lifecycle job queued",
        "已创建本地生命周期任务，等待独立 worker 领取。",
        payload={"status": "queued", "engine_mode": engine_mode, "idempotent": bool(normalized_key)},
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
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        job = conn.execute("SELECT run_id FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
        conn.execute("INSERT INTO run_event_counters(run_id, next_seq) VALUES (?, 1) ON CONFLICT(run_id) DO NOTHING", (run_id,))
        if is_postgres_url():
            counter = conn.execute(
                "UPDATE run_event_counters SET next_seq = next_seq + 1 WHERE run_id = ? RETURNING next_seq - 1 AS seq",
                (run_id,),
            ).fetchone()
            seq = int(counter["seq"])
        else:
            counter = conn.execute(
                "SELECT next_seq FROM run_event_counters WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            seq = int(counter["next_seq"])
            conn.execute(
                "UPDATE run_event_counters SET next_seq = ? WHERE run_id = ?",
                (seq + 1, run_id),
            )
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
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        lock_clause = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
        row = conn.execute(
            f"""
            SELECT * FROM run_jobs
            WHERE status = ?
              AND (next_attempt_at IS NULL OR next_attempt_at <= ?)
              AND COALESCE(attempt_count, 0) < COALESCE(max_attempts, 3)
            ORDER BY created_at ASC LIMIT 1{lock_clause}
            """,
            (CLAIMABLE_STATUS, now),
        ).fetchone()
        if row is None:
            return None
        attempt_number = int(row["attempt_count"] or 0) + 1
        attempt_id = f"attempt_{uuid4().hex}"
        updated = conn.execute(
            """
            UPDATE run_jobs
            SET status = ?, started_at = COALESCE(started_at, ?), updated_at = ?,
                worker_id = ?, lease_expires_at = ?, attempt_count = ?, current_attempt_id = ?,
                next_attempt_at = NULL, terminal_reason = NULL, error_code = NULL, error_message = NULL
            WHERE run_id = ? AND status = ?
            """,
            ("preparing", now, now, worker_id, lease_expires_at, attempt_number, attempt_id, row["run_id"], CLAIMABLE_STATUS),
        )
        if updated.rowcount != 1:
            return None
        conn.execute(
            """
            INSERT INTO run_attempts
            (attempt_id, run_id, worker_id, attempt_number, status, started_at)
            VALUES (?, ?, ?, ?, 'running', ?)
            """,
            (attempt_id, row["run_id"], worker_id, attempt_number, now),
        )
    append_event(
        row["run_id"], "WORKER", row["current_phase"], "Worker claimed run", "独立本地 worker 已领取任务。",
        payload={
            "status": "preparing", "worker_id": worker_id, "lease_expires_at": lease_expires_at,
            "attempt_id": attempt_id, "attempt_number": attempt_number,
        },
    )
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
    recovered: list[tuple[str, str, str, str | None]] = []
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        lock_clause = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
        rows = conn.execute(
            f"""
            SELECT run_id, status, current_phase, current_attempt_id, attempt_count, max_attempts FROM run_jobs
            WHERE status IN ('preparing', 'running', 'pausing', 'cancelling')
              AND lease_expires_at IS NOT NULL AND lease_expires_at < ?
            ORDER BY updated_at ASC{lock_clause}
            """,
            (cutoff,),
        ).fetchall()
        for row in rows:
            attempts_exhausted = int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 3)
            next_status = (
                "paused" if row["status"] == "pausing"
                else "cancelled" if row["status"] == "cancelling"
                else "failed" if attempts_exhausted
                else "queued"
            )
            completed_at = cutoff if next_status in TERMINAL_STATUSES else None
            terminal_reason = "stale_lease_attempts_exhausted" if next_status == "failed" else (
                "user_cancelled" if next_status == "cancelled" else "stale_lease_recovered"
            )
            conn.execute(
                """
                UPDATE run_jobs
                SET status = ?, worker_id = NULL, lease_expires_at = NULL, updated_at = ?,
                    completed_at = COALESCE(?, completed_at), terminal_reason = ?
                WHERE run_id = ? AND status = ?
                """,
                (next_status, cutoff, completed_at, terminal_reason, row["run_id"], row["status"]),
            )
            if row["current_attempt_id"]:
                conn.execute(
                    """
                    UPDATE run_attempts
                    SET status = ?, completed_at = ?, error_code = 'WorkerLeaseExpired',
                        error_message = 'Worker lease expired before the next verified step boundary'
                    WHERE attempt_id = ? AND status = 'running'
                    """,
                    ("failed" if next_status == "failed" else "abandoned", cutoff, row["current_attempt_id"]),
                )
            recovered.append((row["run_id"], row["current_phase"], next_status, row["current_attempt_id"]))
    results = []
    for run_id, phase, next_status, attempt_id in recovered:
        append_event(
            run_id,
            "WORKER",
            phase,
            "Stale worker lease recovered",
            "检测到 worker 租约过期，任务已按阶段边界语义安全恢复。",
            payload={"status": next_status, "recovered_by": recovered_by, "attempt_id": attempt_id},
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
    terminal_reason: str | None = None,
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
                terminal_reason = COALESCE(?, terminal_reason),
                worker_id = CASE WHEN ? THEN NULL ELSE worker_id END,
                lease_expires_at = CASE WHEN ? THEN NULL ELSE lease_expires_at END
            WHERE run_id = ?
            """,
            (status, next_phase, next_progress, result_run_id, error_code, redact_secrets(error_message), now, completed_at, terminal_reason, clear_owner, clear_owner, run_id),
        )
        if current.current_attempt_id and status in {"completed", "paused", "cancelled", "failed"}:
            conn.execute(
                """
                UPDATE run_attempts
                SET status = ?, completed_at = COALESCE(completed_at, ?), error_code = COALESCE(?, error_code),
                    error_message = COALESCE(?, error_message)
                WHERE attempt_id = ? AND status = 'running'
                """,
                (status, now, error_code, redact_secrets(error_message), current.current_attempt_id),
            )
        _sync_negotiation_session_status(conn, run_id, status, now)
    return get_job(run_id)


def handle_attempt_failure(run_id: str, error: Exception) -> RunJobStatus:
    job = get_job(run_id)
    safe_error = redact_secrets(str(error)) or "Lifecycle execution failed"
    error_code = type(error).__name__
    now = now_iso()
    exhausted = job.attempt_count >= job.max_attempts
    if exhausted:
        return update_job_status(
            run_id,
            status="failed",
            progress=job.progress,
            error_code=error_code,
            error_message=safe_error,
            terminal_reason="max_attempts_exhausted",
            completed=True,
        )

    delay_seconds = min(60, 2 ** max(0, job.attempt_count - 1))
    next_attempt_at = (datetime.now() + timedelta(seconds=delay_seconds)).isoformat(timespec="milliseconds")
    with connect() as conn:
        conn.execute(
            """
            UPDATE run_jobs
            SET status = 'queued', next_attempt_at = ?, terminal_reason = 'retry_scheduled',
                error_code = ?, error_message = ?, updated_at = ?, worker_id = NULL, lease_expires_at = NULL
            WHERE run_id = ?
            """,
            (next_attempt_at, error_code, safe_error, now, run_id),
        )
        if job.current_attempt_id:
            conn.execute(
                """
                UPDATE run_attempts
                SET status = 'failed', completed_at = ?, error_code = ?, error_message = ?
                WHERE attempt_id = ? AND status = 'running'
                """,
                (now, error_code, safe_error, job.current_attempt_id),
            )
    append_event(
        run_id,
        "WORKER",
        job.current_phase,
        "Run retry scheduled",
        "当前执行尝试失败，任务将在指数退避后从最近有效检查点继续。",
        payload={
            "status": "queued",
            "attempt_id": job.current_attempt_id,
            "attempt_number": job.attempt_count,
            "max_attempts": job.max_attempts,
            "next_attempt_at": next_attempt_at,
            "error": error_code,
        },
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
        _sync_negotiation_session_status(conn, run_id, next_status, now)
    append_event(run_id, "WORKER", job.current_phase, "Pause requested", "暂停请求已记录，将在阶段边界生效。", payload={"status": next_status})
    return get_job(run_id)


def resume_job(run_id: str) -> RunJobStatus:
    job = get_job(run_id)
    if job.status not in {"paused", "pausing"}:
        raise HTTPException(status_code=409, detail=f"Cannot resume {job.status} run")
    now = now_iso()
    with connect() as conn:
        conn.execute(
            """
            UPDATE run_jobs
            SET status = ?, pause_requested_at = NULL, worker_id = NULL, lease_expires_at = NULL,
                next_attempt_at = NULL, terminal_reason = NULL, completed_at = NULL, updated_at = ?
            WHERE run_id = ?
            """,
            ("queued", now, run_id),
        )
        _sync_negotiation_session_status(conn, run_id, "running", now)
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
            """
            UPDATE run_jobs
            SET status = ?, cancel_requested_at = ?, updated_at = ?,
                completed_at = CASE WHEN ? = 'cancelled' THEN ? ELSE completed_at END,
                terminal_reason = CASE WHEN ? = 'cancelled' THEN 'user_cancelled' ELSE terminal_reason END,
                worker_id = CASE WHEN ? = 'cancelled' THEN NULL ELSE worker_id END,
                lease_expires_at = CASE WHEN ? = 'cancelled' THEN NULL ELSE lease_expires_at END
            WHERE run_id = ?
            """,
            (next_status, now, now, next_status, now, next_status, next_status, next_status, run_id),
        )
        if next_status == "cancelled" and job.current_attempt_id:
            conn.execute(
                """
                UPDATE run_attempts SET status = 'cancelled', completed_at = ?
                WHERE attempt_id = ? AND status = 'running'
                """,
                (now, job.current_attempt_id),
            )
        _sync_negotiation_session_status(conn, run_id, next_status, now)
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
            max_attempts=job.max_attempts,
        ),
        pinned_rule_pack_id=job.rule_pack_id,
    )


def add_artifact(
    run_id: str,
    artifact_type: str,
    schema_version: str,
    content: dict,
    *,
    attempt_id: str | None = None,
    step_id: str | None = None,
    supersedes_artifact_id: str | None = None,
) -> RunArtifactSummary:
    init_db()
    body = dumps(content)
    sha256 = hashlib.sha256(body.encode("utf-8")).hexdigest()
    with connect() as conn:
        job = conn.execute(
            "SELECT current_attempt_id FROM run_jobs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
        attempt_id = attempt_id or job["current_attempt_id"]
        if step_id is None and attempt_id:
            active_step = conn.execute(
                """
                SELECT step_id FROM run_steps
                WHERE run_id = ? AND attempt_id = ? AND status = 'running'
                ORDER BY started_at DESC, step_id DESC LIMIT 1
                """,
                (run_id, attempt_id),
            ).fetchone()
            step_id = active_step["step_id"] if active_step else None
        if supersedes_artifact_id is None:
            previous = conn.execute(
                """
                SELECT artifact_id FROM run_artifacts
                WHERE run_id = ? AND artifact_type = ?
                ORDER BY created_at DESC, artifact_id DESC LIMIT 1
                """,
                (run_id, artifact_type),
            ).fetchone()
            supersedes_artifact_id = previous["artifact_id"] if previous else None
        version_row = conn.execute(
            """
            SELECT COALESCE(MAX(artifact_version), 0) AS version
            FROM run_artifacts WHERE run_id = ? AND artifact_type = ?
            """,
            (run_id, artifact_type),
        ).fetchone()
        artifact_version = int(version_row["version"] or 0) + 1
    artifact = RunArtifactSummary(
        artifact_id=f"artifact_{uuid4().hex[:12]}",
        run_id=run_id,
        artifact_type=artifact_type,
        schema_version=schema_version,
        sha256=sha256,
        created_at=now_iso(),
        attempt_id=attempt_id,
        step_id=step_id,
        artifact_version=artifact_version,
        supersedes_artifact_id=supersedes_artifact_id,
    )
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO run_artifacts
            (artifact_id, run_id, artifact_type, schema_version, content_json, sha256, created_at,
             attempt_id, step_id, artifact_version, supersedes_artifact_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact.artifact_id, artifact.run_id, artifact.artifact_type, artifact.schema_version,
                body, artifact.sha256, artifact.created_at, artifact.attempt_id, artifact.step_id,
                artifact.artifact_version, artifact.supersedes_artifact_id,
            ),
        )
    return artifact


def get_artifacts(run_id: str) -> list[RunArtifactSummary]:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT artifact_id, run_id, artifact_type, schema_version, content_json, sha256, created_at,
                   attempt_id, step_id, artifact_version, supersedes_artifact_id
            FROM run_artifacts WHERE run_id = ? ORDER BY created_at ASC, artifact_id ASC
            """,
            (run_id,),
        ).fetchall()
    return [_artifact_from_row(row) for row in rows]


def get_steps(run_id: str):
    _ensure_job_exists(run_id)
    from .steps import get_steps as query_steps

    return query_steps(run_id)


def get_attempts(run_id: str) -> list[RunAttemptRecord]:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_attempts WHERE run_id = ? ORDER BY attempt_number ASC",
            (run_id,),
        ).fetchall()
    return [
        RunAttemptRecord(
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
        for row in rows
    ]


def set_attempt_resume_step(attempt_id: str, step_key: str | None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE run_attempts SET resume_from_step = ? WHERE attempt_id = ?",
            (step_key, attempt_id),
        )


def get_artifact_content_by_id(run_id: str, artifact_id: str) -> dict:
    return get_artifact_record_by_id(run_id, artifact_id)[1]


def get_artifact_record_by_id(run_id: str, artifact_id: str) -> tuple[str, dict]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT artifact_type, content_json, sha256 FROM run_artifacts WHERE run_id = ? AND artifact_id = ?",
            (run_id, artifact_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail=f"Checkpoint artifact is missing: {artifact_id}")
    if _artifact_digest(row["content_json"]) != row["sha256"]:
        raise HTTPException(status_code=409, detail=f"Checkpoint artifact integrity verification failed: {row['artifact_type']}")
    return row["artifact_type"], loads(row["content_json"], {})


def get_latest_artifact_content(run_id: str, artifact_type: str) -> dict | None:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT a.content_json, a.sha256
            FROM run_artifacts AS a
            LEFT JOIN run_attempts AS attempt ON attempt.attempt_id = a.attempt_id
            LEFT JOIN run_steps AS step ON step.step_id = a.step_id
            WHERE a.run_id = ? AND a.artifact_type = ?
              AND (a.attempt_id IS NULL OR attempt.status IN ('running', 'completed'))
            ORDER BY COALESCE(attempt.attempt_number, 0) DESC,
                     COALESCE(step.completed_at, step.started_at, a.created_at) DESC,
                     a.artifact_version DESC, a.created_at DESC, a.artifact_id DESC
            LIMIT 1
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
    negotiation_summary = get_latest_artifact_content(run_id, "negotiation_summary")
    return {
        "run": get_job(run_id).model_dump(),
        "events": [event.model_dump() for event in get_events(run_id)],
        "artifacts": [artifact.model_dump() for artifact in get_artifacts(run_id)],
        "steps": [step.model_dump() for step in get_steps(run_id)],
        "attempts": [attempt.model_dump() for attempt in get_attempts(run_id)],
        "integrity": verify_artifacts(run_id),
        "consistency_audit": get_latest_artifact_content(run_id, "consistency_audit"),
        "action_projection_audit": get_latest_artifact_content(run_id, "agent_action_projection_audit"),
        "agent_runtime": get_latest_artifact_content(run_id, "agent_runtime_audit"),
        "metrics": get_latest_artifact_content(run_id, "lifecycle_metrics"),
        "hybrid": {
            "replay_record": hybrid_record,
            "modifier_bundle": get_latest_artifact_content(run_id, "deterministic_action_modifiers"),
            "baseline_result": get_latest_artifact_content(run_id, "war_room_result"),
            "final_result": get_latest_artifact_content(run_id, "hybrid_war_room_result"),
        } if hybrid_record else None,
        "negotiation": negotiation_summary,
    }


def get_health_summary() -> LifecycleHealthSummary:
    init_db()
    now = datetime.now()
    with connect() as conn:
        jobs = conn.execute(
            "SELECT status, created_at, started_at, lease_expires_at, worker_id FROM run_jobs"
        ).fetchall()
        steps_rows = conn.execute(
            "SELECT step_key, duration_ms FROM run_steps WHERE status = 'completed' AND completed_at IS NOT NULL"
        ).fetchall()
        artifacts = conn.execute("SELECT content_json, sha256 FROM run_artifacts").fetchall()
        recoveries = conn.execute(
            "SELECT COUNT(*) AS count FROM run_events WHERE title = 'Stale worker lease recovered'"
        ).fetchone()["count"]
        auth_failures = conn.execute("SELECT COUNT(*) FROM security_audit_events WHERE event_type = 'auth.login.failed'").fetchone()[0]
        access_denied = conn.execute("SELECT COUNT(*) FROM security_audit_events WHERE event_type = 'api.access' AND outcome = 'denied'").fetchone()[0]
        calibration_rows = conn.execute("SELECT created_at, completed_at, metrics_json FROM calibration_runs WHERE completed_at IS NOT NULL").fetchall()
        promotions = conn.execute("SELECT COUNT(*) FROM rule_packs WHERE activated_at IS NOT NULL").fetchone()[0]
        review_rows = conn.execute("SELECT created_at, closed_at, status FROM review_cases").fetchall()

    counts = {"queued": 0, "running": 0, "stale": 0, "failed": 0, "completed": 0}
    queue_waits: list[float] = []
    workers: set[str] = set()
    for row in jobs:
        status = row["status"]
        if status in {"preparing", "running", "pausing", "cancelling"}:
            counts["running"] += 1
            if row["lease_expires_at"] and row["lease_expires_at"] < now.isoformat(timespec="milliseconds"):
                counts["stale"] += 1
        elif status in counts:
            counts[status] += 1
        if row["worker_id"]:
            workers.add(row["worker_id"])
        if row["started_at"]:
            queue_waits.append(max(0.0, (datetime.fromisoformat(row["started_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds() * 1000))

    durations: dict[str, list[float]] = {}
    for row in steps_rows:
        durations.setdefault(row["step_key"], []).append(float(row["duration_ms"] or 0))
    phase_durations = {
        key: {"count": len(values), "p50": _percentile(values, 0.50), "p95": _percentile(values, 0.95)}
        for key, values in sorted(durations.items())
    }
    invalid = sum(1 for row in artifacts if _artifact_digest(row["content_json"]) != row["sha256"])
    calibration_durations = [
        max(0.0, (datetime.fromisoformat(row["completed_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds() * 1000)
        for row in calibration_rows
    ]
    false_accepts = sum(int(loads(row["metrics_json"], {}).get("critical_false_accept", 0)) for row in calibration_rows)
    review_durations = [
        max(0.0, (datetime.fromisoformat(row["closed_at"]) - datetime.fromisoformat(row["created_at"])).total_seconds() * 1000)
        for row in review_rows if row["closed_at"]
    ]
    return LifecycleHealthSummary(
        **counts,
        avg_queue_wait_ms=round(sum(queue_waits) / len(queue_waits), 2) if queue_waits else 0,
        recoveries=int(recoveries or 0),
        artifact_integrity_failures=invalid,
        phase_durations_ms=phase_durations,
        worker_count=len(workers),
        security_metrics={
            "auth_failures": int(auth_failures),
            "access_denied_401_403": int(access_denied),
            "calibration_avg_duration_ms": round(sum(calibration_durations) / len(calibration_durations), 2) if calibration_durations else 0,
            "rule_pack_activations": int(promotions),
            "critical_false_accepts": int(false_accepts),
            "pending_reviews": sum(1 for row in review_rows if row["status"] == "open"),
            "review_avg_resolution_ms": round(sum(review_durations) / len(review_durations), 2) if review_durations else 0,
        },
    )


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
    return normalized if normalized in {"deterministic", "mock_agent", "controlled_agent", "hybrid", "hybrid_recorded", "negotiation"} else "deterministic"


def _sync_negotiation_session_status(conn, run_id: str, status: str, now: str) -> None:
    if status not in {"running", "paused", "cancelled", "failed", "completed"}:
        return
    conn.execute(
        """
        UPDATE negotiation_sessions
        SET status = ?, completed_at = CASE WHEN ? IN ('cancelled','failed','completed') THEN COALESCE(completed_at, ?) ELSE NULL END
        WHERE run_id = ?
        """,
        (status, status, now, run_id),
    )


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
        attempt_id=row["attempt_id"] if "attempt_id" in row.keys() else None,
        step_id=row["step_id"] if "step_id" in row.keys() else None,
        artifact_version=int(row["artifact_version"] or 1) if "artifact_version" in row.keys() else 1,
        supersedes_artifact_id=row["supersedes_artifact_id"] if "supersedes_artifact_id" in row.keys() else None,
        integrity_status="verified" if "content_json" not in row.keys() or _artifact_digest(row["content_json"]) == row["sha256"] else "failed",
    )


def _artifact_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _lease_expiry(lease_seconds: int) -> str:
    seconds = max(10, min(int(lease_seconds), 3600))
    return (datetime.now() + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")


def _normalize_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot be empty")
    if len(normalized) > 200:
        raise HTTPException(status_code=400, detail="Idempotency-Key cannot exceed 200 characters")
    if any(ord(char) < 33 or ord(char) > 126 for char in normalized):
        raise HTTPException(status_code=400, detail="Idempotency-Key must contain printable ASCII characters only")
    return normalized


def _percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return round(ordered[index], 2)
