from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import repository
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import process_one_queued_job


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "concurrency.db")
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={
            "title": "Concurrency",
            "question": "event sequence and lineage",
            "mode": "war_room",
            "event_types": ["conflict"],
            "scenario_config": {"scenario_key": "strait_blockade_30d"},
        },
    ).json()
    return client, project["project_id"]


def test_event_sequence_is_atomic_under_concurrent_append(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    run = client.post(f"/api/v2/projects/{project_id}/runs", json={}).json()

    def append(index):
        return repository.append_event(
            run["run_id"], "WORKER", "scenario_compile", f"concurrent-{index}", "parallel event"
        ).seq

    with ThreadPoolExecutor(max_workers=8) as pool:
        seqs = list(pool.map(append, range(40)))
    events = repository.get_events(run["run_id"])
    assert sorted(seqs) == list(range(2, 42))
    assert [item.seq for item in events] == list(range(1, 42))


def test_atomic_claim_assigns_distinct_attempts_and_jobs(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    first = client.post(f"/api/v2/projects/{project_id}/runs", json={}).json()
    second = client.post(f"/api/v2/projects/{project_id}/runs", json={}).json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(repository.claim_next_job, ["worker-a", "worker-b"]))
    claimed = [item for item in claimed if item is not None]
    assert {item.run_id for item in claimed} == {first["run_id"], second["run_id"]}
    assert len({item.current_attempt_id for item in claimed}) == 2


def test_failed_attempt_artifacts_are_not_selected_over_new_attempt(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    run = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"scenario": {"scenario_key": "food_shortfall"}, "max_attempts": 2},
    ).json()
    original_add = lifecycle_executor.repository.add_artifact
    failed_once = {"value": False}

    def fail_report_once(run_id, artifact_type, schema_version, content, **kwargs):
        artifact = original_add(run_id, artifact_type, schema_version, content, **kwargs)
        if artifact_type == "report_projection_manifest" and not failed_once["value"]:
            failed_once["value"] = True
            raise RuntimeError("after report artifact")
        return artifact

    monkeypatch.setattr(lifecycle_executor.repository, "add_artifact", fail_report_once)
    first = process_one_queued_job(worker_id="worker-a")
    assert first.status == "queued"
    with project_store.connect() as conn:
        conn.execute("UPDATE run_jobs SET next_attempt_at = '2000-01-01T00:00:00.000' WHERE run_id = ?", (run["run_id"],))
    monkeypatch.setattr(lifecycle_executor.repository, "add_artifact", original_add)
    second = process_one_queued_job(worker_id="worker-b")
    assert second.status == "completed"

    report_artifacts = [item for item in repository.get_artifacts(run["run_id"]) if item.artifact_type == "report_projection_manifest"]
    assert len(report_artifacts) == 2
    assert len({item.attempt_id for item in report_artifacts}) == 2
    assert report_artifacts[-1].supersedes_artifact_id == report_artifacts[0].artifact_id
    latest = repository.get_latest_artifact_content(run["run_id"], "report_projection_manifest")
    assert latest["workspace_compatible"] is True
    attempts = repository.get_attempts(run["run_id"])
    assert attempts[0].status == "failed"
    assert attempts[1].status == "completed"
