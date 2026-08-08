"""Atomic V2 report checkpoint persistence under GOV-FINALIZE-FENCE-1."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.db.postgres import is_postgres_url
from app.services.consistency.hashing import stable_hash
from app.services.projects import (
    get_project_detail,
    prepare_war_room_result,
    write_prepared_war_room_result,
)
from app.services.project_store import connect, dumps, loads

from . import worker_trust
from .execution_contract import V2ExecutionPathNotEnabledError
from .execution_contract import KernelModeFencingEpoch
from .integrity import artifact_digest
from .mode_execution_adapter import (
    ModeExecutionReconstruction,
    ReportProjectionManifestV2,
    _strict_json_array,
    _strict_json_object,
    build_report_projection_manifest_v2,
    StoredModeExecutionAdapter,
)
from .repository import now_iso


class FinalizationFenceError(ValueError):
    """The current lease/attempt no longer authorizes a finalization write."""


@dataclass(frozen=True)
class ReportFinalizationResult:
    manifest: ReportProjectionManifestV2
    artifact_id: str
    step_id: str
    recovered: bool


@dataclass(frozen=True)
class ReplayFinalizationResult:
    result_run_id: str
    projection_artifact_id: str
    metrics_artifact_id: str
    step_id: str


def finalization_fault_hook(moment: str) -> None:
    """Test-only transaction fault seam; production is a no-op."""

    return None


def commit_report_generate_v2(
    run_id: str,
    *,
    step_id: str,
    reconstruction: ModeExecutionReconstruction,
) -> ReportFinalizationResult:
    """Commit manifest + exact step binding in one fenced transaction."""

    manifest = build_report_projection_manifest_v2(reconstruction)
    request = reconstruction.request
    record = reconstruction.record
    if (
        request.run_id != run_id
        or request.lifecycle_job_id != run_id
        or record.run_id != run_id
        or record.lifecycle_job_id != run_id
        or request.attempt != record.attempt
        or request.fencing_epoch_hash != record.fencing_epoch_hash
    ):
        raise FinalizationFenceError("reconstruction ownership tuple is inconsistent")
    now = now_iso()
    with connect() as connection:
        if not is_postgres_url():
            connection.execute("BEGIN IMMEDIATE")
        step = connection.execute(
            """
            SELECT * FROM run_steps
            WHERE step_id = ? AND run_id = ? AND step_key = 'report_generate'
              AND step_version = 'report-generate.v2' AND attempt_id = ?
            """,
            (step_id, run_id, request.attempt),
        ).fetchone()
        if step is None:
            raise FinalizationFenceError("current V2 report step is missing")
        _validate_report_step_input(
            step,
            expected_fencing_epoch_hash=request.fencing_epoch_hash,
        )
        existing = connection.execute(
            """
            SELECT * FROM run_artifacts
            WHERE run_id = ? AND attempt_id = ?
              AND artifact_type = 'report_projection_manifest'
              AND schema_version = 'report-projection-manifest.v2'
            ORDER BY artifact_version ASC, artifact_id ASC
            """,
            (run_id, request.attempt),
        ).fetchall()
        if step["status"] not in {"running", "completed"}:
            raise FinalizationFenceError("V2 report step is not running")
        if step["status"] == "running" and existing:
            raise FinalizationFenceError(
                "running V2 report step already has a manifest Artifact"
            )

        try:
            epoch = worker_trust.capture_v2_fencing_epoch(
                connection,
                run_id=run_id,
                now=now,
                lock_rows=is_postgres_url(),
                expected_fencing_epoch_hash=request.fencing_epoch_hash,
            )
        except V2ExecutionPathNotEnabledError as error:
            raise FinalizationFenceError(str(error)) from error
        step = connection.execute(
            """
            SELECT * FROM run_steps
            WHERE step_id = ? AND run_id = ? AND step_key = 'report_generate'
              AND step_version = 'report-generate.v2' AND attempt_id = ?
            """,
            (step_id, run_id, request.attempt),
        ).fetchone()
        existing = connection.execute(
            """
            SELECT * FROM run_artifacts
            WHERE run_id = ? AND attempt_id = ?
              AND artifact_type = 'report_projection_manifest'
              AND schema_version = 'report-projection-manifest.v2'
            ORDER BY artifact_version ASC, artifact_id ASC
            """,
            (run_id, request.attempt),
        ).fetchall()
        if step is None:
            raise FinalizationFenceError("current V2 report step disappeared")
        _validate_report_step_input(
            step,
            expected_fencing_epoch_hash=request.fencing_epoch_hash,
        )
        if step["status"] == "completed":
            return _validate_completed_report(
                step,
                existing,
                expected_manifest=manifest,
            )
        if step["status"] != "running" or existing:
            raise FinalizationFenceError(
                "V2 report state changed before finalization CAS"
            )
        if (
            epoch.current_attempt_id != request.attempt
            or epoch.fencing_epoch_hash != record.fencing_epoch_hash
        ):
            raise FinalizationFenceError("V2 report fencing epoch mismatch")
        guarded = connection.execute(
            """
            UPDATE run_jobs
            SET lease_expires_at = lease_expires_at
            WHERE run_id = ?
              AND status = 'running'
              AND current_attempt_id = ?
              AND worker_id = ?
              AND lease_expires_at > ?
              AND EXISTS (
                  SELECT 1 FROM run_attempts AS attempt
                  WHERE attempt.attempt_id = run_jobs.current_attempt_id
                    AND attempt.run_id = run_jobs.run_id
                    AND attempt.attempt_number = ?
                    AND attempt.worker_id = run_jobs.worker_id
                    AND attempt.status = 'running'
              )
            """,
            (
                run_id,
                epoch.current_attempt_id,
                epoch.worker_id,
                now,
                epoch.attempt_number,
            ),
        )
        if guarded.rowcount != 1:
            raise FinalizationFenceError("V2 report finalization CAS refused")

        version_row = connection.execute(
            """
            SELECT COALESCE(MAX(artifact_version), 0) AS version
            FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'report_projection_manifest'
            """,
            (run_id,),
        ).fetchone()
        artifact_version = int(version_row["version"] or 0) + 1
        artifact_id = f"artifact_{uuid4().hex[:12]}"
        manifest_body = dumps(manifest.model_dump(mode="json"))
        manifest_sha = artifact_digest(manifest_body)
        connection.execute(
            """
            INSERT INTO run_artifacts
            (artifact_id, run_id, artifact_type, schema_version, content_json,
             sha256, created_at, attempt_id, step_id, artifact_version,
             supersedes_artifact_id)
            VALUES (?, ?, 'report_projection_manifest',
                    'report-projection-manifest.v2', ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                artifact_id,
                run_id,
                manifest_body,
                manifest_sha,
                now,
                request.attempt,
                step_id,
                artifact_version,
            ),
        )
        finalization_fault_hook("after_manifest_insert")
        binding = {
            "artifact_id": artifact_id,
            "artifact_type": "report_projection_manifest",
            "schema_version": "report-projection-manifest.v2",
            "sha256": manifest_sha,
            "attempt_id": request.attempt,
            "step_id": step_id,
            "artifact_version": artifact_version,
            "supersedes_artifact_id": None,
        }
        output = _report_step_output(
            manifest,
            artifact_id=artifact_id,
            artifact_binding=binding,
            fencing_epoch_hash=epoch.fencing_epoch_hash,
        )
        completed = connection.execute(
            """
            UPDATE run_steps
            SET status = 'completed', output_hash = ?, completed_at = ?,
                duration_ms = 0, error_code = NULL, artifact_refs = ?,
                output_json = ?
            WHERE step_id = ? AND status = 'running'
              AND attempt_id = ? AND step_version = 'report-generate.v2'
            """,
            (
                stable_hash(output),
                now,
                dumps([artifact_id]),
                dumps(output),
                step_id,
                request.attempt,
            ),
        )
        if completed.rowcount != 1:
            raise FinalizationFenceError("V2 report step completion CAS refused")
    return ReportFinalizationResult(
        manifest=manifest,
        artifact_id=artifact_id,
        step_id=step_id,
        recovered=False,
    )


