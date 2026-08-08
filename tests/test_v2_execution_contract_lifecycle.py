from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.models import RunJobCreateRequest, WarRoomScenarioRequest
from app.main import app
from app.services import project_store
from app.services.consistency.hashing import stable_hash
from app.services.run_lifecycle import checkpoints, repository
from app.services.run_lifecycle.execution_contract import (
    KERNEL_MODE_EXECUTION_V2,
    V2ExecutionPathNotEnabledError,
    pin_legacy_execution_contract,
    report_replay_step_versions,
    select_execution_contract,
)
from app.services.run_lifecycle.steps import (
    begin_step,
    complete_step,
    step_definitions_for_runtime_profile,
)


def _v2_profile(*, seed: int = 0) -> dict:
    return {
        "execution_contract_version": KERNEL_MODE_EXECUTION_V2,
        "effective_seed": seed,
        "minimum_worker_generation": 2,
        "agent_pack_resolver_version": "agent-pack-resolver.v1",
        "constraint_context_resolver_version": "constraint-context-resolver.v1",
        "evaluator_version": "worldpulse-consistency.v0.8",
    }


def _setup_project(monkeypatch, tmp_path) -> str:
    monkeypatch.setattr(
        project_store, "DB_PATH", tmp_path / "execution-contract-test.db"
    )
    client = TestClient(app)
    response = client.post(
        "/api/projects",
        json={
            "title": "Execution contract test",
            "question": "Verify fail-closed V2 lifecycle selection",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d"},
            "event_types": ["conflict"],
        },
    )
    assert response.status_code == 200
    return response.json()["project_id"]


def test_execution_contract_selection_is_key_absent_v1_or_complete_exact_v2():
    assert report_replay_step_versions({}) == (
        "report-generate.v1",
        "replay-archive.v1",
    )
    selected = select_execution_contract(_v2_profile(seed=0))
    assert selected.is_v2 is True
    assert selected.profile is not None and selected.profile.effective_seed == 0
    assert report_replay_step_versions(_v2_profile()) == (
        "report-generate.v2",
        "replay-archive.v2",
    )

    with pytest.raises(ValueError, match="unknown lifecycle execution contract"):
        select_execution_contract({"execution_contract_version": "kernel-mode-execution.v3"})
    with pytest.raises(ValueError, match="missing required keys"):
        select_execution_contract({"execution_contract_version": KERNEL_MODE_EXECUTION_V2})
    with pytest.raises(ValueError, match="orphaned V2 keys"):
        select_execution_contract({"effective_seed": 42})
    with pytest.raises(ValueError, match="baseline-derived"):
        select_execution_contract({"agent_pack_hash": "a" * 64})


def test_step_selection_never_mixes_v1_and_v2_report_replay_versions():
    legacy = {item.key: item.version for item in step_definitions_for_runtime_profile({})}
    treatment = {
        item.key: item.version
        for item in step_definitions_for_runtime_profile(_v2_profile())
    }
    assert legacy["report_generate"] == "report-generate.v1"
    assert legacy["replay_archive"] == "replay-archive.v1"
    assert treatment["report_generate"] == "report-generate.v2"
    assert treatment["replay_archive"] == "replay-archive.v2"
    assert {
        key: version
        for key, version in legacy.items()
        if key not in {"report_generate", "replay_archive"}
    } == {
        key: version
        for key, version in treatment.items()
        if key not in {"report_generate", "replay_archive"}
    }


def test_persisted_step_uses_runtime_profile_selected_version(monkeypatch, tmp_path):
    project_id = _setup_project(monkeypatch, tmp_path)
    created = repository.create_job(project_id, RunJobCreateRequest(seed=23))
    legacy = begin_step(
        created.run_id,
        "report_generate",
        "attempt-legacy-version",
        {"kind": "legacy"},
    )
    treatment = begin_step(
        created.run_id,
        "report_generate",
        "attempt-v2-version",
        {"kind": "v2"},
        runtime_profile=_v2_profile(seed=23),
    )

    assert legacy.step_version == "report-generate.v1"
    assert treatment.step_version == "report-generate.v2"


