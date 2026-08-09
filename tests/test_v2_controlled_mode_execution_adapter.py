from __future__ import annotations

import pytest

from app.core.models import (
    ResearchProjectCreate,
    RunJobCreateRequest,
    WarRoomScenarioRequest,
)
from app.db import postgres as postgres_db
from app.db.postgres import PostgresSessionIdentity
from app.services import operations, project_store
from app.services.agent_runtime import AgentRuntimeResult
from app.services.auth import ensure_system_user
from app.services.consistency.hashing import stable_hash
from app.services.project_app.service import create_project
from app.services.project_store import connect, dumps, loads
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import repository, steps, worker_trust
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    build_worker_execution_capability,
    expected_postgres_worker_principal,
)
from app.services.run_lifecycle.executor import process_job
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.run_lifecycle.mode_context import resolve_mode_context
from app.services.run_lifecycle.mode_execution_adapter import (
    ModeExecutionAdapterError,
)


_CONTROLLED_PROOF_TYPES = {
    "agent_runtime_audit",
    "agent_action_proposals",
    "consistency_audit",
    "agent_action_projection_audit",
}


def _setup_claimed_controlled(monkeypatch, tmp_path):
    monkeypatch.setattr(
        project_store,
        "DB_PATH",
        tmp_path / "v2-controlled-mode-adapter.db",
    )
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    ensure_system_user()
    project = create_project(
        ResearchProjectCreate(
            title="V2 controlled mode adapter",
            question="Can controlled Agent proof remain provider-free after capture?",
            mode="war_room",
        )
    )
    capability = build_worker_execution_capability(
        worker_id="worker-v2-controlled-adapter",
        worker_generation=6,
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
    monkeypatch.setenv(worker_trust.V2_MINIMUM_WORKER_GENERATION_ENV, "6")
    created = repository.create_job(
        project.project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            seed=43,
            scenario=WarRoomScenarioRequest(seed=43),
        ),
    )
    with connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET engine_mode = 'controlled_agent' WHERE run_id = ?",
            (created.run_id,),
        )
    claimed = repository.claim_next_job(worker_id=capability.worker_id)
    assert claimed is not None
    assert claimed.current_attempt_id is not None
    return claimed, capability


def _fail_first_report_and_claim_retry(monkeypatch, job, capability):
    first_attempt = job.current_attempt_id
    failed_once = {"value": False}

    def fail_first_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("controlled first attempt failed")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        fail_first_report,
    )
    with pytest.raises(RuntimeError, match="controlled first attempt failed") as raised:
        process_job(job.run_id)
    steps.fail_active_step(job.run_id, raised.value)
    repository.handle_attempt_failure(job.run_id, raised.value)
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
    return first_attempt, claimed


