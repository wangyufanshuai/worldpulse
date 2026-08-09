from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.models import ResearchProjectCreate, RunJobCreateRequest, WarRoomScenarioRequest
from app.db import postgres as postgres_db
from app.db.postgres import PostgresSessionIdentity
from app.services import operations, project_store
from app.services.auth import ensure_system_user
from app.services.consistency import evaluate_war_room_result
from app.services.consistency.hashing import stable_hash
from app.services.negotiation import build_consistency_audit_source
from app.services.project_app.service import create_project
from app.services.run_lifecycle import repository, steps, worker_trust
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.run_lifecycle import finalization_uow
from app.services.run_lifecycle.finalization_uow import (
    FinalizationFenceError,
    commit_report_generate_v2,
    commit_replay_archive_v2,
)
from app.services.run_lifecycle.mode_execution_adapter import (
    ModeExecutionAdapterError,
    StoredModeExecutionAdapter,
)
from app.services.run_lifecycle.executor import process_job
from app.services.simulation_runtime import simulation_runtime_service
from app.services.project_app.service import (
    war_room_replay_pack,
    war_room_workspace,
)


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-mode-execution-adapter.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    ensure_system_user()
    project = create_project(
        ResearchProjectCreate(
            title="V2 stored mode adapter",
            question="Can stored deterministic proof cross the Kernel gate?",
            mode="war_room",
        )
    )
    capability = build_worker_execution_capability(
        worker_id="worker-v2-mode-adapter",
        worker_generation=4,
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
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "4")
    repository.create_job(
        project.project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            seed=31,
            scenario=WarRoomScenarioRequest(seed=31),
        ),
    )
    claimed = repository.claim_next_job(worker_id=capability.worker_id)
    assert claimed is not None
    return claimed, capability


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


def _complete_v2_step(step, summaries) -> None:
    ordered = sorted(summaries, key=lambda item: item.artifact_id.encode("utf-8"))
    refs = [item.artifact_id for item in summaries]
    steps.complete_step(
        step.step_id,
        {
            "phase": step.step_key,
            "artifact_refs": refs,
            "artifact_bindings": [_artifact_binding(item) for item in ordered],
        },
        refs,
    )


def _prepare_deterministic_sources(monkeypatch, tmp_path):
    job, capability = _setup(monkeypatch, tmp_path)
    assert job.current_attempt_id is not None
    scenario = WarRoomScenarioRequest.model_validate(job.scenario)
    result = simulation_runtime_service.run_war_room(scenario)

    repository.mark_phase(
        job.run_id,
        "deterministic_run",
        56,
        "ENGINE",
        "Deterministic source",
        "Test deterministic source.",
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
    _complete_v2_step(deterministic_step, [baseline_artifact])

    report = evaluate_war_room_result(
        result,
        run_id=job.run_id,
        created_at="2026-08-08T00:00:00.000",
    )
    source = build_consistency_audit_source(
        report,
        run_id=job.run_id,
        role="final",
        tick=None,
        evaluator_version=job.runtime_profile["evaluator_version"],
        agent_pack_id=None,
        agent_pack_hash=None,
        constraint_context_hash=None,
    )
    repository.mark_phase(
        job.run_id,
        "consistency_audit",
        74,
        "CONSISTENCY",
        "Consistency source",
        "Test consistency source.",
    )
    consistency_step = steps.begin_step(
        job.run_id,
        "consistency_audit",
        job.current_attempt_id,
        {"run_id": job.run_id, "phase": "consistency_audit"},
        runtime_profile=job.runtime_profile,
    )
    consistency_artifact = repository.add_artifact(
        job.run_id,
        "consistency_audit",
        source.schema_version,
        source.model_dump(mode="json"),
    )
    _complete_v2_step(consistency_step, [consistency_artifact])

    repository.mark_phase(
        job.run_id,
        "report_generate",
        88,
        "SNAPSHOT",
        "Report reconstruction",
        "Test report reconstruction boundary.",
    )
    operations.heartbeat_worker(
        capability.worker_id,
        status="busy",
        current_job_id=job.run_id,
    )
    epoch = repository.capture_v2_fencing_epoch(job.run_id)
    report_step = steps.begin_step(
        job.run_id,
        "report_generate",
        job.current_attempt_id,
        {
            "run_id": job.run_id,
            "phase": "report_generate",
            "fencing_epoch": epoch.model_dump(mode="json"),
        },
        runtime_profile=job.runtime_profile,
    )
    return job, epoch, baseline_artifact, consistency_artifact, report_step


def _commit_report_and_begin_replay(monkeypatch, tmp_path):
    job, epoch, baseline, consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )
    report = commit_report_generate_v2(
        job.run_id,
        step_id=report_step.step_id,
        reconstruction=reconstruction,
    )
    repository.mark_phase(
        job.run_id,
        "replay_archive",
        100,
        "SNAPSHOT",
        "Replay finalization",
        "Test replay finalization boundary.",
    )
    repository.heartbeat_job(job.run_id, epoch.worker_id)
    operations.heartbeat_worker(
        epoch.worker_id,
        status="busy",
        current_job_id=job.run_id,
    )
    replay_epoch = repository.capture_v2_fencing_epoch(job.run_id)
    assert replay_epoch == epoch
    replay_step = steps.begin_step(
        job.run_id,
        "replay_archive",
        job.current_attempt_id,
        {
            "run_id": job.run_id,
            "phase": "replay_archive",
            "fencing_epoch": replay_epoch.model_dump(mode="json"),
        },
        runtime_profile=job.runtime_profile,
    )
    return job, replay_epoch, baseline, consistency, report, replay_step


