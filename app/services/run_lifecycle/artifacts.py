"""Content-addressed Artifact Store for the Run Control Plane."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.core.models import RunArtifactSummary
from app.services.project_store import connect, dumps, init_db, loads

from .integrity import artifact_digest
from .mappers import artifact_from_row


def add_artifact(
    run_id: str,
    artifact_type: str,
    schema_version: str,
    content: dict,
    *,
    attempt_id: str | None = None,
    step_id: str | None = None,
    supersedes_artifact_id: str | None = None,
    auto_supersede: bool = True,
) -> RunArtifactSummary:
    init_db()
    body = dumps(content)
    sha256 = artifact_digest(body)
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
        if supersedes_artifact_id is None and auto_supersede:
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
        created_at=datetime.now().isoformat(timespec="milliseconds"),
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
                artifact.artifact_id,
                artifact.run_id,
                artifact.artifact_type,
                artifact.schema_version,
                body,
                artifact.sha256,
                artifact.created_at,
                artifact.attempt_id,
                artifact.step_id,
                artifact.artifact_version,
                artifact.supersedes_artifact_id,
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
    return [artifact_from_row(row) for row in rows]


def get_artifact_content_by_id(run_id: str, artifact_id: str) -> dict:
    return get_artifact_record_by_id(run_id, artifact_id)[1]


def get_artifact_summary_by_id(
    run_id: str, artifact_id: str
) -> RunArtifactSummary:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT artifact_id, run_id, artifact_type, schema_version, content_json,
                   sha256, created_at, attempt_id, step_id, artifact_version,
                   supersedes_artifact_id
            FROM run_artifacts WHERE run_id = ? AND artifact_id = ?
            """,
            (run_id, artifact_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail=f"Checkpoint artifact is missing: {artifact_id}")
    return artifact_from_row(row)


def get_artifact_record_by_id(run_id: str, artifact_id: str) -> tuple[str, dict]:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT artifact_type, content_json, sha256 FROM run_artifacts WHERE run_id = ? AND artifact_id = ?",
            (run_id, artifact_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail=f"Checkpoint artifact is missing: {artifact_id}")
    if artifact_digest(row["content_json"]) != row["sha256"]:
        raise HTTPException(
            status_code=409,
            detail=f"Checkpoint artifact integrity verification failed: {row['artifact_type']}",
        )
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
    if artifact_digest(row["content_json"]) != row["sha256"]:
        raise HTTPException(status_code=409, detail=f"Artifact integrity verification failed: {artifact_type}")
    return loads(row["content_json"], {})


def get_latest_artifact_summary(
    run_id: str, artifact_type: str
) -> RunArtifactSummary | None:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        row = conn.execute(
            """
            SELECT a.artifact_id, a.run_id, a.artifact_type, a.schema_version,
                   a.content_json, a.sha256, a.created_at, a.attempt_id,
                   a.step_id, a.artifact_version, a.supersedes_artifact_id
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
    return artifact_from_row(row) if row is not None else None


def get_artifact_contents(run_id: str, artifact_type: str) -> list[dict]:
    init_db()
    _ensure_job_exists(run_id)
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT a.content_json, a.sha256
            FROM run_artifacts AS a
            LEFT JOIN run_attempts AS attempt ON attempt.attempt_id = a.attempt_id
            LEFT JOIN run_steps AS step ON step.step_id = a.step_id
            WHERE a.run_id = ? AND a.artifact_type = ?
              AND (a.attempt_id IS NULL OR attempt.status IN ('running', 'completed'))
            ORDER BY a.artifact_version, a.created_at, a.artifact_id
            """,
            (run_id, artifact_type),
        ).fetchall()
    result: list[dict] = []
    for row in rows:
        if artifact_digest(row["content_json"]) != row["sha256"]:
            raise HTTPException(status_code=409, detail=f"Artifact integrity verification failed: {artifact_type}")
        result.append(loads(row["content_json"], {}))
    return result


def verify_artifacts(run_id: str) -> dict:
    artifacts = get_artifacts(run_id)
    invalid = [item.artifact_type for item in artifacts if item.integrity_status != "verified"]
    return {
        "status": "verified" if not invalid else "failed",
        "verified_count": len(artifacts) - len(invalid),
        "invalid_count": len(invalid),
        "invalid_artifact_types": invalid,
    }


def _ensure_job_exists(run_id: str) -> None:
    with connect() as conn:
        row = conn.execute("SELECT run_id FROM run_jobs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown lifecycle run: {run_id}")
