"""Stored-proof reconstruction boundary for Kernel mode finalization."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.models import WarRoomRun
from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.negotiation import (
    AgentRuntimeResultSource,
    KernelProposalBatchSource,
    build_audit_only_projection_source,
    build_consistency_audit_source,
    build_kernel_proposal_batch_source,
    extract_ar_claims,
    extract_consistency_claims,
    extract_pa_claims,
    extract_pb_claims,
)
from app.services.project_store import connect, dumps
from app.services.simulation_kernel import (
    KernelModeExecutionProof,
    KernelModeExecutionRecord,
    KernelModeExecutionRequest,
    KernelModeProofReference,
    KernelModeProofRelationship,
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
from .mode_context import build_resolved_mock_agent_batch, resolve_mode_context
from .source_roots import (
    RootArtifact,
    validate_mode_proof_step_root,
    validate_resolver_step_root,
)


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
    attempt_id: str | None = None
    supersedes_artifact_id: str | None = None


@dataclass(frozen=True)
class HistoricalRuntimeSource:
    artifact_id: str
    artifact_sha256: str
    content_hash: str
    attempt_id: str
    attempt_number: int
    payload: dict[str, Any]


def load_controlled_retry_runtime(
    run_id: str,
    *,
    current_attempt_id: str,
) -> HistoricalRuntimeSource:
    """Authenticate the unique latest failed-attempt AR for provider-free retry."""

    with connect() as connection:
        current = connection.execute(
            """
            SELECT job.engine_mode, attempt.attempt_number
            FROM run_jobs AS job
            JOIN run_attempts AS attempt
              ON attempt.attempt_id = job.current_attempt_id
             AND attempt.run_id = job.run_id
            WHERE job.run_id = ? AND attempt.attempt_id = ?
            """,
            (run_id, current_attempt_id),
        ).fetchone()
        if (
            current is None
            or current["engine_mode"] != "controlled_agent"
            or int(current["attempt_number"]) <= 1
        ):
            raise ModeExecutionAdapterError(
                "controlled retry requires a later current attempt"
            )
        candidates = connection.execute(
            """
            SELECT attempt_id, attempt_number
            FROM run_attempts
            WHERE run_id = ?
              AND status IN ('failed', 'abandoned')
              AND attempt_number < ?
            ORDER BY attempt_number DESC
            """,
            (run_id, int(current["attempt_number"])),
        ).fetchall()
        if not candidates:
            raise ModeExecutionAdapterError(
                "controlled retry has no eligible failed historical attempt"
            )
        selected_number = int(candidates[0]["attempt_number"])
        selected = [
            item
            for item in candidates
            if int(item["attempt_number"]) == selected_number
        ]
        if len(selected) != 1:
            raise ModeExecutionAdapterError(
                "controlled retry historical attempt is ambiguous"
            )
        historical_attempt = selected[0]["attempt_id"]
        step, artifacts = _load_rooted_step(
            connection,
            run_id=run_id,
            attempt_id=historical_attempt,
            step_key="consistency_audit",
            step_version="consistency-audit-step.v1",
        )
        raw_refs = step["output"].get("artifact_refs")
        if not isinstance(raw_refs, list):
            raise ModeExecutionAdapterError(
                "historical controlled proof root has malformed refs"
            )
        ordered_ids = tuple(
            item[1]
            for item in raw_refs
            if isinstance(item, list) and len(item) == 6
        )
        by_id = {item.artifact_id: item for item in artifacts}
        if len(ordered_ids) != len(raw_refs) or set(ordered_ids) != set(by_id):
            raise ModeExecutionAdapterError(
                "historical controlled proof root membership mismatch"
            )
        ordered = tuple(by_id[item] for item in ordered_ids)
        validate_mode_proof_step_root(
            step["output"],
            run_id=run_id,
            attempt=historical_attempt,
            engine_mode="controlled_agent",
            artifacts=ordered,
        )
        runtime_sources = [
            item for item in ordered if item.artifact_type == "agent_runtime_audit"
        ]
        if len(runtime_sources) != 1:
            raise ModeExecutionAdapterError(
                "historical controlled proof must contain exactly one AR"
            )
        runtime = runtime_sources[0]
        source = AgentRuntimeResultSource.model_validate(runtime.payload)
        return HistoricalRuntimeSource(
            artifact_id=runtime.artifact_id,
            artifact_sha256=runtime.sha256,
            content_hash=source.runtime_hash,
            attempt_id=historical_attempt,
            attempt_number=selected_number,
            payload=source.model_dump(mode="json"),
        )


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
                       job.runtime_profile_hash, job.scenario_json,
                       active_attempt.attempt_number
                FROM run_jobs AS job
                JOIN run_attempts AS active_attempt
                  ON active_attempt.attempt_id = job.current_attempt_id
                 AND active_attempt.run_id = job.run_id
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
            if job["engine_mode"] not in {
                "deterministic",
                "mock_agent",
                "controlled_agent",
            }:
                raise ModeExecutionAdapterError(
                    "this reconstruction slice does not admit the requested engine mode"
                )
            if type(job["seed"]) is not int or job["seed"] != selection.profile.effective_seed:
                raise ModeExecutionAdapterError("job seed does not match V2 runtime profile")
            if not job["rule_pack_id"] or not job["rule_pack_hash"]:
                raise ModeExecutionAdapterError("V2 job is missing its pinned Rule Pack")

            agent_pack_artifact = None
            context_artifact = None
            proposal_artifact = None
            projection_audit_artifact = None
            runtime_artifact = None
            if job["engine_mode"] == "deterministic":
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
            else:
                rooted = _load_audit_only_source_roots(
                    connection,
                    job=job,
                    profile=selection.profile,
                    run_id=run_id,
                    attempt_id=fencing_epoch.current_attempt_id,
                )
                baseline_artifact = _bound_from_root(rooted["war_room_result"])
                agent_pack_artifact = _bound_from_root(rooted["agent_pack"])
                context_artifact = _bound_from_root(
                    rooted["agent_constraint_context"]
                )
                proposal_artifact = _bound_from_root(
                    rooted["agent_action_proposals"]
                )
                if job["engine_mode"] == "controlled_agent":
                    runtime_artifact = _bound_from_root(
                        rooted["agent_runtime_audit"]
                    )
                consistency_artifact = _bound_from_root(
                    rooted["consistency_audit"]
                )
                projection_root = rooted.get("agent_action_projection_audit")
                projection_audit_artifact = (
                    _bound_from_root(projection_root)
                    if projection_root is not None
                    else None
                )

        baseline = WarRoomRun.model_validate(baseline_artifact.payload)
        projection = build_war_room_projection(
            baseline,
            run_id=run_id,
            seed=selection.profile.effective_seed,
            rule_pack_hash=job["rule_pack_hash"],
        )
        agent_pack_id: str | None = None
        agent_pack_hash: str | None = None
        constraint_context_hash: str | None = None
        historical_runtime_source: HistoricalRuntimeSource | None = None
        references: list[KernelModeProofReference] = []
        if job["engine_mode"] == "deterministic":
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
            references.append(
                _proof_reference(
                    artifact=consistency_artifact,
                    proof_schema="kp.final-consistency.v1",
                    claims=claims,
                    content_hash=claims.audit_hash,
                    run_id=run_id,
                    attempt=fencing_epoch.current_attempt_id,
                    ordinal=0,
                )
            )
        else:
            if (
                agent_pack_artifact is None
                or context_artifact is None
                or proposal_artifact is None
            ):
                raise ModeExecutionAdapterError("audit-only resolver/PB sources are incomplete")
            resolved = resolve_mode_context(
                baseline,
                effective_seed=selection.profile.effective_seed,
            )
            stored_agent_pack = type(resolved.agent_pack).model_validate(
                agent_pack_artifact.payload,
                strict=True,
            )
            stored_context = type(resolved.constraint_context).model_validate(
                context_artifact.payload,
                strict=True,
            )
            if stored_agent_pack != resolved.agent_pack or stored_context != resolved.constraint_context:
                raise ModeExecutionAdapterError(
                    "stored audit-only resolver payload differs from provider-free reconstruction"
                )
            agent_pack_id = resolved.agent_pack.agent_pack_id
            agent_pack_hash = resolved.agent_pack_hash
            constraint_context_hash = resolved.constraint_context_hash

            stored_pb = KernelProposalBatchSource.model_validate(
                proposal_artifact.payload
            )
            if job["engine_mode"] == "mock_agent":
                mock_batch = build_resolved_mock_agent_batch(
                    baseline,
                    run_id=run_id,
                    effective_seed=selection.profile.effective_seed,
                    context=resolved,
                )
                authoritative_proposals = tuple(mock_batch.proposals)
                expected_pb = build_kernel_proposal_batch_source(
                    run_id=run_id,
                    proposals=authoritative_proposals,
                    source_kind="mock_batch",
                    mock_batch=mock_batch,
                )
                pb_claims = extract_pb_claims(
                    proposal_artifact.payload,
                    run_id=run_id,
                    mock_batch_payload=mock_batch.model_dump(mode="json"),
                )
            else:
                if runtime_artifact is None:
                    raise ModeExecutionAdapterError(
                        "controlled_agent proof is missing AR"
                    )
                stored_runtime = AgentRuntimeResultSource.model_validate(
                    runtime_artifact.payload
                )
                if stable_hash(stored_runtime.constraint_context) != stable_hash(
                    resolved.runtime_constraint_context.model_dump(mode="json")
                ):
                    raise ModeExecutionAdapterError(
                        "controlled_agent AR context differs from the resolver"
                    )
                if int(job["attempt_number"]) > 1:
                    historical_runtime_source = load_controlled_retry_runtime(
                        run_id,
                        current_attempt_id=fencing_epoch.current_attempt_id,
                    )
                    if (
                        runtime_artifact.supersedes_artifact_id
                        != historical_runtime_source.artifact_id
                        or runtime_artifact.payload
                        != historical_runtime_source.payload
                        or stored_runtime.runtime_hash
                        != historical_runtime_source.content_hash
                    ):
                        raise ModeExecutionAdapterError(
                            "controlled_agent AR retry lineage/payload mismatch"
                        )
                elif runtime_artifact.supersedes_artifact_id is not None:
                    raise ModeExecutionAdapterError(
                        "first controlled_agent attempt may not supersede AR"
                    )
                authoritative_proposals = tuple(
                    AgentActionProposal.model_validate(item)
                    for item in stored_runtime.proposals
                )
                expected_pb = build_kernel_proposal_batch_source(
                    run_id=run_id,
                    proposals=authoritative_proposals,
                    source_kind="agent_runtime",
                    runtime_hash=stored_runtime.runtime_hash,
                )
                pb_claims = extract_pb_claims(
                    proposal_artifact.payload,
                    run_id=run_id,
                    expected_runtime_hash=stored_runtime.runtime_hash,
                )
            if stored_pb.model_dump(mode="json") != expected_pb.model_dump(mode="json"):
                raise ModeExecutionAdapterError(
                    "stored audit-only PB differs from its authenticated source"
                )
            complete_proposals = tuple(stored_pb.proposals)

            recomputed_report = evaluate_war_room_result(
                baseline,
                run_id=run_id,
                created_at="2000-01-01T00:00:00.000Z",
                proposals=list(authoritative_proposals),
                constraint_context=resolved.runtime_constraint_context,
            )
            expected_fc = build_consistency_audit_source(
                recomputed_report,
                run_id=run_id,
                role="final",
                tick=None,
                evaluator_version=selection.profile.evaluator_version,
                agent_pack_id=agent_pack_id,
                agent_pack_hash=agent_pack_hash,
                constraint_context_hash=constraint_context_hash,
                complete_proposals=authoritative_proposals,
            )
            if consistency_artifact.payload != expected_fc.model_dump(mode="json"):
                raise ModeExecutionAdapterError(
                    "stored audit-only FC differs from evaluator reconstruction"
                )
            fc_claims = extract_consistency_claims(
                consistency_artifact.payload,
                run_id=run_id,
                role="final",
                tick=None,
                evaluator_version=selection.profile.evaluator_version,
                agent_pack_id=agent_pack_id,
                agent_pack_hash=agent_pack_hash,
                constraint_context_hash=constraint_context_hash,
                complete_proposals=complete_proposals,
            )
            pb_relationships: tuple[KernelModeProofRelationship, ...] = ()
            if job["engine_mode"] == "controlled_agent":
                if runtime_artifact is None:
                    raise ModeExecutionAdapterError(
                        "controlled_agent proof is missing AR"
                    )
                ar_claims = extract_ar_claims(
                    runtime_artifact.payload,
                    run_id=run_id,
                )
                ar_reference = _proof_reference(
                    artifact=runtime_artifact,
                    proof_schema="kp.agent-runtime.v1",
                    claims=ar_claims,
                    content_hash=ar_claims.runtime_hash,
                    run_id=run_id,
                    attempt=fencing_epoch.current_attempt_id,
                    ordinal=0,
                    relationships=(
                        (
                            KernelModeProofRelationship(
                                relationship_type="supersedes",
                                target_artifact_id=(
                                    historical_runtime_source.artifact_id
                                ),
                                target_content_hash=(
                                    historical_runtime_source.content_hash
                                ),
                                target_attempt=(
                                    historical_runtime_source.attempt_id
                                ),
                            ),
                        )
                        if historical_runtime_source is not None
                        else ()
                    ),
                )
                references.append(ar_reference)
                pb_relationships = (
                    _relationship("generated_by", ar_reference),
                )
            pb_reference = _proof_reference(
                artifact=proposal_artifact,
                proof_schema="kp.proposal-batch.v1",
                claims=pb_claims,
                content_hash=pb_claims.batch_hash,
                run_id=run_id,
                attempt=fencing_epoch.current_attempt_id,
                ordinal=len(references),
                relationships=pb_relationships,
            )
            references.append(pb_reference)
            fc_reference = _proof_reference(
                artifact=consistency_artifact,
                proof_schema="kp.final-consistency.v1",
                claims=fc_claims,
                content_hash=fc_claims.audit_hash,
                run_id=run_id,
                attempt=fencing_epoch.current_attempt_id,
                ordinal=len(references),
                relationships=(
                    _relationship("evaluates", pb_reference),
                ),
            )
            references.append(fc_reference)

            if pb_claims.proposal_count == 0:
                if projection_audit_artifact is not None:
                    raise ModeExecutionAdapterError(
                        "zero-proposal audit-only proof may not contain PA"
                    )
            else:
                if projection_audit_artifact is None:
                    raise ModeExecutionAdapterError(
                        "nonzero-proposal audit-only proof requires PA"
                    )
                expected_pa = build_audit_only_projection_source(
                    run_id=run_id,
                    consistency_audit_hash=expected_fc.audit_hash,
                    final_result_hash=stable_hash(baseline.model_dump(mode="json")),
                    proposals=authoritative_proposals,
                    decisions=tuple(recomputed_report.proposal_decisions),
                )
                if projection_audit_artifact.payload != expected_pa.model_dump(mode="json"):
                    raise ModeExecutionAdapterError(
                        "stored PA differs from audit-only reconstruction"
                    )
                pa_claims = extract_pa_claims(
                    projection_audit_artifact.payload,
                    run_id=run_id,
                    session_id=None,
                    tick=None,
                    projection_mode="audit_only",
                    consistency_audit_hash=expected_fc.audit_hash,
                    complete_proposals=complete_proposals,
                    modifier_claims=None,
                )
                references.append(
                    _proof_reference(
                        artifact=projection_audit_artifact,
                        proof_schema="kp.projection-audit.v1",
                        claims=pa_claims,
                        content_hash=pa_claims.audit_hash,
                        run_id=run_id,
                        attempt=fencing_epoch.current_attempt_id,
                        ordinal=len(references),
                        relationships=(
                            _relationship("covers", pb_reference),
                            _relationship("governed_by", fc_reference),
                        ),
                    )
                )

        proof_payload = {
            "schema_version": "kernel-mode-execution-proof.v1",
            "references": [item.model_dump(mode="json") for item in references],
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
            "agent_pack_id": agent_pack_id,
            "agent_pack_hash": agent_pack_hash,
            "constraint_context_hash": constraint_context_hash,
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


def _relationship(
    relationship_type: Any,
    target: KernelModeProofReference,
) -> KernelModeProofRelationship:
    return KernelModeProofRelationship(
        relationship_type=relationship_type,
        target_artifact_id=target.artifact_id,
        target_content_hash=target.content_hash,
        target_attempt=None,
    )


def _proof_reference(
    *,
    artifact: _BoundArtifact,
    proof_schema: Any,
    claims: Any,
    content_hash: str,
    run_id: str,
    attempt: str,
    ordinal: int,
    relationships: tuple[KernelModeProofRelationship, ...] = (),
) -> KernelModeProofReference:
    claims_hash = stable_hash(
        {
            "claims": claims.model_dump(mode="json"),
            "proof_schema": proof_schema,
        }
    )
    return KernelModeProofReference(
        proof_schema=proof_schema,
        artifact_type=artifact.artifact_type,
        schema_version=artifact.schema_version,
        artifact_id=artifact.artifact_id,
        run_id=run_id,
        session_id=None,
        attempt=attempt,
        ordinal=ordinal,
        tick=None,
        artifact_sha256=artifact.sha256,
        content_hash=content_hash,
        claims=claims,
        claims_hash=claims_hash,
        relationships=relationships,
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


def _bound_from_root(artifact: RootArtifact) -> _BoundArtifact:
    return _BoundArtifact(
        artifact_id=artifact.artifact_id,
        artifact_type=artifact.artifact_type,
        schema_version=artifact.schema_version,
        sha256=artifact.sha256,
        payload=artifact.payload,
        attempt_id=artifact.attempt_id,
        supersedes_artifact_id=artifact.supersedes_artifact_id,
    )


def _load_audit_only_source_roots(
    connection,
    *,
    job,
    profile,
    run_id: str,
    attempt_id: str,
) -> dict[str, RootArtifact]:
    resolver_step, resolver_artifacts = _load_rooted_step(
        connection,
        run_id=run_id,
        attempt_id=attempt_id,
        step_key="deterministic_run",
        step_version="deterministic-run.v1",
    )
    scenario = _strict_json_object(job["scenario_json"], "stored scenario")
    scenario_hash = stable_hash(scenario)
    if (
        resolver_step["input"].get("run_id") != run_id
        or resolver_step["input"].get("engine_mode") != job["engine_mode"]
        or resolver_step["input"].get("scenario_hash") != scenario_hash
        or resolver_step["input"].get("rule_pack_id") != job["rule_pack_id"]
        or resolver_step["input"].get("rule_pack_hash") != job["rule_pack_hash"]
    ):
        raise ModeExecutionAdapterError("resolver-step input identity drift")
    validate_resolver_step_root(
        resolver_step["output"],
        run_id=run_id,
        attempt=attempt_id,
        engine_mode=job["engine_mode"],
        effective_seed=profile.effective_seed,
        agent_pack_resolver_version=profile.agent_pack_resolver_version,
        constraint_context_resolver_version=(
            profile.constraint_context_resolver_version
        ),
        scenario_hash=scenario_hash,
        rule_pack_hash=job["rule_pack_hash"],
        artifacts=resolver_artifacts,
    )
    proof_step, proof_artifacts = _load_rooted_step(
        connection,
        run_id=run_id,
        attempt_id=attempt_id,
        step_key="consistency_audit",
        step_version="consistency-audit-step.v1",
    )
    proof_refs = proof_step["output"].get("artifact_refs")
    if not isinstance(proof_refs, list):
        raise ModeExecutionAdapterError("proof-step output refs must be an array")
    proof_ids = tuple(
        item[1]
        for item in proof_refs
        if isinstance(item, list) and len(item) == 6
    )
    if len(proof_ids) != len(proof_refs):
        raise ModeExecutionAdapterError("proof-step output refs are malformed")
    proof_by_id = {item.artifact_id: item for item in proof_artifacts}
    if set(proof_ids) != set(proof_by_id):
        raise ModeExecutionAdapterError("proof-step output/root membership mismatch")
    ordered_proof_artifacts = tuple(proof_by_id[item] for item in proof_ids)
    validate_mode_proof_step_root(
        proof_step["output"],
        run_id=run_id,
        attempt=attempt_id,
        engine_mode=job["engine_mode"],
        artifacts=ordered_proof_artifacts,
    )
    consistency_input = proof_step["input"]
    if (
        consistency_input.get("run_id") != run_id
        or consistency_input.get("engine_mode") != job["engine_mode"]
        or consistency_input.get("scenario_hash") != scenario_hash
        or consistency_input.get("rule_pack_id") != job["rule_pack_id"]
        or consistency_input.get("rule_pack_hash") != job["rule_pack_hash"]
        or consistency_input.get("previous_step_id") != resolver_step["step_id"]
        or consistency_input.get("previous_output_hash")
        != resolver_step["output_hash"]
        or consistency_input.get("previous_artifact_refs")
        != resolver_step["artifact_refs"]
    ):
        raise ModeExecutionAdapterError(
            "proof-step input does not extend the resolver checkpoint root"
        )
    combined = (*resolver_artifacts, *ordered_proof_artifacts)
    by_type = {item.artifact_type: item for item in combined}
    if len(by_type) != len(combined):
        raise ModeExecutionAdapterError(
            "audit-only source roots contain duplicate Artifact types"
        )
    return by_type


def _load_rooted_step(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    step_key: str,
    step_version: str,
) -> tuple[dict[str, Any], tuple[RootArtifact, ...]]:
    rows = connection.execute(
        """
        SELECT step_id, input_json, input_hash, output_json, output_hash,
               artifact_refs, status
        FROM run_steps
        WHERE run_id = ? AND attempt_id = ? AND step_key = ?
          AND step_version = ? AND status = 'completed'
        """,
        (run_id, attempt_id, step_key, step_version),
    ).fetchall()
    if len(rows) != 1:
        raise ModeExecutionAdapterError(
            f"expected one completed rooted {step_key} step, found {len(rows)}"
        )
    row = rows[0]
    step_input = _strict_json_object(row["input_json"], f"{step_key} input")
    step_output = _strict_json_object(row["output_json"], f"{step_key} output")
    artifact_refs = _strict_json_array(
        row["artifact_refs"],
        f"{step_key} Artifact refs",
    )
    if (
        stable_hash(step_input) != row["input_hash"]
        or stable_hash(step_output) != row["output_hash"]
        or any(not isinstance(item, str) for item in artifact_refs)
        or artifact_refs
        != sorted(set(artifact_refs), key=lambda value: value.encode("utf-8"))
    ):
        raise ModeExecutionAdapterError(f"{step_key} completed root hash mismatch")
    artifact_rows = connection.execute(
        """
        SELECT artifact_id, artifact_type, schema_version, content_json,
               sha256, attempt_id, supersedes_artifact_id
        FROM run_artifacts
        WHERE run_id = ? AND attempt_id = ? AND step_id = ?
        ORDER BY artifact_id ASC
        """,
        (run_id, attempt_id, row["step_id"]),
    ).fetchall()
    if tuple(item["artifact_id"] for item in artifact_rows) != tuple(artifact_refs):
        raise ModeExecutionAdapterError(
            f"{step_key} stored Artifact refs do not match its rows"
        )
    artifacts: list[RootArtifact] = []
    for artifact in artifact_rows:
        raw = artifact["content_json"]
        if not isinstance(raw, str) or artifact_digest(raw) != artifact["sha256"]:
            raise ModeExecutionAdapterError(
                f"{step_key} source Artifact outer SHA mismatch"
            )
        artifacts.append(
            RootArtifact(
                artifact_id=artifact["artifact_id"],
                artifact_type=artifact["artifact_type"],
                schema_version=artifact["schema_version"],
                sha256=artifact["sha256"],
                attempt_id=artifact["attempt_id"],
                supersedes_artifact_id=artifact["supersedes_artifact_id"],
                payload=_strict_json_object(raw, f"{step_key} source Artifact"),
            )
        )
    return (
        {
            "step_id": row["step_id"],
            "input": step_input,
            "output": step_output,
            "output_hash": row["output_hash"],
            "artifact_refs": artifact_refs,
        },
        tuple(artifacts),
    )


def _load_exact_bound_artifact(
    connection,
    **coordinates: Any,
) -> _BoundArtifact:
    bound = _load_bound_artifacts(connection, **coordinates)
    if len(bound) != 1:
        raise ModeExecutionAdapterError(
            f"expected one bound {coordinates['artifact_type']} Artifact, found {len(bound)}"
        )
    return bound[0]


def _load_optional_bound_artifact(
    connection,
    **coordinates: Any,
) -> _BoundArtifact | None:
    bound = _load_bound_artifacts(connection, **coordinates)
    if len(bound) > 1:
        raise ModeExecutionAdapterError(
            f"expected at most one bound {coordinates['artifact_type']} Artifact, found {len(bound)}"
        )
    return bound[0] if bound else None


def _load_bound_artifacts(
    connection,
    *,
    run_id: str,
    attempt_id: str,
    artifact_type: str,
    schema_version: str,
    producing_step_key: str,
    producing_step_version: str,
) -> tuple[_BoundArtifact, ...]:
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
            or any(not isinstance(item, str) for item in artifact_refs)
        ):
            raise ModeExecutionAdapterError("producing step hash root mismatch")
        if step_output.get("schema_version") == "mode-proof-step-output.v1":
            root = RootArtifact(
                artifact_id=row["artifact_id"],
                artifact_type=row["artifact_type"],
                schema_version=row["schema_version"],
                sha256=row["sha256"],
                attempt_id=row["artifact_attempt_id"],
                supersedes_artifact_id=row["supersedes_artifact_id"],
                payload=payload,
            )
            if artifact_refs != [row["artifact_id"]]:
                raise ModeExecutionAdapterError(
                    "single-source proof root has unexpected Artifact membership"
                )
            step_engine_mode = step_input.get("engine_mode")
            if not isinstance(step_engine_mode, str):
                raise ModeExecutionAdapterError(
                    "proof-root producing step is missing engine_mode"
                )
            validate_mode_proof_step_root(
                step_output,
                run_id=run_id,
                attempt=attempt_id,
                engine_mode=step_engine_mode,
                artifacts=(root,),
            )
            bound.append(_bound_from_root(root))
            continue
        if (
            not isinstance(output_refs, list)
            or any(not isinstance(item, str) for item in output_refs)
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
                    attempt_id=row["artifact_attempt_id"],
                    supersedes_artifact_id=row["supersedes_artifact_id"],
                )
            )
    return tuple(bound)


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