def test_deterministic_stored_proof_reconstructs_authoritative_record(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, _report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )

    reconstructed = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )

    assert reconstructed.request.lifecycle_job_id == job.run_id
    assert reconstructed.request.attempt == job.current_attempt_id
    assert reconstructed.request.fencing_epoch_hash == epoch.fencing_epoch_hash
    assert reconstructed.request.proof.references[0].token == "FC"
    assert reconstructed.record.request_hash == reconstructed.request.request_hash
    assert reconstructed.record.baseline_source_run_hash == stable_hash(
        repository.get_latest_artifact_content(
            job.run_id,
            "war_room_result",
        )
    )
    assert StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
        caller_record=reconstructed.record,
    ) == reconstructed


def test_deterministic_v2_lifecycle_completes_end_to_end(monkeypatch, tmp_path):
    job, _capability = _setup(monkeypatch, tmp_path)

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    assert completed.result_run_id is not None
    versions = {
        item.step_key: item.step_version for item in steps.get_steps(job.run_id)
    }
    assert versions["report_generate"] == "report-generate.v2"
    assert versions["replay_archive"] == "replay-archive.v2"
    consistency_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit"
    )
    assert consistency_step.output["schema_version"] == "mode-proof-step-output.v1"
    assert [item[4] for item in consistency_step.output["artifact_refs"]] == [
        "kp.final-consistency.v1"
    ]
    artifacts = repository.get_artifacts(job.run_id)
    assert any(
        item.artifact_type == "report_projection_manifest"
        and item.schema_version == "report-projection-manifest.v2"
        for item in artifacts
    )
    assert any(
        item.artifact_type == "projection"
        and item.schema_version == "research-run-projection.v1"
        for item in artifacts
    )
    workspace = war_room_workspace(job.project_id, completed.result_run_id)
    replay = war_room_replay_pack(job.project_id, completed.result_run_id)
    assert workspace.run_id == completed.result_run_id
    assert replay.run_id == completed.result_run_id


def test_caller_record_is_comparison_only(monkeypatch, tmp_path):
    job, epoch, _baseline, _consistency, _report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    record = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    ).record
    drifted = record.model_dump(mode="json")
    drifted["organization_id"] = "organization-other"
    drifted["record_hash"] = stable_hash(
        {key: value for key, value in drifted.items() if key != "record_hash"}
    )

    with pytest.raises(ModeExecutionAdapterError, match="does not match"):
        StoredModeExecutionAdapter().reconstruct(
            job.run_id,
            fencing_epoch=epoch,
            caller_record=drifted,
        )