def test_v2_checkpoint_never_restores_a_prior_attempt_step(monkeypatch, tmp_path):
    project_id = _setup_project(monkeypatch, tmp_path)
    created = repository.create_job(project_id, RunJobCreateRequest(seed=29))
    profile = _v2_profile(seed=29)
    with project_store.connect() as connection:
        connection.execute(
            """
            UPDATE run_jobs
            SET runtime_profile_json = ?, runtime_profile_hash = ?,
                current_attempt_id = 'attempt-current'
            WHERE run_id = ?
            """,
            (project_store.dumps(profile), stable_hash(profile), created.run_id),
        )
    step_input = {
        "run_id": created.run_id,
        "engine_mode": created.engine_mode,
        "scenario_hash": stable_hash(created.scenario),
        "previous_step_id": None,
        "previous_output_hash": None,
        "previous_artifact_refs": [],
    }
    prior = begin_step(
        created.run_id,
        "scenario_compile",
        "attempt-prior",
        step_input,
        runtime_profile=profile,
    )
    complete_step(prior.step_id, {"artifact_refs": []}, [])

    job = repository.get_job(created.run_id)
    assert checkpoints.load_verified_checkpoint(job).completed_steps == []

    current = begin_step(
        created.run_id,
        "scenario_compile",
        "attempt-current",
        step_input,
        runtime_profile=profile,
    )
    complete_step(current.step_id, {"artifact_refs": []}, [])
    restored = checkpoints.load_verified_checkpoint(job)
    assert [item.step_id for item in restored.completed_steps] == [current.step_id]


def test_normal_creation_strips_caller_v2_and_derived_profile_keys(monkeypatch, tmp_path):
    project_id = _setup_project(monkeypatch, tmp_path)
    requested = {
        **_v2_profile(seed=17),
        "agent_pack_id": "caller-pack",
        "agent_pack_hash": "a" * 64,
        "constraint_context_hash": "b" * 64,
        "provider": "mock",
    }
    created = repository.create_job(
        project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            scenario=WarRoomScenarioRequest(seed=17),
            seed=17,
        ),
        runtime_profile=requested,
    )
    assert created.runtime_profile == {"provider": "mock"}
    assert pin_legacy_execution_contract(requested) == {"provider": "mock"}


def test_v2_or_unknown_profile_fails_before_claim_mutation(monkeypatch, tmp_path):
    project_id = _setup_project(monkeypatch, tmp_path)
    created = repository.create_job(
        project_id,
        RunJobCreateRequest(
            engine_mode="deterministic",
            scenario=WarRoomScenarioRequest(seed=17),
            seed=17,
        ),
    )
    profile = _v2_profile(seed=17)
    with project_store.connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET runtime_profile_json = ?, runtime_profile_hash = ? WHERE run_id = ?",
            (project_store.dumps(profile), stable_hash(profile), created.run_id),
        )
    before = repository.get_job(created.run_id)
    with pytest.raises(V2ExecutionPathNotEnabledError):
        repository.claim_next_job(worker_id="worker-v1")
    after = repository.get_job(created.run_id)
    assert after.status == before.status == "queued"
    assert after.attempt_count == before.attempt_count == 0
    assert after.current_attempt_id is None
    assert after.worker_id is None

    unknown = {"execution_contract_version": "unknown.v9"}
    with project_store.connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET runtime_profile_json = ?, runtime_profile_hash = ? WHERE run_id = ?",
            (project_store.dumps(unknown), stable_hash(unknown), created.run_id),
        )
    with pytest.raises(ValueError, match="unknown lifecycle execution contract"):
        repository.claim_next_job(worker_id="worker-v1")
    unchanged = repository.get_job(created.run_id)
    assert unchanged.status == "queued"
    assert unchanged.attempt_count == 0
    assert unchanged.current_attempt_id is None

    legacy_profile = {"provider": "historic-legacy"}
    with project_store.connect() as connection:
        connection.execute(
            "UPDATE run_jobs SET runtime_profile_json = ?, runtime_profile_hash = NULL WHERE run_id = ?",
            (project_store.dumps(legacy_profile), created.run_id),
        )
    claimed = repository.claim_next_job(worker_id="worker-v1")
    assert claimed is not None and claimed.run_id == created.run_id
    assert claimed.status == "preparing"
    assert claimed.attempt_count == 1
