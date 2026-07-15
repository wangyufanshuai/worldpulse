from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services import project_store
from app.services.agent_runtime import runtime_config_from_env
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import repository


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "reliability.db")
    client = TestClient(app)
    project = client.post("/api/projects", json={
        "title": "Reliability",
        "question": "Verify worker recovery and artifact integrity",
        "mode": "war_room",
        "event_types": ["conflict"],
        "scenario_config": {"scenario_key": "strait_blockade_30d"},
    }).json()
    return client, project["project_id"]


def test_stale_worker_lease_is_requeued_and_completed(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()
    claimed = repository.claim_next_job("worker_dead")
    assert claimed.worker_id == "worker_dead"
    assert claimed.attempt_count == 1
    with project_store.connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET status = 'running', lease_expires_at = '2000-01-01T00:00:00.000' WHERE run_id = ?",
            (created["run_id"],),
        )

    recovered = repository.recover_stale_jobs(recovered_by="worker_replacement")
    assert [item.run_id for item in recovered] == [created["run_id"]]
    assert recovered[0].status == "queued"
    assert recovered[0].worker_id is None

    completed = process_one_queued_job(worker_id="worker_replacement")
    assert completed.status == "completed"
    assert completed.attempt_count == 2
    assert completed.worker_id is None
    events = repository.get_events(created["run_id"])
    assert any(event.title == "Stale worker lease recovered" for event in events)
    metrics = repository.get_latest_artifact_content(created["run_id"], "lifecycle_metrics")
    assert metrics["attempt_count"] == 2
    assert set(metrics["phase_durations_ms"]) == {
        "scenario_compile", "environment_prepare", "deterministic_run",
        "consistency_audit", "report_generate", "replay_archive",
    }


def test_artifact_tampering_is_visible_and_content_read_fails_closed(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()
    assert process_one_queued_job().status == "completed"
    with project_store.connect() as conn:
        conn.execute(
            "UPDATE run_artifacts SET content_json = '{\"tampered\": true}' WHERE run_id = ? AND artifact_type = 'consistency_audit'",
            (created["run_id"],),
        )

    artifacts = repository.get_artifacts(created["run_id"])
    target = next(item for item in artifacts if item.artifact_type == "consistency_audit")
    assert target.integrity_status == "failed"
    assert repository.verify_artifacts(created["run_id"])["invalid_count"] == 1
    with pytest.raises(HTTPException) as exc:
        repository.get_latest_artifact_content(created["run_id"], "consistency_audit")
    assert exc.value.status_code == 409
    assert client.get(f"/api/v2/runs/{created['run_id']}/audit").status_code == 409


def test_recovery_after_projection_is_idempotent(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()
    first = process_one_queued_job(worker_id="worker_first")
    assert first.status == "completed"
    with project_store.connect() as conn:
        initial_count = conn.execute("SELECT COUNT(*) AS count FROM research_runs WHERE project_id = ?", (project_id,)).fetchone()["count"]
        conn.execute(
            "UPDATE run_jobs SET status = 'running', result_run_id = NULL, worker_id = 'worker_dead', lease_expires_at = '2000-01-01T00:00:00.000' WHERE run_id = ?",
            (created["run_id"],),
        )
    repository.recover_stale_jobs(recovered_by="worker_second")
    recovered = process_one_queued_job(worker_id="worker_second")
    with project_store.connect() as conn:
        final_count = conn.execute("SELECT COUNT(*) AS count FROM research_runs WHERE project_id = ?", (project_id,)).fetchone()["count"]
    assert recovered.status == "completed"
    assert recovered.result_run_id == first.result_run_id
    assert final_count == initial_count == 1


def test_lifecycle_events_and_failures_redact_secrets(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()
    bearer_secret = "Bearer " + "secret-token-123"
    key_secret = "sk-" + "secretsecret123"
    event = repository.append_event(
        created["run_id"], "WORKER", "scenario_compile", "provider error",
        f"Authorization {bearer_secret} and api_key={key_secret}",
        payload={"password": "password=hunter2", "nested": ["token=my-token"]},
    )
    assert "secret-token" not in event.detail
    assert "sk-secret" not in event.detail
    assert "hunter2" not in str(event.payload)
    assert "my-token" not in str(event.payload)
    repository.update_job_status(created["run_id"], status="failed", error_message="secret=" + "sk-" + "private12345", completed=True)
    assert "sk-private" not in repository.get_job(created["run_id"]).error_message


def test_runtime_environment_is_bounded_and_invalid_values_fall_back(monkeypatch):
    monkeypatch.setenv("AGENT_PROVIDER", "not-allowlisted")
    monkeypatch.setenv("AGENT_MAX_TURNS", "not-an-int")
    monkeypatch.setenv("AGENT_MAX_AGENTS", "999")
    monkeypatch.setenv("AGENT_TIMEOUT_SECONDS", "-5")
    monkeypatch.setenv("AGENT_FALLBACK_MODE", "unsafe")
    config = runtime_config_from_env()
    assert config.provider == "mock"
    assert config.max_turns == 1
    assert config.max_agents == 8
    assert config.timeout_seconds == 0.05
    assert config.fallback_mode == "mock"


def test_v2_scenario_rejects_unknown_or_oversized_input(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    unknown = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall", "unknown": "field"}})
    oversized = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "x" * 81}})
    assert unknown.status_code == 422
    assert oversized.status_code == 422