def test_updated_artifact_row_sha_cannot_escape_producing_step_binding(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, consistency, _report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    payload = repository.get_artifact_content_by_id(job.run_id, consistency.artifact_id)
    payload["role"] = "projection"
    body = project_store.dumps(payload)
    with project_store.connect() as connection:
        connection.execute(
            "UPDATE run_artifacts SET content_json = ?, sha256 = ? WHERE artifact_id = ?",
            (body, artifact_digest(body), consistency.artifact_id),
        )

    with pytest.raises(ModeExecutionAdapterError, match="binding does not match"):
        StoredModeExecutionAdapter().reconstruct(
            job.run_id,
            fencing_epoch=epoch,
        )


def test_missing_v2_artifact_binding_fails_even_with_rehashed_step_output(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, consistency, _report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    with project_store.connect() as connection:
        row = connection.execute(
            "SELECT step_id, output_json FROM run_steps WHERE step_id = ?",
            (consistency.step_id,),
        ).fetchone()
        output = project_store.loads(row["output_json"], {})
        output.pop("artifact_bindings")
        connection.execute(
            "UPDATE run_steps SET output_json = ?, output_hash = ? WHERE step_id = ?",
            (project_store.dumps(output), stable_hash(output), row["step_id"]),
        )

    with pytest.raises(ModeExecutionAdapterError, match="missing complete"):
        StoredModeExecutionAdapter().reconstruct(
            job.run_id,
            fencing_epoch=epoch,
        )


def test_report_generate_v2_commits_manifest_and_step_atomically(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )

    committed = commit_report_generate_v2(
        job.run_id,
        step_id=report_step.step_id,
        reconstruction=reconstruction,
    )

    assert committed.recovered is False
    assert committed.manifest.execution_record == reconstruction.record
    stored_step = steps.get_step(report_step.step_id)
    assert stored_step.status == "completed"
    assert stored_step.artifact_refs == [committed.artifact_id]
    assert stored_step.output["execution_record_hash"] == reconstruction.record.record_hash
    assert repository.get_job(job.run_id).status == "running"
    with project_store.connect() as connection:
        attempt = connection.execute(
            "SELECT status FROM run_attempts WHERE attempt_id = ?",
            (job.current_attempt_id,),
        ).fetchone()
        projection_count = connection.execute(
            "SELECT COUNT(*) AS count FROM research_runs",
        ).fetchone()
    assert attempt["status"] == "running"
    assert int(projection_count["count"]) == 0

    recovered = commit_report_generate_v2(
        job.run_id,
        step_id=report_step.step_id,
        reconstruction=reconstruction,
    )
    assert recovered.recovered is True
    assert recovered.artifact_id == committed.artifact_id


def test_report_transaction_fault_rolls_back_manifest_cas_and_step(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )
    monkeypatch.setattr(
        finalization_uow,
        "finalization_fault_hook",
        lambda _moment: (_ for _ in ()).throw(RuntimeError("fault after manifest")),
    )

    with pytest.raises(RuntimeError, match="fault after manifest"):
        commit_report_generate_v2(
            job.run_id,
            step_id=report_step.step_id,
            reconstruction=reconstruction,
        )

    assert steps.get_step(report_step.step_id).status == "running"
    with project_store.connect() as connection:
        manifests = connection.execute(
            """
            SELECT COUNT(*) AS count FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'report_projection_manifest'
            """,
            (job.run_id,),
        ).fetchone()
    assert int(manifests["count"]) == 0


def test_concurrent_same_attempt_report_commit_is_one_write_plus_recovery(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda _index: commit_report_generate_v2(
                    job.run_id,
                    step_id=report_step.step_id,
                    reconstruction=reconstruction,
                ),
                range(2),
            )
        )

    assert {item.recovered for item in results} == {False, True}
    assert len({item.artifact_id for item in results}) == 1
    with project_store.connect() as connection:
        manifests = connection.execute(
            """
            SELECT COUNT(*) AS count FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'report_projection_manifest'
            """,
            (job.run_id,),
        ).fetchone()
    assert int(manifests["count"]) == 1


def test_new_attempt_fences_stale_report_with_zero_report_writes(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )
    with project_store.connect() as connection:
        connection.execute(
            """
            INSERT INTO run_attempts
            (attempt_id, run_id, worker_id, attempt_number, status, started_at)
            VALUES ('attempt-new-owner', ?, ?, 2, 'running', ?)
            """,
            (job.run_id, epoch.worker_id, repository.now_iso()),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET current_attempt_id = 'attempt-new-owner', attempt_count = 2
            WHERE run_id = ?
            """,
            (job.run_id,),
        )

    with pytest.raises(FinalizationFenceError, match="epoch|ownership"):
        commit_report_generate_v2(
            job.run_id,
            step_id=report_step.step_id,
            reconstruction=reconstruction,
        )

    assert steps.get_step(report_step.step_id).status == "running"
    with project_store.connect() as connection:
        manifests = connection.execute(
            """
            SELECT COUNT(*) AS count FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'report_projection_manifest'
            """,
            (job.run_id,),
        ).fetchone()
    assert int(manifests["count"]) == 0


def test_completed_report_is_not_recovered_from_a_new_current_attempt(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, report_step = _prepare_deterministic_sources(
        monkeypatch,
        tmp_path,
    )
    reconstruction = StoredModeExecutionAdapter().reconstruct(
        job.run_id,
        fencing_epoch=epoch,
    )
    committed = commit_report_generate_v2(
        job.run_id,
        step_id=report_step.step_id,
        reconstruction=reconstruction,
    )
    with project_store.connect() as connection:
        connection.execute(
            """
            INSERT INTO run_attempts
            (attempt_id, run_id, worker_id, attempt_number, status, started_at)
            VALUES ('attempt-after-report', ?, ?, 2, 'running', ?)
            """,
            (job.run_id, epoch.worker_id, repository.now_iso()),
        )
        connection.execute(
            """
            UPDATE run_jobs
            SET current_attempt_id = 'attempt-after-report', attempt_count = 2
            WHERE run_id = ?
            """,
            (job.run_id,),
        )

    with pytest.raises(FinalizationFenceError, match="epoch changed"):
        commit_report_generate_v2(
            job.run_id,
            step_id=report_step.step_id,
            reconstruction=reconstruction,
        )
    with project_store.connect() as connection:
        manifests = connection.execute(
            """
            SELECT artifact_id FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'report_projection_manifest'
            """,
            (job.run_id,),
        ).fetchall()
    assert [item["artifact_id"] for item in manifests] == [committed.artifact_id]


def test_replay_archive_v2_atomically_projects_and_completes_lifecycle(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, _report, replay_step = (
        _commit_report_and_begin_replay(monkeypatch, tmp_path)
    )

    completed = commit_replay_archive_v2(
        job.run_id,
        step_id=replay_step.step_id,
        fencing_epoch=epoch,
        phase_durations_ms={"report_generate": 3, "replay_archive": 5},
    )

    terminal = repository.get_job(job.run_id)
    assert terminal.status == "completed"
    assert terminal.result_run_id == completed.result_run_id
    assert terminal.worker_id is None
    stored_step = steps.get_step(replay_step.step_id)
    assert stored_step.status == "completed"
    assert set(stored_step.artifact_refs) == {
        completed.projection_artifact_id,
        completed.metrics_artifact_id,
    }
    with project_store.connect() as connection:
        attempt = connection.execute(
            "SELECT status FROM run_attempts WHERE attempt_id = ?",
            (job.current_attempt_id,),
        ).fetchone()
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM research_runs WHERE run_id = ?) AS runs,
              (SELECT COUNT(*) FROM causal_graph_snapshots WHERE run_id = ?) AS graphs,
              (SELECT COUNT(*) FROM ai_reports WHERE run_id = ?) AS reports
            """,
            (completed.result_run_id, completed.result_run_id, completed.result_run_id),
        ).fetchone()
    assert attempt["status"] == "completed"
    assert (int(counts["runs"]), int(counts["graphs"]), int(counts["reports"])) == (
        1,
        1,
        1,
    )
    assert war_room_workspace(job.project_id, completed.result_run_id).run_id == completed.result_run_id
    assert war_room_replay_pack(job.project_id, completed.result_run_id).run_id == completed.result_run_id


def test_replay_fault_rolls_back_research_artifacts_and_terminal_states(
    monkeypatch,
    tmp_path,
):
    job, epoch, _baseline, _consistency, _report, replay_step = (
        _commit_report_and_begin_replay(monkeypatch, tmp_path)
    )

    def fail_after_projection(moment: str) -> None:
        if moment == "after_research_projection":
            raise RuntimeError("fault after research projection")

    monkeypatch.setattr(
        finalization_uow,
        "finalization_fault_hook",
        fail_after_projection,
    )
    with pytest.raises(RuntimeError, match="fault after research projection"):
        commit_replay_archive_v2(
            job.run_id,
            step_id=replay_step.step_id,
            fencing_epoch=epoch,
        )

    assert repository.get_job(job.run_id).status == "running"
    assert steps.get_step(replay_step.step_id).status == "running"
    with project_store.connect() as connection:
        counts = connection.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM research_runs) AS runs,
              (SELECT COUNT(*) FROM run_artifacts
                WHERE run_id = ? AND artifact_type IN ('projection','lifecycle_metrics')) AS artifacts
            """,
            (job.run_id,),
        ).fetchone()
        attempt = connection.execute(
            "SELECT status FROM run_attempts WHERE attempt_id = ?",
            (job.current_attempt_id,),
        ).fetchone()
    assert int(counts["runs"]) == 0
    assert int(counts["artifacts"]) == 0
    assert attempt["status"] == "running"
