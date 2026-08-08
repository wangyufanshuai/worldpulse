"""Stored-proof reconstruction boundary for Kernel mode finalization."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import WarRoomRun
from app.services.consistency.hashing import stable_hash
from app.services.negotiation import extract_consistency_claims
from app.services.project_store import connect, dumps
from app.services.simulation_kernel import (
    KernelModeExecutionProof,
    KernelModeExecutionRecord,
    KernelModeExecutionRequest,
    KernelModeProofReference,
    SimulationKernelApplicationPort,
    normalize_kernel_mode,
    simulation_kernel_service,
)
from app.services.simulation_kernel.war_room_projection import (
    build_war_room_projection,
)

from .execution_contract import (
    KernelModeFencingEpoch,
    select_execution_contract,
)
from .integrity import artifact_digest


class ModeExecutionAdapterError(ValueError):
    """Stored lifecycle state cannot produce one authoritative Kernel request."""


class ReportProjectionManifestV2(BaseModel):
    """Closed report checkpoint embedding the compact Kernel authority record."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: str = Field(pattern=r"^report-projection-manifest\.v2$")
    result_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    workspace_compatible: bool
    run_diff_compatible: bool
    replay_pack_compatible: bool
    execution_record: KernelModeExecutionRecord
    proof_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_manifest(self) -> "ReportProjectionManifestV2":
        if not (
            self.workspace_compatible
            and self.run_diff_compatible
            and self.replay_pack_compatible
        ):
            raise ValueError("V2 report compatibility flags must all be true")
        if self.result_hash != self.execution_record.final_source_run_hash:
            raise ValueError("V2 report result hash does not match execution record")
        if self.proof_hash != self.execution_record.proof_hash:
            raise ValueError("V2 report proof hash does not match execution record")
        expected = stable_hash(
            self.model_dump(mode="json", exclude={"manifest_hash"})
        )
        if self.manifest_hash != expected:
            raise ValueError("V2 report manifest_hash mismatch")
        return self


@dataclass(frozen=True)
class ModeExecutionReconstruction:
    request: KernelModeExecutionRequest
    record: KernelModeExecutionRecord
    final_result: WarRoomRun


@dataclass(frozen=True)
class _BoundArtifact:
    artifact_id: str
    artifact_type: str
    schema_version: str
    sha256: str
    payload: dict[str, Any]


