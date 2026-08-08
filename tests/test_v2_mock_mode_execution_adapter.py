from __future__ import annotations

import pytest

from app.core.models import ResearchProjectCreate, RunJobCreateRequest, WarRoomScenarioRequest
from app.db import postgres as postgres_db
from app.db.postgres import PostgresSessionIdentity
from app.services import operations, project_store
from app.services.auth import ensure_system_user
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.negotiation import (
    build_audit_only_projection_source,
    build_consistency_audit_source,
    build_kernel_proposal_batch_source,
)
from app.services.project_app.service import create_project
from app.services.project_store import connect, dumps, loads
from app.services.run_lifecycle import repository, steps, worker_trust
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.run_lifecycle.mode_context import (
    build_resolved_mock_agent_batch,
    resolve_mode_context,
)
from app.services.run_lifecycle.mode_execution_adapter import (
    ModeExecutionAdapterError,
    StoredModeExecutionAdapter,
)
from app.services.run_lifecycle.executor import process_job
from app.services.simulation_runtime import simulation_runtime_service


def _artifact_binding(summary) -> dict:
    return {
        "artifact_id": summary.artifact_id,
        "artifact_type": summary.artifact_type,
        "schema_version": summary.schema_version,
        "sha256": summary.sha256,
        "attempt_id": summary.attempt_id,
        "step_id": summary.step_id,
        "artifact_version": summary.artifact_version,
        "supersedes_artifact_id": summary.supersedes_artifact_id,
    }


def _complete_step(step, summaries) -> None:
    refs = [item.artifact_id for item in summaries]
    steps.complete_step(
        step.step_id,
        {
            "phase": step.step_key,
            "artifact_refs": refs,
            "artifact_bindings": [
                _artifact_binding(item)
                for item in sorted(
                    summaries,
                    key=lambda value: value.artifact_id.encode("utf-8"),
                )
            ],
        },
        refs,
    )


def _rewrite_bound_artifact(artifact_id: str, payload: dict) -> None:
    with connect() as connection:
        row = connection.execute(
            "SELECT run_id, step_id FROM run_artifacts WHERE artifact_id = ?",
            (artifact_id,),
        ).fetchone()
        raw = dumps(payload)
        digest = artifact_digest(raw)
        connection.execute(
            "UPDATE run_artifacts SET content_json = ?, sha256 = ? WHERE artifact_id = ?",
            (raw, digest, artifact_id),
        )
        step_row = connection.execute(
            "SELECT output_json FROM run_steps WHERE step_id = ?",
            (row["step_id"],),
        ).fetchone()
        output = loads(step_row["output_json"], {})
        for binding in output["artifact_bindings"]:
            if binding["artifact_id"] == artifact_id:
                binding["sha256"] = digest
        connection.execute(
            "UPDATE run_steps SET output_json = ?, output_hash = ? WHERE step_id = ?",
            (dumps(output), stable_hash(output), row["step_id"]),
        )
        next_rows = connection.execute(
            "SELECT step_id, input_json FROM run_steps WHERE run_id = ?",
            (row["run_id"],),
        ).fetchall()
        for next_row in next_rows:
            next_input = loads(next_row["input_json"], {})
            if next_input.get("previous_step_id") != row["step_id"]:
                continue
            next_input["previous_output_hash"] = stable_hash(output)
            connection.execute(
                "UPDATE run_steps SET input_json = ?, input_hash = ? WHERE step_id = ?",
                (
                    dumps(next_input),
                    stable_hash(next_input),
                    next_row["step_id"],
                ),
            )


