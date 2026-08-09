from __future__ import annotations

import pytest

from app.services import project_store
from app.services.agent_runtime import AgentRuntimeResult
from app.services.consistency.hashing import stable_hash
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import repository, steps
from app.services.run_lifecycle.executor import process_job
from app.services.run_lifecycle.mode_execution_adapter import ModeExecutionAdapterError
from app.services.run_lifecycle.mode_context import resolve_mode_context
from app.services.project_store import connect

from test_v2_controlled_mode_execution_adapter import (
    _fail_first_report_and_claim_retry,
    _setup_claimed_controlled,
)


def _setup_claimed_hybrid(monkeypatch, tmp_path, *, engine_mode: str = "hybrid"):
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    with connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET engine_mode = ? WHERE run_id = ?",
            (engine_mode, job.run_id),
        )
    refreshed = repository.get_job(job.run_id)
    assert refreshed.engine_mode == engine_mode
    return refreshed, capability


@pytest.mark.parametrize("engine_mode", ["hybrid", "hybrid_recorded"])
def test_hybrid_v2_builds_complete_current_attempt_proof(
    monkeypatch,
    tmp_path,
    engine_mode,
) -> None:
    job, _ = _setup_claimed_hybrid(
        monkeypatch,
        tmp_path,
        engine_mode=engine_mode,
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
        "kp.action-modifier-bundle.v1",
        "kp.commitment-ledger.v1",
        "kp.projection-audit.v1",
        "kp.hybrid-replay.v1",
    ]
    assert repository.get_latest_artifact_content(
        job.run_id,
        "hybrid_war_room_result",
    ) is None
    replay = repository.get_latest_artifact_content(
        job.run_id,
        "hybrid_replay_record",
    )
    assert replay is not None
    assert replay["schema_version"] == "hybrid-replay-record.v2"
    assert replay["engine_mode"] == engine_mode
    assert replay["provider_calls_required"] == 0
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    assert manifest["execution_record"]["kernel_mode"] == "hybrid"
    assert manifest["execution_record"]["authority_path"] == {
        "hybrid": "hybrid_action_adapter_replay",
        "hybrid_recorded": "hybrid_recorded_action_adapter_replay",
    }[engine_mode]


def test_hybrid_v2_same_attempt_report_resume_is_provider_free(monkeypatch, tmp_path):
    job, _ = _setup_claimed_hybrid(monkeypatch, tmp_path)
    failed_once = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("hybrid sources captured")

    monkeypatch.setattr(lifecycle_executor, "lifecycle_fault_hook", stop_before_report)
    with pytest.raises(RuntimeError, match="hybrid sources captured"):
        process_job(job.run_id)

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("hybrid report resume may not call Provider/runtime")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    completed = process_job(job.run_id)

    assert completed.status == "completed"
    assert project_store.DB_PATH == tmp_path / "v2-controlled-mode-adapter.db"


def test_hybrid_v2_empty_runtime_keeps_mandatory_pa_and_empty_cl(monkeypatch, tmp_path):
    job, _ = _setup_claimed_hybrid(monkeypatch, tmp_path)

    def empty_runtime(result, *, run_id, config, **_kwargs):
        resolved = resolve_mode_context(result, effective_seed=config.seed)
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
        "kp.action-modifier-bundle.v1",
        "kp.commitment-ledger.v1",
        "kp.projection-audit.v1",
        "kp.hybrid-replay.v1",
    ]
    replay = repository.get_latest_artifact_content(
        job.run_id,
        "hybrid_replay_record",
    )
    assert replay is not None
    assert replay["accepted_proposal_ids"] == []
    ledger = repository.get_latest_artifact_content(job.run_id, "commitment_ledger")
    assert ledger is not None
    assert ledger["ledger_entry_count"] == 0


def test_hybrid_v2_tampered_replay_fails_before_report(monkeypatch, tmp_path):
    job, _ = _setup_claimed_hybrid(monkeypatch, tmp_path)
    stopped = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not stopped["value"]:
            stopped["value"] = True
            raise RuntimeError("hybrid replay captured")

    monkeypatch.setattr(lifecycle_executor, "lifecycle_fault_hook", stop_before_report)
    with pytest.raises(RuntimeError, match="hybrid replay captured"):
        process_job(job.run_id)

    with connect() as connection:
        row = connection.execute(
            """
            SELECT artifact_id, content_json
            FROM run_artifacts
            WHERE run_id = ? AND artifact_type = 'hybrid_replay_record'
            """,
            (job.run_id,),
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE run_artifacts SET content_json = ? WHERE artifact_id = ?",
            (row["content_json"].replace("stored_only", "tampered"), row["artifact_id"]),
        )

    with pytest.raises((ModeExecutionAdapterError, ValueError)):
        process_job(job.run_id)
    assert repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    ) is None


@pytest.mark.parametrize("engine_mode", ["hybrid", "hybrid_recorded"])
def test_hybrid_v2_retry_reemits_ar_without_provider(monkeypatch, tmp_path, engine_mode):
    job, capability = _setup_claimed_hybrid(
        monkeypatch,
        tmp_path,
        engine_mode=engine_mode,
    )
    first_attempt, claimed = _fail_first_report_and_claim_retry(
        monkeypatch,
        job,
        capability,
    )

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("hybrid retry may not call Provider/runtime")

    monkeypatch.setattr(lifecycle_executor, "run_agent_runtime", forbidden_runtime)
    completed = process_job(job.run_id)

    assert completed.status == "completed"
    assert claimed.current_attempt_id is not None
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
        if item.attempt_id == claimed.current_attempt_id
    )
    assert current.supersedes_artifact_id == first.artifact_id
    replay = repository.get_latest_artifact_content(
        job.run_id,
        "hybrid_replay_record",
    )
    assert replay is not None
    assert replay["provider_calls_required"] == 0
