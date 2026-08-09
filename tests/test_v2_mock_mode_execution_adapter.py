from __future__ import annotations

import pytest

from app.core.models import (
    ResearchProjectCreate,
    RunJobCreateRequest,
    WarRoomRun,
    WarRoomScenarioRequest,
)
from app.db import postgres as postgres_db
from app.db.postgres import PostgresSessionIdentity
from app.services import operations, project_store
from app.services.agent_contract.models import MockAgentBatch
from app.services.auth import ensure_system_user
from app.services.consistency.hashing import stable_hash
from app.services.project_app.service import create_project
from app.services.project_store import connect, dumps, loads
from app.services.run_lifecycle import repository, steps, worker_trust
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import mode_execution_adapter as mode_adapter_module
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.run_lifecycle.mode_context import resolve_mode_context
from app.services.run_lifecycle.mode_execution_adapter import (
    ModeExecutionAdapterError,
    StoredModeExecutionAdapter,
)
from app.services.run_lifecycle.executor import process_job


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
        for binding in output.get("artifact_bindings", []):
            if binding["artifact_id"] == artifact_id:
                binding["sha256"] = digest
        for reference in output.get("artifact_refs", []):
            if (
                isinstance(reference, list)
                and len(reference) == 6
                and reference[1] == artifact_id
            ):
                reference[2] = digest
                reference[3] = payload.get(
                    "batch_hash",
                    payload.get("audit_hash", reference[3]),
                )
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

    failed_once = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("prepared rooted mock sources")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        stop_before_report,
    )
    with pytest.raises(RuntimeError, match="prepared rooted mock sources"):
        process_job(job.run_id)
    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        lambda _phase, _moment: None,
    )
    job = repository.get_job(job.run_id)
    result_payload = repository.get_latest_artifact_content(
        job.run_id,
        "war_room_result",
    )
    agent_pack_artifact = repository.get_latest_artifact_summary(
        job.run_id,
        "agent_pack",
    )
    assert result_payload is not None
    assert agent_pack_artifact is not None
    resolved = resolve_mode_context(
        WarRoomRun.model_validate(result_payload),
        effective_seed=41,
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
    artifact_summaries = repository.get_artifacts(job.run_id)
    schemas = {
        (item.artifact_type, item.schema_version)
        for item in artifact_summaries
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
    completed_steps = {
        item.step_key: item
        for item in steps.get_steps(job.run_id)
        if item.status == "completed"
    }
    resolver_output = completed_steps["deterministic_run"].output
    assert set(resolver_output) == {
        "schema_version",
        "run_id",
        "attempt",
        "agent_pack_resolver_version",
        "constraint_context_resolver_version",
        "effective_seed",
        "baseline_result_hash",
        "scenario_hash",
        "rule_pack_hash",
        "agent_pack_id",
        "agent_pack_hash",
        "constraint_context_hash",
        "artifact_refs",
    }
    proof_output = completed_steps["consistency_audit"].output
    assert set(proof_output) == {
        "schema_version",
        "run_id",
        "attempt",
        "engine_mode",
        "artifact_refs",
    }
    assert [item[4] for item in proof_output["artifact_refs"]] == [
        "kp.proposal-batch.v1",
        "kp.final-consistency.v1",
        "kp.projection-audit.v1",
    ]
    source_types = {
        "war_room_result",
        "agent_pack",
        "agent_constraint_context",
        "agent_action_proposals",
        "consistency_audit",
        "agent_action_projection_audit",
    }
    assert all(
        item.supersedes_artifact_id is None
        for item in artifact_summaries
        if item.artifact_type in source_types
    )
    pb_summary = next(
        item
        for item in artifact_summaries
        if item.artifact_type == "agent_action_proposals"
    )
    assert pb_summary.step_id == completed_steps["consistency_audit"].step_id


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


def test_zero_proposal_mock_root_forbids_projection_audit(
    monkeypatch,
    tmp_path,
) -> None:
    def empty_batch(
        _result,
        *,
        run_id: str,
        effective_seed: int,
        context,
    ) -> MockAgentBatch:
        del run_id
        return MockAgentBatch(
            seed=effective_seed,
            proposals=[],
            constraint_context=context.runtime_constraint_context,
            batch_hash=stable_hash(
                {
                    "provider": "mock-deterministic",
                    "seed": effective_seed,
                    "proposal_ids": [],
                }
            ),
        )

    monkeypatch.setattr(
        lifecycle_executor,
        "build_resolved_mock_agent_batch",
        empty_batch,
    )
    monkeypatch.setattr(
        mode_adapter_module,
        "build_resolved_mock_agent_batch",
        empty_batch,
    )
    job, _ = _setup_mock_sources(
        monkeypatch,
        tmp_path,
        prebuild_sources=False,
    )

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    proof_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit" and item.status == "completed"
    )
    assert [item[4] for item in proof_step.output["artifact_refs"]] == [
        "kp.proposal-batch.v1",
        "kp.final-consistency.v1",
    ]
    assert repository.get_latest_artifact_content(
        job.run_id,
        "agent_action_projection_audit",
    ) is None


def test_mock_proof_root_order_tamper_fails_closed(monkeypatch, tmp_path) -> None:
    job, epoch, _, _ = _setup_mock_sources(monkeypatch, tmp_path)
    proof_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit" and item.status == "completed"
    )
    output = proof_step.output
    output["artifact_refs"][0], output["artifact_refs"][1] = (
        output["artifact_refs"][1],
        output["artifact_refs"][0],
    )
    with connect() as connection:
        connection.execute(
            "UPDATE run_steps SET output_json = ?, output_hash = ? WHERE step_id = ?",
            (dumps(output), stable_hash(output), proof_step.step_id),
        )

    with pytest.raises(ValueError, match="canonical|schema|root|identity"):
        StoredModeExecutionAdapter().reconstruct(
            job.run_id,
            fencing_epoch=epoch,
        )
    assert repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    ) is None