def commit_replay_archive_v2(
    run_id: str,
    *,
    step_id: str,
    fencing_epoch,
    phase_durations_ms: dict[str, int] | None = None,
    adapter: StoredModeExecutionAdapter | None = None,
) -> ReplayFinalizationResult:
    """Rebuild proof, then atomically project and complete the lifecycle."""

    reconstruction = (adapter or StoredModeExecutionAdapter()).reconstruct(
        run_id,
        fencing_epoch=fencing_epoch,
    )
    expected_manifest = build_report_projection_manifest_v2(reconstruction)
    job = _job_projection_identity(run_id)
    completed_at = now_iso()
    prepared = prepare_war_room_result(
        job["project_id"],
        reconstruction.final_result,
        project_loader=lambda project_id: get_project_detail(project_id).project,
        now_factory=now_iso,
        started=job["started_at"],
        completed=completed_at,
        lifecycle_job_id=run_id,
    )
    with connect() as connection:
        if not is_postgres_url():
            connection.execute("BEGIN IMMEDIATE")
        replay_step = _load_current_step(
            connection,
            step_id=step_id,
            run_id=run_id,
            attempt_id=reconstruction.request.attempt,
            step_key="replay_archive",
            step_version="replay-archive.v2",
        )
        if replay_step["status"] != "running":
            raise FinalizationFenceError("V2 replay step is not running")
        _validate_replay_step_input(
            replay_step,
            expected_fencing_epoch_hash=reconstruction.record.fencing_epoch_hash,
        )
        report_step = connection.execute(
            """
            SELECT * FROM run_steps
            WHERE run_id = ? AND attempt_id = ?
              AND step_key = 'report_generate'
              AND step_version = 'report-generate.v2'
            """,
            (run_id, reconstruction.request.attempt),
        ).fetchall()
        report_rows = connection.execute(
            """
            SELECT * FROM run_artifacts
            WHERE run_id = ? AND attempt_id = ?
              AND artifact_type = 'report_projection_manifest'
              AND schema_version = 'report-projection-manifest.v2'
            """,
            (run_id, reconstruction.request.attempt),
        ).fetchall()
        if len(report_step) != 1 or report_step[0]["status"] != "completed":
            raise FinalizationFenceError("V2 replay requires one completed report step")
        _validate_report_step_input(
            report_step[0],
            expected_fencing_epoch_hash=reconstruction.record.fencing_epoch_hash,
        )
        _validate_completed_report(
            report_step[0],
            report_rows,
            expected_manifest=expected_manifest,
        )
        _require_no_active_projection(
            connection,
            run_id=run_id,
            project_id=job["project_id"],
            attempt_id=reconstruction.request.attempt,
        )
        try:
            epoch = worker_trust.capture_v2_fencing_epoch(
                connection,
                run_id=run_id,
                now=completed_at,
                lock_rows=is_postgres_url(),
                expected_fencing_epoch_hash=reconstruction.record.fencing_epoch_hash,
            )
        except V2ExecutionPathNotEnabledError as error:
            raise FinalizationFenceError(str(error)) from error
        guarded = connection.execute(
            """
            UPDATE run_jobs
            SET lease_expires_at = lease_expires_at
            WHERE run_id = ? AND status = 'running'
              AND current_attempt_id = ? AND worker_id = ?
              AND lease_expires_at > ?
              AND EXISTS (
                  SELECT 1 FROM run_attempts AS attempt
                  WHERE attempt.attempt_id = run_jobs.current_attempt_id
                    AND attempt.run_id = run_jobs.run_id
                    AND attempt.attempt_number = ?
                    AND attempt.worker_id = run_jobs.worker_id
                    AND attempt.status = 'running'
              )
            """,
            (
                run_id,
                epoch.current_attempt_id,
                epoch.worker_id,
                completed_at,
                epoch.attempt_number,
            ),
        )
        if guarded.rowcount != 1:
            raise FinalizationFenceError("V2 replay finalization CAS refused")
        _require_no_active_projection(
            connection,
            run_id=run_id,
            project_id=job["project_id"],
            attempt_id=reconstruction.request.attempt,
        )
        write_prepared_war_room_result(connection, prepared)
        finalization_fault_hook("after_research_projection")
        projection_binding = _insert_bound_artifact(
            connection,
            run_id=run_id,
            attempt_id=reconstruction.request.attempt,
            step_id=step_id,
            artifact_type="projection",
            schema_version="research-run-projection.v1",
            content={
                "project_id": job["project_id"],
                "result_run_id": prepared.run.run_id,
                "workspace_compatible": True,
            },
            created_at=completed_at,
        )
        metrics_payload = {
            "worker_id": epoch.worker_id,
            "attempt_count": epoch.attempt_number,
            "phase_durations_ms": dict(phase_durations_ms or {}),
            "event_count": int(
                connection.execute(
                    "SELECT COUNT(*) AS count FROM run_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()["count"]
            ),
            "engine_mode": reconstruction.request.engine_mode,
            "execution_contract_version": "kernel-mode-execution.v2",
            "execution_record_hash": reconstruction.record.record_hash,
            "fencing_epoch_hash": epoch.fencing_epoch_hash,
        }
        metrics_binding = _insert_bound_artifact(
            connection,
            run_id=run_id,
            attempt_id=reconstruction.request.attempt,
            step_id=step_id,
            artifact_type="lifecycle_metrics",
            schema_version="lifecycle-metrics.v2",
            content=metrics_payload,
            created_at=completed_at,
        )
        bindings = sorted(
            (projection_binding, metrics_binding),
            key=lambda item: item["artifact_id"].encode("utf-8"),
        )
        refs = [item["artifact_id"] for item in bindings]
        output = {
            "phase": "replay_archive",
            "progress": 100,
            "result_hash": expected_manifest.result_hash,
            "result_run_id": prepared.run.run_id,
            "execution_record_hash": reconstruction.record.record_hash,
            "manifest_hash": expected_manifest.manifest_hash,
            "fencing_epoch_hash": epoch.fencing_epoch_hash,
            "artifact_refs": refs,
            "artifact_bindings": bindings,
        }
        step_completed = connection.execute(
            """
            UPDATE run_steps
            SET status = 'completed', output_hash = ?, completed_at = ?,
                duration_ms = 0, error_code = NULL, artifact_refs = ?,
                output_json = ?
            WHERE step_id = ? AND status = 'running'
              AND attempt_id = ? AND step_version = 'replay-archive.v2'
            """,
            (
                stable_hash(output),
                completed_at,
                dumps(refs),
                dumps(output),
                step_id,
                reconstruction.request.attempt,
            ),
        )
        if step_completed.rowcount != 1:
            raise FinalizationFenceError("V2 replay step completion CAS refused")
        job_completed = connection.execute(
            """
            UPDATE run_jobs
            SET status = 'completed', current_phase = 'replay_archive',
                progress = 100, result_run_id = ?, completed_at = ?,
                updated_at = ?, terminal_reason = 'completed',
                worker_id = NULL, lease_expires_at = NULL
            WHERE run_id = ? AND status = 'running'
              AND current_attempt_id = ? AND worker_id = ?
            """,
            (
                prepared.run.run_id,
                completed_at,
                completed_at,
                run_id,
                reconstruction.request.attempt,
                epoch.worker_id,
            ),
        )
        attempt_completed = connection.execute(
            """
            UPDATE run_attempts
            SET status = 'completed', completed_at = ?
            WHERE attempt_id = ? AND run_id = ? AND worker_id = ?
              AND status = 'running'
            """,
            (
                completed_at,
                reconstruction.request.attempt,
                run_id,
                epoch.worker_id,
            ),
        )
        if job_completed.rowcount != 1 or attempt_completed.rowcount != 1:
            raise FinalizationFenceError("V2 terminal lifecycle CAS refused")
    return ReplayFinalizationResult(
        result_run_id=prepared.run.run_id,
        projection_artifact_id=projection_binding["artifact_id"],
        metrics_artifact_id=metrics_binding["artifact_id"],
        step_id=step_id,
    )


def _validate_completed_report(
    step,
    rows,
    *,
    expected_manifest: ReportProjectionManifestV2,
) -> ReportFinalizationResult:
    if len(rows) != 1:
        raise FinalizationFenceError(
            "completed V2 report must bind exactly one manifest Artifact"
        )
    row = rows[0]
    raw = row["content_json"]
    if not isinstance(raw, str) or artifact_digest(raw) != row["sha256"]:
        raise FinalizationFenceError("stored V2 report outer SHA mismatch")
    stored_manifest = ReportProjectionManifestV2.model_validate(
        _strict_json_object(raw, "stored V2 report manifest")
    )
    if stored_manifest != expected_manifest:
        raise FinalizationFenceError("stored V2 report manifest drift")
    output = _strict_json_object(step["output_json"], "completed V2 report output")
    refs = _strict_json_array(step["artifact_refs"], "completed V2 report refs")
    binding = {
        "artifact_id": row["artifact_id"],
        "artifact_type": row["artifact_type"],
        "schema_version": row["schema_version"],
        "sha256": row["sha256"],
        "attempt_id": row["attempt_id"],
        "step_id": row["step_id"],
        "artifact_version": int(row["artifact_version"]),
        "supersedes_artifact_id": row["supersedes_artifact_id"],
    }
    expected_output = _report_step_output(
        stored_manifest,
        artifact_id=row["artifact_id"],
        artifact_binding=binding,
        fencing_epoch_hash=stored_manifest.execution_record.fencing_epoch_hash,
    )
    if (
        refs != [row["artifact_id"]]
        or stable_hash(output) != step["output_hash"]
        or output != expected_output
    ):
        raise FinalizationFenceError("completed V2 report step binding drift")
    return ReportFinalizationResult(
        manifest=stored_manifest,
        artifact_id=row["artifact_id"],
        step_id=step["step_id"],
        recovered=True,
    )


def _job_projection_identity(run_id: str) -> dict:
    with connect() as connection:
        row = connection.execute(
            """
            SELECT project_id, started_at FROM run_jobs WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
    if row is None or not row["started_at"]:
        raise FinalizationFenceError("V2 replay job projection identity is missing")
    return {
        "project_id": row["project_id"],
        "started_at": row["started_at"],
    }


def _load_current_step(
    connection,
    *,
    step_id: str,
    run_id: str,
    attempt_id: str,
    step_key: str,
    step_version: str,
):
    row = connection.execute(
        """
        SELECT * FROM run_steps
        WHERE step_id = ? AND run_id = ? AND attempt_id = ?
          AND step_key = ? AND step_version = ?
        """,
        (step_id, run_id, attempt_id, step_key, step_version),
    ).fetchone()
    if row is None:
        raise FinalizationFenceError(f"current V2 {step_key} step is missing")
    return row


def _validate_replay_step_input(
    step,
    *,
    expected_fencing_epoch_hash: str,
) -> None:
    step_input = _strict_json_object(step["input_json"], "V2 replay step input")
    if stable_hash(step_input) != step["input_hash"]:
        raise FinalizationFenceError("V2 replay step input hash mismatch")
    raw_epoch = step_input.get("fencing_epoch")
    try:
        epoch = KernelModeFencingEpoch.model_validate(raw_epoch)
    except ValueError as error:
        raise FinalizationFenceError("V2 replay step fencing input is malformed") from error
    if epoch.fencing_epoch_hash != expected_fencing_epoch_hash:
        raise FinalizationFenceError("V2 replay step fencing input mismatch")


def _require_no_active_projection(
    connection,
    *,
    run_id: str,
    project_id: str,
    attempt_id: str,
) -> None:
    research_rows = connection.execute(
        "SELECT run_id, data_snapshot FROM research_runs WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    matching_research = [
        row["run_id"]
        for row in research_rows
        if loads(row["data_snapshot"], {}).get("lifecycle_job_id") == run_id
    ]
    projection_rows = connection.execute(
        """
        SELECT artifact_id FROM run_artifacts
        WHERE run_id = ? AND artifact_type = 'projection'
        """,
        (run_id,),
    ).fetchall()
    if matching_research or projection_rows:
        raise FinalizationFenceError(
            f"active V2 attempt {attempt_id} already has a research projection"
        )


def _insert_bound_artifact(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    step_id: str,
    artifact_type: str,
    schema_version: str,
    content: dict,
    created_at: str,
) -> dict:
    existing = connection.execute(
        """
        SELECT COUNT(*) AS count FROM run_artifacts
        WHERE run_id = ? AND artifact_type = ?
        """,
        (run_id, artifact_type),
    ).fetchone()
    if int(existing["count"] or 0) != 0:
        raise FinalizationFenceError(
            f"V2 terminal Artifact already exists: {artifact_type}"
        )
    artifact_id = f"artifact_{uuid4().hex[:12]}"
    body = dumps(content)
    sha256 = artifact_digest(body)
    connection.execute(
        """
        INSERT INTO run_artifacts
        (artifact_id, run_id, artifact_type, schema_version, content_json,
         sha256, created_at, attempt_id, step_id, artifact_version,
         supersedes_artifact_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, NULL)
        """,
        (
            artifact_id,
            run_id,
            artifact_type,
            schema_version,
            body,
            sha256,
            created_at,
            attempt_id,
            step_id,
        ),
    )
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "schema_version": schema_version,
        "sha256": sha256,
        "attempt_id": attempt_id,
        "step_id": step_id,
        "artifact_version": 1,
        "supersedes_artifact_id": None,
    }


def _validate_report_step_input(
    step,
    *,
    expected_fencing_epoch_hash: str,
) -> None:
    step_input = _strict_json_object(step["input_json"], "V2 report step input")
    if stable_hash(step_input) != step["input_hash"]:
        raise FinalizationFenceError("V2 report step input hash mismatch")
    fencing_epoch = step_input.get("fencing_epoch")
    if (
        not isinstance(fencing_epoch, dict)
        or fencing_epoch.get("fencing_epoch_hash")
        != expected_fencing_epoch_hash
    ):
        raise FinalizationFenceError("V2 report step fencing input mismatch")


def _report_step_output(
    manifest: ReportProjectionManifestV2,
    *,
    artifact_id: str,
    artifact_binding: dict,
    fencing_epoch_hash: str,
) -> dict:
    return {
        "phase": "report_generate",
        "progress": 88,
        "result_hash": manifest.result_hash,
        "execution_record_hash": manifest.execution_record.record_hash,
        "proof_hash": manifest.proof_hash,
        "manifest_hash": manifest.manifest_hash,
        "fencing_epoch_hash": fencing_epoch_hash,
        "artifact_refs": [artifact_id],
        "artifact_bindings": [artifact_binding],
    }