class StoredModeExecutionAdapter:
    """Reconstruct typed proof only from outer-SHA-verified current-attempt rows."""

    def __init__(
        self,
        kernel: SimulationKernelApplicationPort = simulation_kernel_service,
    ) -> None:
        self._kernel = kernel

    def reconstruct(
        self,
        run_id: str,
        *,
        fencing_epoch: KernelModeFencingEpoch,
        caller_record: KernelModeExecutionRecord | dict[str, Any] | None = None,
    ) -> ModeExecutionReconstruction:
        with connect() as connection:
            ownership_rows = connection.execute(
                """
                SELECT job.run_id, job.project_id, ownership.organization_id,
                       job.engine_mode, job.status, job.current_attempt_id,
                       job.worker_id, job.seed, job.rule_pack_id,
                       job.rule_pack_hash, job.runtime_profile_json,
                       job.runtime_profile_hash
                FROM run_jobs AS job
                JOIN organization_resources AS ownership
                  ON ownership.resource_type = 'project'
                 AND ownership.resource_id = job.project_id
                WHERE job.run_id = ?
                """,
                (run_id,),
            ).fetchall()
            if len(ownership_rows) != 1:
                raise ModeExecutionAdapterError(
                    "V2 lifecycle ownership tuple must resolve exactly once"
                )
            job = ownership_rows[0]
            profile = _strict_json_object(job["runtime_profile_json"], "runtime profile")
            selection = select_execution_contract(profile)
            if not selection.is_v2 or selection.profile is None:
                raise ModeExecutionAdapterError("mode reconstruction requires exact V2")
            if (
                not isinstance(job["runtime_profile_hash"], str)
                or stable_hash(profile) != job["runtime_profile_hash"]
            ):
                raise ModeExecutionAdapterError("runtime profile hash mismatch")
            if job["status"] != "running":
                raise ModeExecutionAdapterError("mode reconstruction requires a running job")
            if (
                job["current_attempt_id"] != fencing_epoch.current_attempt_id
                or job["worker_id"] != fencing_epoch.worker_id
            ):
                raise ModeExecutionAdapterError("fencing epoch ownership mismatch")
            if job["engine_mode"] != "deterministic":
                raise ModeExecutionAdapterError(
                    "this reconstruction slice currently admits deterministic mode only"
                )
            if type(job["seed"]) is not int or job["seed"] != selection.profile.effective_seed:
                raise ModeExecutionAdapterError("job seed does not match V2 runtime profile")
            if not job["rule_pack_id"] or not job["rule_pack_hash"]:
                raise ModeExecutionAdapterError("V2 job is missing its pinned Rule Pack")

            baseline_artifact = _load_exact_bound_artifact(
                connection,
                run_id=run_id,
                attempt_id=fencing_epoch.current_attempt_id,
                artifact_type="war_room_result",
                schema_version="war-room-result.v1",
                producing_step_key="deterministic_run",
                producing_step_version="deterministic-run.v1",
            )
            consistency_artifact = _load_exact_bound_artifact(
                connection,
                run_id=run_id,
                attempt_id=fencing_epoch.current_attempt_id,
                artifact_type="consistency_audit",
                schema_version="consistency-audit.v3",
                producing_step_key="consistency_audit",
                producing_step_version="consistency-audit-step.v1",
            )

        baseline = WarRoomRun.model_validate(baseline_artifact.payload)
        projection = build_war_room_projection(
            baseline,
            run_id=run_id,
            seed=selection.profile.effective_seed,
            rule_pack_hash=job["rule_pack_hash"],
        )
        claims = extract_consistency_claims(
            consistency_artifact.payload,
            run_id=run_id,
            role="final",
            tick=None,
            evaluator_version=selection.profile.evaluator_version,
            agent_pack_id=None,
            agent_pack_hash=None,
            constraint_context_hash=None,
            complete_proposals=(),
        )
        claims_hash = stable_hash(
            {
                "claims": claims.model_dump(mode="json"),
                "proof_schema": "kp.final-consistency.v1",
            }
        )
        reference = KernelModeProofReference(
            proof_schema="kp.final-consistency.v1",
            artifact_type=consistency_artifact.artifact_type,
            schema_version=consistency_artifact.schema_version,
            artifact_id=consistency_artifact.artifact_id,
            run_id=run_id,
            session_id=None,
            attempt=fencing_epoch.current_attempt_id,
            ordinal=0,
            tick=None,
            artifact_sha256=consistency_artifact.sha256,
            content_hash=claims.audit_hash,
            claims=claims,
            claims_hash=claims_hash,
            relationships=(),
        )
        proof_payload = {
            "schema_version": "kernel-mode-execution-proof.v1",
            "references": [reference.model_dump(mode="json")],
        }
        proof = KernelModeExecutionProof.model_validate(
            {**proof_payload, "proof_hash": stable_hash(proof_payload)}
        )
        request_payload = {
            "schema_version": "kernel-mode-execution-request.v1",
            "execution_contract_version": "kernel-mode-execution.v2",
            "organization_id": job["organization_id"],
            "project_id": job["project_id"],
            "lifecycle_job_id": run_id,
            "run_id": run_id,
            "session_id": None,
            "attempt": fencing_epoch.current_attempt_id,
            "engine_mode": job["engine_mode"],
            "kernel_mode": normalize_kernel_mode(job["engine_mode"]),
            "effective_seed": selection.profile.effective_seed,
            "rule_pack_id": job["rule_pack_id"],
            "rule_pack_hash": job["rule_pack_hash"],
            "agent_pack_id": None,
            "agent_pack_hash": None,
            "constraint_context_hash": None,
            "evaluator_version": selection.profile.evaluator_version,
            "runtime_profile_hash": job["runtime_profile_hash"],
            "fencing_epoch_hash": fencing_epoch.fencing_epoch_hash,
            "baseline_projection": projection.model_dump(mode="json"),
            "final_projection": projection.model_dump(mode="json"),
            "proof": proof.model_dump(mode="json"),
            "proof_hash": proof.proof_hash,
        }
        request = KernelModeExecutionRequest.model_validate(
            {**request_payload, "request_hash": stable_hash(request_payload)}
        )
        record = self._kernel.finalize_execution(request)
        if caller_record is not None:
            supplied = KernelModeExecutionRecord.model_validate(caller_record)
            if supplied != record:
                raise ModeExecutionAdapterError(
                    "caller execution record does not match reconstructed authority"
                )
        return ModeExecutionReconstruction(
            request=request,
            record=record,
            final_result=baseline,
        )


