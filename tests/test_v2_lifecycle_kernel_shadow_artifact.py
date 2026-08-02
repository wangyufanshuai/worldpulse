from __future__ import annotations

import json

from fastapi.testclient import TestClient
import pytest

from app.core.models import RunJobCreateRequest, WarRoomRun
from app.main import app
from app.services import project_store
from app.services.consistency.hashing import stable_hash
from app.services.project_app import research_workspace_service
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import repository
from app.services.run_lifecycle import kernel_shadow as kernel_shadow_adapter
from app.services.run_lifecycle.kernel_shadow import (
    KERNEL_SHADOW_ARTIFACT_TYPE,
    KERNEL_SHADOW_MAX_BYTES,
    KERNEL_SHADOW_POLICY_KEY,
    verify_persisted_kernel_shadow_artifact,
)
from app.services.run_lifecycle.integrity import artifact_digest


DEFAULT_DETERMINISTIC_ARTIFACTS = {
    "scenario",
    "environment_manifest",
    "war_room_result",
    "consistency_audit",
    "report_projection_manifest",
    "projection",
    "lifecycle_metrics",
}


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "kernel-shadow-lifecycle.db")
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={
            "title": "Kernel shadow lifecycle",
            "question": "Can stored Kernel lineage replay without a Provider?",
            "mode": "war_room",
        },
    ).json()
    return client, project["project_id"]


def _create(client, project_id: str, *, engine_mode: str = "deterministic", max_attempts: int = 1):
    response = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={
            "engine_mode": engine_mode,
            "scenario": {
                "scenario_key": "strait_blockade_30d",
                "intensity": 0.8,
                "propagation": 0.55,
                "policy_actions": ["sanctions"],
            },
            "seed": 7,
            "max_attempts": max_attempts,
        },
    )
    assert response.status_code == 200
    return response.json()


def _artifact_types(run_id: str) -> set[str]:
    return {item.artifact_type for item in repository.get_artifacts(run_id)}


def test_kernel_shadow_default_off_preserves_exact_lifecycle_and_replay_contract(
    monkeypatch,
    tmp_path,
):
    monkeypatch.delenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", raising=False)
    client, project_id = _setup(monkeypatch, tmp_path)
    created = _create(client, project_id)
    pinned = repository.get_job(created["run_id"])

    assert pinned.runtime_profile == {}
    assert pinned.runtime_profile_hash is None
    completed = lifecycle_executor.process_one_queued_job()
    assert completed is not None and completed.status == "completed"
    assert _artifact_types(created["run_id"]) == DEFAULT_DETERMINISTIC_ARTIFACTS
    assert not any(
        event.title == "Kernel shadow Artifact recorded"
        for event in repository.get_events(created["run_id"])
    )

    replay = research_workspace_service.war_room_replay_pack(
        project_id, run_id=completed.result_run_id
    )
    assert replay.manifest["lifecycle_job_id"] is None
    assert "kernel" not in replay.model_outputs


def test_enabled_kernel_shadow_policy_is_pinned_and_artifact_is_replayable(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "true")
    client, project_id = _setup(monkeypatch, tmp_path)
    created = _create(client, project_id)
    pinned = repository.get_job(created["run_id"])
    policy = pinned.runtime_profile[KERNEL_SHADOW_POLICY_KEY]
    assert policy["enabled"] is True
    assert policy["max_bytes"] == KERNEL_SHADOW_MAX_BYTES
    assert pinned.runtime_profile_hash == stable_hash(pinned.runtime_profile)

    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "false")
    completed = lifecycle_executor.process_one_queued_job()
    assert completed is not None and completed.status == "completed"
    assert _artifact_types(created["run_id"]) == DEFAULT_DETERMINISTIC_ARTIFACTS | {
        KERNEL_SHADOW_ARTIFACT_TYPE
    }

    payload = repository.get_latest_artifact_content(
        created["run_id"], KERNEL_SHADOW_ARTIFACT_TYPE
    )
    source_payload = repository.get_latest_artifact_content(
        created["run_id"], "war_room_result"
    )
    source_summary = repository.get_latest_artifact_summary(
        created["run_id"], "war_room_result"
    )
    assert payload is not None and source_payload is not None and source_summary is not None
    envelope = verify_persisted_kernel_shadow_artifact(
        payload,
        job=repository.get_job(created["run_id"]),
        source_result=WarRoomRun.model_validate(source_payload),
        source_artifact=source_summary,
    )
    assert envelope.baseline_scope == "deterministic_pre_agent"
    assert envelope.replay_stored().content_hash() == envelope.final_state_hash

    events = [
        event
        for event in repository.get_events(created["run_id"])
        if event.title == "Kernel shadow Artifact recorded"
    ]
    assert len(events) == 1
    assert events[0].payload["payload_bytes"] <= KERNEL_SHADOW_MAX_BYTES
    assert events[0].payload["integration_duration_ms"] > 0

    replay = research_workspace_service.war_room_replay_pack(
        project_id, run_id=completed.result_run_id
    )
    assert replay.manifest["verified_lifecycle_artifacts"] == [
        "kernel_shadow_run",
        "war_room_result",
    ]
    assert set(replay.model_outputs["kernel"]["artifacts"]) == {
        "kernel_shadow_run",
        "war_room_result",
    }
    assert any(
        step["step"] == "kernel_offline_evidence_chain"
        for step in replay.audit_trail
    )


