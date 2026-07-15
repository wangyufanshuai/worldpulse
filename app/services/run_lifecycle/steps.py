from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.core.models import RunStepRecord
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads
from app.services.security import redact_secrets


@dataclass(frozen=True)
class StepDefinition:
    key: str
    version: str


STEP_DEFINITIONS = (
    StepDefinition("scenario_compile", "scenario-compile.v1"),
    StepDefinition("environment_prepare", "environment-prepare.v1"),
    StepDefinition("deterministic_run", "deterministic-run.v1"),
    StepDefinition("consistency_audit", "consistency-audit-step.v1"),
    StepDefinition("report_generate", "report-generate.v1"),
    StepDefinition("replay_archive", "replay-archive.v1"),
)
STEP_BY_KEY = {item.key: item for item in STEP_DEFINITIONS}


def begin_step(run_id: str, step_key: str, attempt_id: str, input_payload: dict) -> RunStepRecord:
    init_db()
    definition = STEP_BY_KEY[step_key]
    started_at = _now()
    input_hash = stable_hash(input_payload)
    step_id = f"step_{stable_hash({'run_id': run_id, 'step_key': step_key, 'attempt_id': attempt_id})[:20]}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO run_steps
            (step_id, run_id, step_key, step_version, attempt_id, input_hash, status, started_at, artifact_refs, input_json, output_json)
            VALUES (?, ?, ?, ?, ?, ?, 'running', ?, '[]', ?, '{}')
            ON CONFLICT(run_id, step_key, attempt_id) DO UPDATE SET
                step_version = excluded.step_version,
                input_hash = excluded.input_hash,
                status = 'running',
                started_at = excluded.started_at,
                completed_at = NULL,
                duration_ms = 0,
                error_code = NULL,
                artifact_refs = '[]',
                input_json = excluded.input_json,
                output_json = '{}',
                output_hash = NULL
            """,
            (step_id, run_id, step_key, definition.version, attempt_id, input_hash, started_at, dumps(input_payload)),
        )
    return get_step(step_id)


def complete_step(step_id: str, output_payload: dict, artifact_refs: list[str]) -> RunStepRecord:
    current = get_step(step_id)
    completed_at = _now()
    duration_ms = _duration_ms(current.started_at, completed_at)
    output_hash = stable_hash(output_payload)
    with connect() as conn:
        conn.execute(
            """
            UPDATE run_steps
            SET status = 'completed', output_hash = ?, completed_at = ?, duration_ms = ?,
                error_code = NULL, artifact_refs = ?, output_json = ?
            WHERE step_id = ?
            """,
            (output_hash, completed_at, duration_ms, dumps(sorted(set(artifact_refs))), dumps(output_payload), step_id),
        )
    return get_step(step_id)


def fail_step(step_id: str, error: Exception | str) -> RunStepRecord:
    current = get_step(step_id)
    completed_at = _now()
    error_code = type(error).__name__ if isinstance(error, Exception) else "StepExecutionError"
    safe_error = redact_secrets(str(error)) or error_code
    output = {"error": safe_error}
    with connect() as conn:
        conn.execute(
            """
            UPDATE run_steps
            SET status = 'failed', output_hash = ?, completed_at = ?, duration_ms = ?, error_code = ?, output_json = ?
            WHERE step_id = ?
            """,
            (stable_hash(output), completed_at, _duration_ms(current.started_at, completed_at), error_code, dumps(output), step_id),
        )
    return get_step(step_id)


def fail_active_step(run_id: str, error: Exception | str) -> RunStepRecord | None:
    with connect() as conn:
        row = conn.execute(
            "SELECT step_id FROM run_steps WHERE run_id = ? AND status = 'running' ORDER BY started_at DESC, rowid DESC LIMIT 1",
            (run_id,),
        ).fetchone()
    return fail_step(row["step_id"], error) if row else None


def get_steps(run_id: str) -> list[RunStepRecord]:
    init_db()
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at ASC, rowid ASC",
            (run_id,),
        ).fetchall()
    return [_from_row(row) for row in rows]


def get_step(step_id: str) -> RunStepRecord:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM run_steps WHERE step_id = ?", (step_id,)).fetchone()
    if row is None:
        raise KeyError(f"Unknown lifecycle step: {step_id}")
    return _from_row(row)


def attempt_id_for(run_id: str, attempt_count: int) -> str:
    return f"attempt_{stable_hash({'run_id': run_id, 'attempt_count': max(1, attempt_count)})[:20]}"


def _from_row(row) -> RunStepRecord:
    return RunStepRecord(
        step_id=row["step_id"],
        run_id=row["run_id"],
        step_key=row["step_key"],
        step_version=row["step_version"],
        attempt_id=row["attempt_id"],
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        status=row["status"],
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        duration_ms=int(row["duration_ms"] or 0),
        error_code=row["error_code"],
        artifact_refs=loads(row["artifact_refs"], []),
        input=loads(row["input_json"], {}),
        output=loads(row["output_json"], {}),
    )


def _duration_ms(started_at: str, completed_at: str) -> int:
    return max(0, int((datetime.fromisoformat(completed_at) - datetime.fromisoformat(started_at)).total_seconds() * 1000))


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
