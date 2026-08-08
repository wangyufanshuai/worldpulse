"""Atomic V2 report checkpoint persistence under GOV-FINALIZE-FENCE-1."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.db.postgres import is_postgres_url
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps

from . import worker_trust
from .execution_contract import V2ExecutionPathNotEnabledError
from .integrity import artifact_digest
from .mode_execution_adapter import (
    ModeExecutionReconstruction,
    ReportProjectionManifestV2,
    _strict_json_array,
    _strict_json_object,
    build_report_projection_manifest_v2,
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