def test_reserved_policy_key_cannot_enable_feature_and_invalid_env_fails_closed(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "off")
    client, project_id = _setup(monkeypatch, tmp_path)
    created = repository.create_job(
        project_id,
        RunJobCreateRequest(),
        runtime_profile={KERNEL_SHADOW_POLICY_KEY: {"enabled": True}},
    )
    assert KERNEL_SHADOW_POLICY_KEY not in created.runtime_profile

    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "sometimes")
    with pytest.raises(RuntimeError, match="must be one of"):
        repository.create_job(project_id, RunJobCreateRequest())


def test_enabled_oversize_artifact_fails_before_projection(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "on")
    client, project_id = _setup(monkeypatch, tmp_path)
    created = _create(client, project_id, max_attempts=1)
    monkeypatch.setattr(
        kernel_shadow_adapter,
        "dumps",
        lambda _payload: "x" * (KERNEL_SHADOW_MAX_BYTES + 1),
    )

    failed = lifecycle_executor.process_one_queued_job()
    assert failed is not None and failed.status == "failed"
    assert failed.result_run_id is None
    assert KERNEL_SHADOW_ARTIFACT_TYPE not in _artifact_types(created["run_id"])
    with project_store.connect() as conn:
        projected = conn.execute(
            "SELECT COUNT(*) FROM research_runs WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0]
    assert projected == 0


@pytest.mark.parametrize(
    "engine_mode",
    ["mock_agent", "controlled_agent", "hybrid", "negotiation"],
)
def test_agent_modes_persist_only_deterministic_pre_agent_baseline(
    monkeypatch,
    tmp_path,
    engine_mode,
):
    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "1")
    monkeypatch.setenv("AGENT_PROVIDER", "mock")
    client, project_id = _setup(monkeypatch, tmp_path)
    created = _create(client, project_id, engine_mode=engine_mode)

    completed = lifecycle_executor.process_one_queued_job()
    assert completed is not None and completed.status == "completed"
    payload = repository.get_latest_artifact_content(
        created["run_id"], KERNEL_SHADOW_ARTIFACT_TYPE
    )
    source = repository.get_latest_artifact_content(
        created["run_id"], "war_room_result"
    )
    assert payload is not None and source is not None
    assert payload["baseline_scope"] == "deterministic_pre_agent"
    assert payload["source_run_hash"] == stable_hash(
        WarRoomRun.model_validate(source).model_dump(mode="json")
    )


def test_checkpoint_and_replay_pack_reject_internally_tampered_envelope(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("WORLDPULSE_KERNEL_SHADOW_ARTIFACTS", "true")
    client, project_id = _setup(monkeypatch, tmp_path)
    created = _create(client, project_id, max_attempts=2)
    original_fault_hook = lifecycle_executor.lifecycle_fault_hook

    def fail_after_deterministic_checkpoint(phase: str, moment: str) -> None:
        if phase == "report_generate" and moment == "before":
            raise RuntimeError("checkpoint after Kernel shadow")
        original_fault_hook(phase, moment)

    monkeypatch.setattr(
        lifecycle_executor,
        "lifecycle_fault_hook",
        fail_after_deterministic_checkpoint,
    )
    first = lifecycle_executor.process_one_queued_job()
    assert first is not None and first.status == "queued"

    with project_store.connect() as conn:
        row = conn.execute(
            """
            SELECT artifact_id, content_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = ?
            ORDER BY artifact_version DESC LIMIT 1
            """,
            (created["run_id"], KERNEL_SHADOW_ARTIFACT_TYPE),
        ).fetchone()
        payload = json.loads(row["content_json"])
        payload["event_log_hash"] = "0" * 64
        tampered = project_store.dumps(payload)
        conn.execute(
            "UPDATE run_artifacts SET content_json = ?, sha256 = ? WHERE artifact_id = ?",
            (tampered, artifact_digest(tampered), row["artifact_id"]),
        )
        conn.execute(
            "UPDATE run_jobs SET next_attempt_at = '2000-01-01T00:00:00.000' WHERE run_id = ?",
            (created["run_id"],),
        )

    monkeypatch.setattr(lifecycle_executor, "lifecycle_fault_hook", original_fault_hook)
    second = lifecycle_executor.process_one_queued_job()
    assert second is not None and second.status == "failed"
    assert second.result_run_id is None

    # A separately completed run must also fail Replay Pack export if an
    # attacker rewrites the nested envelope and recomputes only the outer SHA.
    clean = _create(client, project_id)
    completed = lifecycle_executor.process_one_queued_job()
    assert completed is not None and completed.status == "completed"
    with project_store.connect() as conn:
        row = conn.execute(
            """
            SELECT artifact_id, content_json FROM run_artifacts
            WHERE run_id = ? AND artifact_type = ?
            ORDER BY artifact_version DESC LIMIT 1
            """,
            (clean["run_id"], KERNEL_SHADOW_ARTIFACT_TYPE),
        ).fetchone()
        payload = json.loads(row["content_json"])
        payload["shadow_run_hash"] = "0" * 64
        tampered = project_store.dumps(payload)
        conn.execute(
            "UPDATE run_artifacts SET content_json = ?, sha256 = ? WHERE artifact_id = ?",
            (tampered, artifact_digest(tampered), row["artifact_id"]),
        )

    with pytest.raises(ValueError, match="shadow-run hash mismatch"):
        research_workspace_service.war_room_replay_pack(
            project_id, run_id=completed.result_run_id
        )