def _setup_mock_sources(monkeypatch, tmp_path, *, prebuild_sources: bool = True):
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-mock-mode-adapter.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    ensure_system_user()
    project = create_project(
        ResearchProjectCreate(
            title="V2 mock mode adapter",
            question="Can provider-free mock proof cross the Kernel gate?",
            mode="war_room",
        )
    )
    capability = build_worker_execution_capability(
        worker_id="worker-v2-mock-adapter",
        worker_generation=5,
        execution_contract_versions=(KERNEL_MODE_EXECUTION_V2,),
    )
    principal = expected_postgres_worker_principal(
        worker_id=capability.worker_id,
        worker_generation=capability.worker_generation,
    )
    identity = PostgresSessionIdentity(
        session_user=principal,
        current_user=principal,
        can_login=True,
        is_superuser=False,
        can_create_role=False,
        can_create_database=False,
        can_replicate=False,
        can_bypass_rls=False,
    )
    monkeypatch.setattr(postgres_db, "is_postgres_url", lambda _value=None: True)
    monkeypatch.setattr(
        postgres_db,
        "postgres_session_identity",
        lambda _connection: identity,
    )
    operations.register_worker(
        capability.worker_id,
        "lifecycle",
        execution_capability=capability,
    )
    monkeypatch.setenv(worker_trust.V2_CREATION_ENABLED_ENV, "1")
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "5")
    created = repository.create_job(
        project.project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            seed=41,
            scenario=WarRoomScenarioRequest(seed=41),
        ),
    )
    with connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET engine_mode = 'mock_agent' WHERE run_id = ?",
            (created.run_id,),
        )
    job = repository.claim_next_job(worker_id=capability.worker_id)
    assert job is not None
    assert job.current_attempt_id is not None
    if not prebuild_sources:
        return job, capability

    result = simulation_runtime_service.run_war_room(
        WarRoomScenarioRequest.model_validate(job.scenario)
    )
    resolved = resolve_mode_context(result, effective_seed=41)
    batch = build_resolved_mock_agent_batch(
        result,
        run_id=job.run_id,
        effective_seed=41,
        context=resolved,
    )
    pb = build_kernel_proposal_batch_source(
        run_id=job.run_id,
        proposals=tuple(batch.proposals),
        source_kind="mock_batch",
        mock_batch=batch,
    )

    repository.mark_phase(
        job.run_id,
        "deterministic_run",
        56,
        "ENGINE",
        "Mock deterministic source",
        "Test mock deterministic source.",
    )
    deterministic_step = steps.begin_step(
        job.run_id,
        "deterministic_run",
        job.current_attempt_id,
        {"run_id": job.run_id, "phase": "deterministic_run"},
        runtime_profile=job.runtime_profile,
    )
    baseline_artifact = repository.add_artifact(
        job.run_id,
        "war_room_result",
        "war-room-result.v1",
        result.model_dump(mode="json"),
    )
    agent_pack_artifact = repository.add_artifact(
        job.run_id,
        "agent_pack",
        "agent-pack-resolver-output.v1",
        resolved.agent_pack.model_dump(mode="json"),
    )
    context_artifact = repository.add_artifact(
        job.run_id,
        "agent_constraint_context",
        "constraint-context-resolver-output.v1",
        resolved.constraint_context.model_dump(mode="json"),
    )
    pb_artifact = repository.add_artifact(
        job.run_id,
        "agent_action_proposals",
        pb.schema_version,
        pb.model_dump(mode="json"),
    )
    _complete_step(
        deterministic_step,
        [baseline_artifact, agent_pack_artifact, context_artifact, pb_artifact],
    )

    report = evaluate_war_room_result(
        result,
        run_id=job.run_id,
        created_at="2026-08-08T00:00:00.000",
        proposals=batch.proposals,
        constraint_context=resolved.runtime_constraint_context,
    )
    fc = build_consistency_audit_source(
        report,
        run_id=job.run_id,
        role="final",
        tick=None,
        evaluator_version=job.runtime_profile["evaluator_version"],
        agent_pack_id=resolved.agent_pack.agent_pack_id,
        agent_pack_hash=resolved.agent_pack_hash,
        constraint_context_hash=resolved.constraint_context_hash,
        complete_proposals=tuple(batch.proposals),
    )
    pa = build_audit_only_projection_source(
        run_id=job.run_id,
        consistency_audit_hash=fc.audit_hash,
        final_result_hash=stable_hash(result.model_dump(mode="json")),
        proposals=tuple(batch.proposals),
        decisions=tuple(report.proposal_decisions),
    )
    repository.mark_phase(
        job.run_id,
        "consistency_audit",
        74,
        "CONSISTENCY",
        "Mock consistency source",
        "Test mock consistency source.",
    )
    consistency_step = steps.begin_step(
        job.run_id,
        "consistency_audit",
        job.current_attempt_id,
        {"run_id": job.run_id, "phase": "consistency_audit"},
        runtime_profile=job.runtime_profile,
    )
    fc_artifact = repository.add_artifact(
        job.run_id,
        "consistency_audit",
        fc.schema_version,
        fc.model_dump(mode="json"),
    )
    pa_artifact = repository.add_artifact(
        job.run_id,
        "agent_action_projection_audit",
        pa.schema_version,
        pa.model_dump(mode="json"),
    )
    _complete_step(consistency_step, [fc_artifact, pa_artifact])
    operations.heartbeat_worker(
        capability.worker_id,
        status="busy",
        current_job_id=job.run_id,
    )
    epoch = repository.capture_v2_fencing_epoch(job.run_id)
    return job, epoch, resolved, agent_pack_artifact