def build_report_projection_manifest_v2(
    reconstruction: ModeExecutionReconstruction,
) -> ReportProjectionManifestV2:
    result_hash = stable_hash(
        reconstruction.final_result.model_dump(mode="json")
    )
    payload = {
        "schema_version": "report-projection-manifest.v2",
        "result_hash": result_hash,
        "workspace_compatible": True,
        "run_diff_compatible": True,
        "replay_pack_compatible": True,
        "execution_record": reconstruction.record.model_dump(mode="json"),
        "proof_hash": reconstruction.record.proof_hash,
    }
    return ReportProjectionManifestV2.model_validate(
        {**payload, "manifest_hash": stable_hash(payload)}
    )


def _load_exact_bound_artifact(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    artifact_type: str,
    schema_version: str,
    producing_step_key: str,
    producing_step_version: str,
) -> _BoundArtifact:
    rows = connection.execute(
        """
        SELECT artifact.artifact_id, artifact.artifact_type,
               artifact.schema_version, artifact.content_json, artifact.sha256,
               artifact.attempt_id AS artifact_attempt_id,
               artifact.step_id, artifact.artifact_version,
               artifact.supersedes_artifact_id,
               step.step_key, step.step_version,
               step.status AS step_status, step.input_json, step.input_hash,
               step.output_json, step.output_hash,
               step.artifact_refs AS step_artifact_refs
        FROM run_artifacts AS artifact
        JOIN run_steps AS step ON step.step_id = artifact.step_id
        WHERE artifact.run_id = ?
          AND artifact.attempt_id = ?
          AND artifact.artifact_type = ?
          AND artifact.schema_version = ?
        ORDER BY artifact.artifact_version ASC, artifact.artifact_id ASC
        """,
        (run_id, attempt_id, artifact_type, schema_version),
    ).fetchall()
    bound: list[_BoundArtifact] = []
    for row in rows:
        raw_content = row["content_json"]
        if not isinstance(raw_content, str) or artifact_digest(raw_content) != row["sha256"]:
            raise ModeExecutionAdapterError(
                f"{artifact_type} outer Artifact SHA mismatch"
            )
        payload = _strict_json_object(raw_content, f"{artifact_type} Artifact")
        if (
            row["step_key"] != producing_step_key
            or row["step_version"] != producing_step_version
            or row["step_status"] != "completed"
        ):
            continue
        step_input = _strict_json_object(row["input_json"], "producing step input")
        step_output = _strict_json_object(row["output_json"], "producing step output")
        artifact_refs = _strict_json_array(
            row["step_artifact_refs"],
            "producing step Artifact refs",
        )
        output_refs = step_output.get("artifact_refs")
        artifact_bindings = step_output.get("artifact_bindings")
        if (
            stable_hash(step_input) != row["input_hash"]
            or stable_hash(step_output) != row["output_hash"]
            or not isinstance(output_refs, list)
            or any(not isinstance(item, str) for item in output_refs)
            or any(not isinstance(item, str) for item in artifact_refs)
            or sorted(output_refs) != sorted(artifact_refs)
        ):
            raise ModeExecutionAdapterError("producing step hash root mismatch")
        binding = _validated_artifact_binding(
            artifact_bindings,
            artifact_refs=artifact_refs,
            row=row,
        )
        if row["artifact_id"] in artifact_refs:
            if binding is None:
                raise ModeExecutionAdapterError(
                    "producing step does not bind the selected Artifact"
                )
            bound.append(
                _BoundArtifact(
                    artifact_id=row["artifact_id"],
                    artifact_type=row["artifact_type"],
                    schema_version=row["schema_version"],
                    sha256=row["sha256"],
                    payload=payload,
                )
            )
    if len(bound) != 1:
        raise ModeExecutionAdapterError(
            f"expected one bound {artifact_type} Artifact, found {len(bound)}"
        )
    return bound[0]


