from __future__ import annotations

import pytest

from app.services.project_store import connect
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import repository, steps
from app.services.run_lifecycle.executor import process_job
from app.services.run_lifecycle.mode_execution_adapter import (
    ModeExecutionAdapterError,
)

from test_v2_controlled_mode_execution_adapter import _setup_claimed_controlled


def _setup_claimed_negotiation(monkeypatch, tmp_path):
    job, capability = _setup_claimed_controlled(monkeypatch, tmp_path)
    with connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET engine_mode = 'negotiation' WHERE run_id = ?",
            (job.run_id,),
        )
    refreshed = repository.get_job(job.run_id)
    assert refreshed.engine_mode == "negotiation"
    return refreshed, capability


def test_negotiation_v2_persists_and_finalizes_the_canonical_proof(
    monkeypatch,
    tmp_path,
) -> None:
    job, _ = _setup_claimed_negotiation(monkeypatch, tmp_path)

    completed = process_job(job.run_id)

    assert completed.status == "completed"
    proof_step = next(
        item
        for item in steps.get_steps(job.run_id)
        if item.step_key == "consistency_audit" and item.status == "completed"
    )
    proof_schemas = [item[4] for item in proof_step.output["artifact_refs"]]
    assert proof_schemas[:30] == (
        ["kp.negotiation-round.v1"] * 6
        + ["kp.negotiation-proposal-batch.v1"] * 6
        + ["kp.negotiation-admission-consistency.v1"] * 6
        + ["kp.commitment-ledger.v1"] * 6
        + ["kp.negotiation-eligibility.v1"] * 6
    )
    projection_count = proof_schemas.count(
        "kp.negotiation-projection-consistency.v1"
    )
    assert len(proof_schemas) == 38 + 3 * projection_count
    assert proof_schemas[-1] == "kp.negotiation-replay.v1"

    replay = repository.get_latest_artifact_content(
        job.run_id,
        "negotiation_replay",
    )
    assert replay is not None
    assert replay["schema_version"] == "negotiation-replay.v2"
    assert replay["provider_calls_required"] == 0
    manifest = repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    )
    assert manifest is not None
    assert manifest["execution_record"]["kernel_mode"] == "negotiation"
    assert (
        manifest["execution_record"]["authority_path"]
        == "negotiation_governed_deterministic"
    )


def test_negotiation_v2_report_resume_is_provider_free(monkeypatch, tmp_path) -> None:
    job, _ = _setup_claimed_negotiation(monkeypatch, tmp_path)
    stopped = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not stopped["value"]:
            stopped["value"] = True
            raise RuntimeError("negotiation sources captured")

    monkeypatch.setattr(lifecycle_executor, "lifecycle_fault_hook", stop_before_report)
    with pytest.raises(RuntimeError, match="negotiation sources captured"):
        process_job(job.run_id)

    def forbidden_negotiation(*_args, **_kwargs):
        raise AssertionError("negotiation report resume may not invoke the Provider path")

    monkeypatch.setattr(
        lifecycle_executor,
        "run_negotiation",
        forbidden_negotiation,
    )
    completed = process_job(job.run_id)
    assert completed.status == "completed"


def test_negotiation_v2_tampered_source_fails_before_report(monkeypatch, tmp_path) -> None:
    job, _ = _setup_claimed_negotiation(monkeypatch, tmp_path)
    stopped = {"value": False}

    def stop_before_report(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before" and not stopped["value"]:
            stopped["value"] = True
            raise RuntimeError("negotiation proof captured")

    monkeypatch.setattr(lifecycle_executor, "lifecycle_fault_hook", stop_before_report)
    with pytest.raises(RuntimeError, match="negotiation proof captured"):
        process_job(job.run_id)

    with connect() as connection:
        row = connection.execute(
            """
            SELECT artifact_id, content_json
            FROM run_artifacts
            WHERE run_id = ? AND schema_version = 'negotiation-replay.v2'
            """,
            (job.run_id,),
        ).fetchone()
        assert row is not None
        connection.execute(
            "UPDATE run_artifacts SET content_json = ? WHERE artifact_id = ?",
            (
                row["content_json"].replace(
                    '"provider_calls_required": 0',
                    '"provider_calls_required": 1',
                ),
                row["artifact_id"],
            ),
        )

    with pytest.raises((ModeExecutionAdapterError, ValueError)):
        process_job(job.run_id)
    assert repository.get_latest_artifact_content(
        job.run_id,
        "report_projection_manifest",
    ) is None