def _controlled_proof_types_for_attempt(run_id: str, attempt_id: str) -> set[str]:
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT artifact_type
            FROM run_artifacts
            WHERE run_id = ? AND attempt_id = ?
            """,
            (run_id, attempt_id),
        ).fetchall()
    return {item["artifact_type"] for item in rows} & _CONTROLLED_PROOF_TYPES


def _historical_runtime_row(run_id: str, attempt_id: str):
    with connect() as connection:
        row = connection.execute(
            """
            SELECT artifact_id, step_id, content_json, sha256
            FROM run_artifacts
            WHERE run_id = ? AND attempt_id = ?
              AND artifact_type = 'agent_runtime_audit'
            """,
            (run_id, attempt_id),
        ).fetchone()
    assert row is not None
    return row


def test_controlled_agent_report_resume_is_provider_free(monkeypatch, tmp_path) -> None:
    job, _ = _setup_claimed_controlled(monkeypatch, tmp_path)
    failed_once = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("controlled sources captured")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        stop_before_report,
    )
    with pytest.raises(RuntimeError, match="controlled sources captured"):
        process_job(job.run_id)

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("Provider/runtime may not run after controlled source capture")

    monkeypatch.setattr(
        lifecycle_executor,
        "run_agent_runtime",
        forbidden_runtime,
    )
    completed = process_job(job.run_id)

    assert completed.status == "completed"
    proof_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit" and item.status == "completed"
    )
    assert [item[4] for item in proof_step.output["artifact_refs"]] == [
        "kp.agent-runtime.v1",
        "kp.proposal-batch.v1",
        "kp.final-consistency.v1",
        "kp.projection-audit.v1",
    ]
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    record = manifest["execution_record"]
    assert record["engine_mode"] == "controlled_agent"
    assert record["kernel_mode"] == "deterministic"
    assert record["authority_path"] == "controlled_action_adapter_deterministic"
    assert record["agent_pack_id"]
    assert record["agent_pack_hash"]
    assert record["constraint_context_hash"]


def test_controlled_runtime_uses_resolved_agent_identities(monkeypatch, tmp_path) -> None:
    job, _ = _setup_claimed_controlled(monkeypatch, tmp_path)

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    runtime = repository.get_latest_artifact_content(
        job.run_id,
        "agent_runtime_audit",
    )
    agent_pack = repository.get_latest_artifact_content(job.run_id, "agent_pack")
    assert runtime is not None
    assert agent_pack is not None
    profile_ids = {item["agent_id"] for item in agent_pack["profiles"]}
    assert runtime["proposals"]
    assert {item["actor_id"] for item in runtime["proposals"]}.issubset(profile_ids)
    assert {item["actor_id"] for item in runtime["invocations"]}.issubset(profile_ids)
    assert set(runtime["constraint_context"]["actor_capabilities"]) == profile_ids
    assert set(runtime["constraint_context"]["action_budgets"]) == profile_ids


def test_controlled_empty_runtime_closes_without_projection_audit(
    monkeypatch,
    tmp_path,
) -> None:
    job, _ = _setup_claimed_controlled(monkeypatch, tmp_path)

    def empty_runtime(result, *, run_id, config, **_kwargs):
        resolved = resolve_mode_context(
            result,
            effective_seed=config.seed,
        )
        identity = {
            "provider": "empty-test",
            "model": "empty-test",
            "mode": "skipped",
            "proposal_ids": [],
            "invocations": [],
        }
        return AgentRuntimeResult(
            run_id=run_id,
            provider=identity["provider"],
            model=identity["model"],
            mode=identity["mode"],
            runtime_config={},
            proposals=[],
            constraint_context=resolved.runtime_constraint_context,
            invocations=[],
            runtime_hash=stable_hash(identity),
        )

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", empty_runtime)
    completed = process_job(job.run_id)

    assert completed.status == "completed"
    proof_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit" and item.status == "completed"
    )
    assert [item[4] for item in proof_step.output["artifact_refs"]] == [
        "kp.agent-runtime.v1",
        "kp.proposal-batch.v1",
        "kp.final-consistency.v1",
    ]
    assert repository.get_latest_artifact_content(
        job.run_id,
        "agent_action_projection_audit",
    ) is None


def test_controlled_retry_reemits_authenticated_ar_without_provider(
    monkeypatch,
    tmp_path,
) -> None:
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    first_attempt, claimed = _fail_first_report_and_claim_retry(
        monkeypatch,
        job,
        capability,
    )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("controlled retry may not call Provider/runtime")

    monkeypatch.setattr(
        lifecycle_executor,
        "run_agent_runtime",
        forbidden_runtime,
    )
    completed = process_job(job.run_id)

    assert completed.status == "completed"
    runtime_artifacts = [
        item
        for item in repository.get_artifacts(job.run_id)
        if item.artifact_type == "agent_runtime_audit"
    ]
    assert len(runtime_artifacts) == 2
    first = next(item for item in runtime_artifacts if item.attempt_id == first_attempt)
    current = next(
        item
        for item in runtime_artifacts
        if item.attempt_id == completed.current_attempt_id
    )
    assert current.supersedes_artifact_id == first.artifact_id
    first_payload = repository.get_artifact_content_by_id(
        job.run_id,
        first.artifact_id,
    )
    current_payload = repository.get_artifact_content_by_id(
        job.run_id,
        current.artifact_id,
    )
    assert current_payload == first_payload
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    assert manifest["execution_record"]["attempt"] == completed.current_attempt_id


def test_controlled_retry_rejects_ineligible_history_without_proof_writes(
    monkeypatch,
    tmp_path,
) -> None:
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    first_attempt, claimed = _fail_first_report_and_claim_retry(
        monkeypatch,
        job,
        capability,
    )
    with connect() as connection:
        connection.execute(
            "UPDATE run_attempts SET status = 'completed' WHERE attempt_id = ?",
            (first_attempt,),
        )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("ineligible retry history may not call Provider/runtime")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    with pytest.raises(ModeExecutionAdapterError, match="no eligible failed"):
        process_job(job.run_id)

    assert claimed.current_attempt_id is not None
    assert _controlled_proof_types_for_attempt(
        job.run_id,
        claimed.current_attempt_id,
    ) == set()


def test_controlled_retry_does_not_fall_back_past_newer_failed_attempt(
    monkeypatch,
    tmp_path,
) -> None:
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    _, second = _fail_first_report_and_claim_retry(monkeypatch, job, capability)
    second_attempt = second.current_attempt_id
    assert second_attempt is not None
    repository.handle_attempt_failure(job.run_id, RuntimeError("attempt two failed early"))
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
    third = repository.claim_next_job(worker_id=capability.worker_id)
    assert third is not None
    assert third.current_attempt_id not in {None, second_attempt}

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("controlled retry may not fall back or call Provider/runtime")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    with pytest.raises(ModeExecutionAdapterError, match="completed root|exactly one"):
        process_job(job.run_id)

    assert _controlled_proof_types_for_attempt(
        job.run_id,
        third.current_attempt_id,
    ) == set()


@pytest.mark.parametrize("tamper", ["payload", "sha", "root"])
def test_controlled_retry_rejects_historical_ar_tampering_without_proof_writes(
    monkeypatch,
    tmp_path,
    tamper,
) -> None:
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    first_attempt, claimed = _fail_first_report_and_claim_retry(
        monkeypatch,
        job,
        capability,
    )
    runtime = _historical_runtime_row(job.run_id, first_attempt)
    with connect() as connection:
        if tamper == "payload":
            payload = loads(runtime["content_json"], {})
            payload["provider"] = "tampered-provider"
            raw = dumps(payload)
            digest = artifact_digest(raw)
            connection.execute(
                """
                UPDATE run_artifacts
                SET content_json = ?, sha256 = ?
                WHERE artifact_id = ?
                """,
                (raw, digest, runtime["artifact_id"]),
            )
            step = connection.execute(
                "SELECT output_json FROM run_steps WHERE step_id = ?",
                (runtime["step_id"],),
            ).fetchone()
            output = loads(step["output_json"], {})
            output["artifact_refs"][0][2] = digest
            connection.execute(
                "UPDATE run_steps SET output_json = ?, output_hash = ? WHERE step_id = ?",
                (dumps(output), stable_hash(output), runtime["step_id"]),
            )
        elif tamper == "sha":
            connection.execute(
                "UPDATE run_artifacts SET sha256 = ? WHERE artifact_id = ?",
                ("0" * 64, runtime["artifact_id"]),
            )
        else:
            step = connection.execute(
                "SELECT output_json FROM run_steps WHERE step_id = ?",
                (runtime["step_id"],),
            ).fetchone()
            output = loads(step["output_json"], {})
            output["artifact_refs"][0][3] = "0" * 64
            connection.execute(
                "UPDATE run_steps SET output_json = ?, output_hash = ? WHERE step_id = ?",
                (dumps(output), stable_hash(output), runtime["step_id"]),
            )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("tampered historical AR may not call Provider/runtime")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    with pytest.raises((ModeExecutionAdapterError, ValueError)):
        process_job(job.run_id)

    assert claimed.current_attempt_id is not None
    assert _controlled_proof_types_for_attempt(
        job.run_id,
        claimed.current_attempt_id,
    ) == set()


def test_controlled_retry_rejects_current_ar_supersedes_row_drift(
    monkeypatch,
    tmp_path,
) -> None:
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    _, claimed = _fail_first_report_and_claim_retry(monkeypatch, job, capability)
    stopped = {"value": False}

    def stop_retry_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not stopped["value"]:
            stopped["value"] = True
            raise RuntimeError("retry proof captured")

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        stop_retry_before_report,
    )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("controlled retry must remain Provider-free")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    with pytest.raises(RuntimeError, match="retry proof captured"):
        process_job(job.run_id)

    assert claimed.current_attempt_id is not None
    current_runtime = _historical_runtime_row(
        job.run_id,
        claimed.current_attempt_id,
    )
    with connect() as connection:
        connection.execute(
            """
            UPDATE run_artifacts
            SET supersedes_artifact_id = NULL
            WHERE artifact_id = ?
            """,
            (current_runtime["artifact_id"],),
        )

    with pytest.raises(ModeExecutionAdapterError, match="lineage/payload mismatch"):
        process_job(job.run_id)
    assert repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    ) is None