def test_mock_adapter_reconstructs_provider_free_authority(monkeypatch, tmp_path) -> None:
    job, epoch, resolved, _ = _setup_mock_sources(monkeypatch, tmp_path)

    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )

    assert reconstruction.request.engine_mode == "mock_agent"
    assert reconstruction.request.kernel_mode == "deterministic"
    assert reconstruction.request.agent_pack_id == resolved.agent_pack.agent_pack_id
    assert reconstruction.request.agent_pack_hash == resolved.agent_pack_hash
    assert reconstruction.request.constraint_context_hash == resolved.constraint_context_hash
    assert tuple(item.token for item in reconstruction.request.proof.references) == (
        "PB",
        "FC",
        "PA",
    )
    assert reconstruction.request.baseline_projection == reconstruction.request.final_projection
    assert reconstruction.record.authority_path == "mock_action_adapter_deterministic"


def test_mock_production_path_reaches_atomic_v2_terminal_state(
    monkeypatch,
    tmp_path,
) -> None:
    job, _ = _setup_mock_sources(
        monkeypatch,
        tmp_path,
        prebuild_sources=False,
    )

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    assert completed.result_run_id
    schemas = {
        (item.artifact_type, item.schema_version)
        for item in repository.get_artifacts(job.run_id)
    }
    assert {
        ("agent_pack", "agent-pack-resolver-output.v1"),
        ("agent_constraint_context", "constraint-context-resolver-output.v1"),
        ("agent_action_proposals", "kernel-proposal-batch.v1"),
        ("consistency_audit", "consistency-audit.v3"),
        (
            "agent_action_projection_audit",
            "agent-action-projection-audit.v2",
        ),
        ("report_projection_manifest", "report-projection-manifest.v2"),
    }.issubset(schemas)
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    assert manifest["execution_record"]["engine_mode"] == "mock_agent"
    assert manifest["execution_record"]["authority_path"] == (
        "mock_action_adapter_deterministic"
    )


def test_mock_resume_reuses_verified_sources_without_duplicate_emission(
    monkeypatch,
    tmp_path,
) -> None:
    job, _ = _setup_mock_sources(
        monkeypatch,
        tmp_path,
        prebuild_sources=False,
    )
    failed_once = {"value": False}

    def fail_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("fault before mock report")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        fail_before_report,
    )
    with pytest.raises(RuntimeError, match="fault before mock report"):
        process_job(job.run_id)

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    artifacts = repository.get_artifacts(job.run_id)
    for artifact_type in (
        "agent_pack",
        "agent_constraint_context",
        "agent_action_proposals",
        "consistency_audit",
        "agent_action_projection_audit",
        "report_projection_manifest",
    ):
        assert sum(item.artifact_type == artifact_type for item in artifacts) == 1, artifact_type


def test_mock_adapter_rejects_rehashed_resolver_substitution(monkeypatch, tmp_path) -> None:
    job, epoch, _, agent_pack_artifact = _setup_mock_sources(monkeypatch, tmp_path)
    with connect() as connection:
        row = connection.execute(
            "SELECT content_json FROM run_artifacts WHERE artifact_id = ?",
            (agent_pack_artifact.artifact_id,),
        ).fetchone()
        payload = loads(row["content_json"], {})
    payload["status"] = "retired"
    _rewrite_bound_artifact(agent_pack_artifact.artifact_id, payload)

    with pytest.raises((ModeExecutionAdapterError, ValueError), match="resolver|status"):
        StoredModeExecutionAdapter().reconstruct(
            job.run_id,
            fencing_epoch=epoch,
        )


def test_mock_pb_substitution_fails_before_report_or_research_writes(
    monkeypatch,
    tmp_path,
) -> None:
    job, _ = _setup_mock_sources(
        monkeypatch,
        tmp_path,
        prebuild_sources=False,
    )
    failed_once = {"value": False}

    def fail_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("fault before PB substitution")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        fail_before_report,
    )
    with pytest.raises(RuntimeError, match="fault before PB substitution"):
        process_job(job.run_id)

    pb_summary = repository.get_latest_artifact_summary(
        job.run_id,
        "agent_action_proposals",
    )
    pb_payload = repository.get_latest_artifact_content(
        job.run_id,
        "agent_action_proposals",
    )
    assert pb_summary is not None
    assert pb_payload is not None
    pb_payload["proposals"][0]["justification"] += " substituted"
    pb_payload["proposal_hashes"][0] = stable_hash(pb_payload["proposals"][0])
    pb_core = {
        key: value for key, value in pb_payload.items() if key != "batch_hash"
    }
    pb_payload["batch_hash"] = stable_hash(pb_core)
    _rewrite_bound_artifact(pb_summary.artifact_id, pb_payload)

    with pytest.raises(ModeExecutionAdapterError, match="PB differs"):
        process_job(job.run_id)

    assert (
        repository.get_latest_artifact_content(
            job.run_id,
            "report_projection_manifest",
        )
        is None
    )
    assert repository.get_projected_result_run_id(job.run_id) is None
    assert repository.get_job(job.run_id).status == "running"
