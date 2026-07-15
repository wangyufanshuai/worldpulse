from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import repository


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "observability.db")
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={
            "title": "Observability",
            "question": "lifecycle health",
            "mode": "war_room",
            "event_types": ["conflict"],
            "scenario_config": {"scenario_key": "strait_blockade_30d"},
        },
    ).json()
    return client, project["project_id"]


def test_lifecycle_health_summary_reports_queue_phase_and_integrity(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    queued = client.post(f"/api/v2/projects/{project_id}/runs", json={}).json()
    before = client.get("/api/v2/lifecycle/health")
    assert before.status_code == 200
    assert before.json()["queued"] == 1

    completed = process_one_queued_job(worker_id="health-worker")
    assert completed.status == "completed"
    after = client.get("/api/v2/lifecycle/health").json()
    assert after["completed"] == 1
    assert after["avg_queue_wait_ms"] >= 0
    assert after["phase_durations_ms"]["deterministic_run"]["p50"] >= 0
    assert after["phase_durations_ms"]["deterministic_run"]["p95"] >= after["phase_durations_ms"]["deterministic_run"]["p50"]
    assert after["artifact_integrity_failures"] == 0

    with project_store.connect() as conn:
        conn.execute(
            "UPDATE run_artifacts SET content_json = '{\"tampered\":true}' WHERE artifact_id = "
            "(SELECT artifact_id FROM run_artifacts WHERE run_id = ? ORDER BY rowid LIMIT 1)",
            (queued["run_id"],),
        )
    assert client.get("/api/v2/lifecycle/health").json()["artifact_integrity_failures"] == 1


def test_lifecycle_health_counts_stale_recovery(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    queued = client.post(f"/api/v2/projects/{project_id}/runs", json={}).json()
    claimed = repository.claim_next_job("health-dead")
    assert claimed.run_id == queued["run_id"]
    with project_store.connect() as conn:
        conn.execute("UPDATE run_jobs SET lease_expires_at = '2000-01-01T00:00:00.000' WHERE run_id = ?", (queued["run_id"],))
    recovered = repository.recover_stale_jobs(recovered_by="health-replacement")
    assert recovered[0].status == "queued"
    summary = repository.get_health_summary()
    assert summary.recoveries == 1