def _validated_artifact_binding(
    raw_bindings: object,
    *,
    artifact_refs: list[Any],
    row,
) -> dict[str, Any] | None:
    if not isinstance(raw_bindings, list):
        raise ModeExecutionAdapterError(
            "V2 producing step is missing complete Artifact bindings"
        )
    expected_keys = {
        "artifact_id",
        "artifact_type",
        "schema_version",
        "sha256",
        "attempt_id",
        "step_id",
        "artifact_version",
        "supersedes_artifact_id",
    }
    if any(not isinstance(item, dict) or set(item) != expected_keys for item in raw_bindings):
        raise ModeExecutionAdapterError("V2 Artifact binding is not closed")
    binding_ids = [item["artifact_id"] for item in raw_bindings]
    if (
        any(not isinstance(item, str) for item in binding_ids)
        or binding_ids
        != sorted(set(binding_ids), key=lambda value: value.encode("utf-8"))
        or sorted(binding_ids) != sorted(artifact_refs)
    ):
        raise ModeExecutionAdapterError(
            "V2 Artifact bindings do not exactly cover producing step refs"
        )
    selected = next(
        (item for item in raw_bindings if item["artifact_id"] == row["artifact_id"]),
        None,
    )
    if selected is None:
        return None
    expected = {
        "artifact_id": row["artifact_id"],
        "artifact_type": row["artifact_type"],
        "schema_version": row["schema_version"],
        "sha256": row["sha256"],
        "attempt_id": row["artifact_attempt_id"],
        "step_id": row["step_id"],
        "artifact_version": int(row["artifact_version"]),
        "supersedes_artifact_id": row["supersedes_artifact_id"],
    }
    if selected != expected:
        raise ModeExecutionAdapterError("V2 Artifact binding does not match its row")
    return selected


def _strict_json_object(raw: object, field_name: str) -> dict[str, Any]:
    value = _strict_json(raw, field_name)
    if not isinstance(value, dict):
        raise ModeExecutionAdapterError(f"{field_name} must be an object")
    return value


def _strict_json_array(raw: object, field_name: str) -> list[Any]:
    value = _strict_json(raw, field_name)
    if not isinstance(value, list):
        raise ModeExecutionAdapterError(f"{field_name} must be an array")
    return value


def _strict_json(raw: object, field_name: str) -> Any:
    if not isinstance(raw, str):
        raise ModeExecutionAdapterError(f"{field_name} must be UTF-8 JSON text")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ModeExecutionAdapterError(
                    f"{field_name} contains a duplicate object key"
                )
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise ModeExecutionAdapterError(
            f"{field_name} contains a non-finite number: {value}"
        )

    try:
        raw.encode("utf-8", errors="strict")
        value = json.loads(
            raw,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
        canonical = dumps(value)
        canonical.encode("utf-8", errors="strict")
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ModeExecutionAdapterError(
            f"{field_name} is not strict UTF-8 JSON"
        ) from error
    if canonical != raw:
        raise ModeExecutionAdapterError(f"{field_name} is not canonical JSON")
    return value