def test_mock_retry_rebuilds_complete_current_attempt_roots(
    monkeypatch,
    tmp_path,
) -> None:
    job, capability = _setup_mock_sources(
        monkeypatch,
        tmp_path,
        prebuild_sources=False,
    )
    first_attempt = job.current_attempt_id
    failed_once = {"value": False}

    def fail_first_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("first mock attempt failed")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        fail_first_report,
    )
    with pytest.raises(RuntimeError, match="first mock attempt failed") as raised:
        process_job(job.run_id)
    steps.fail_active_step(job.run_id, raised.value)
    retrying = repository.handle_attempt_failure(job.run_id, raised.value)
    assert retrying.status == "queued"
    with connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET next_attempt_at = NULL WHERE run_id = ?",
            (job.run_id,),
        )
    operations.heartbeat_worker(
        capability.worker_id,
        status="ready",
        current_job_id=None,
    )
    claimed = repository.claim_next_job(worker_id=capability.worker_id)
    assert claimed is not None
    assert claimed.current_attempt_id != first_attempt

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    current_attempt = completed.current_attempt_id
    source_types = {
        "war_room_result",
        "agent_pack",
        "agent_constraint_context",
        "agent_action_proposals",
        "consistency_audit",
        "agent_action_projection_audit",
    }
    artifacts = [
        item
        for item in repository.get_artifacts(job.run_id)
        if item.artifact_type in source_types
    ]
    assert {item.attempt_id for item in artifacts} == {
        first_attempt,
        current_attempt,
    }
    assert all(item.supersedes_artifact_id is None for item in artifacts)
    current_steps = [
        item
        for item in steps.get_steps(job.run_id)
        if item.attempt_id == current_attempt and item.status == "completed"
    ]
    assert [item.step_key for item in current_steps] == [
        "scenario_compile",
        "environment_prepare",
        "deterministic_run",
        "consistency_audit",
        "report_generate",
        "replay_archive",
    ]
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    assert manifest["execution_record"]["attempt"] == current_attempt


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

    with pytest.raises(ValueError, match="PB|proposals drift"):
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
