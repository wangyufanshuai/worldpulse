from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import executor as lifecycle_executor
from app.services.run_lifecycle import repository


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "phase2.db")
    client = TestClient(app)
    project = client.post(
        "/api/projects",
        json={
            "title": "Phase 2",
            "question": "checkpoint recovery",
            "mode": "war_room",
            "event_types": ["conflict"],
            "scenario_config": {"scenario_key": "strait_blockade_30d"},
        },
    ).json()
    return client, project["project_id"]


def _make_due(monkeypatch, run_id):
    with project_store.connect() as conn:
        conn.execute(
            "UPDATE run_jobs SET next_attempt_at = '2000-01-01T00:00:00.000' WHERE run_id = ?",
            (run_id,),
        )


def test_idempotency_key_reuses_job_and_rejects_changed_request(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    headers = {"Idempotency-Key": "phase2-create-1"}
    first = client.post(
        f"/api/v2/projects/{project_id}/runs",
        headers=headers,
        json={"scenario": {"scenario_key": "food_shortfall"}, "seed": 7},
    )
    second = client.post(
        f"/api/v2/projects/{project_id}/runs",
        headers=headers,
        json={"scenario": {"scenario_key": "food_shortfall"}, "seed": 7},
    )
    changed = client.post(
        f"/api/v2/projects/{project_id}/runs",
        headers=headers,
        json={"scenario": {"scenario_key": "food_shortfall"}, "seed": 8},
    )
    assert first.status_code == second.status_code == 200
    assert first.json()["run_id"] == second.json()["run_id"]
    assert changed.status_code == 409


def test_worker_resumes_after_verified_checkpoint_without_repeating_prior_steps(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"scenario": {"scenario_key": "food_shortfall"}, "max_attempts": 3},
    ).json()
    original = lifecycle_executor.run_war_room
    calls = {"count": 0}

    def fail_once(scenario):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("checkpoint test")
        return original(scenario)

    monkeypatch.setattr(lifecycle_executor, "run_war_room", fail_once)
    first = process_one_queued_job(worker_id="phase2-a")
    assert first.status == "queued"
    first_steps = client.get(f"/api/v2/runs/{created['run_id']}/steps").json()
    assert [item["step_key"] for item in first_steps] == ["scenario_compile", "environment_prepare", "deterministic_run"]
    assert [item["status"] for item in first_steps] == ["completed", "completed", "failed"]

    _make_due(monkeypatch, created["run_id"])
    second = process_one_queued_job(worker_id="phase2-b")
    assert second.status == "completed"
    assert calls["count"] == 2
    all_steps = client.get(f"/api/v2/runs/{created['run_id']}/steps").json()
    assert [item["step_key"] for item in all_steps[:2]] == ["scenario_compile", "environment_prepare"]
    assert all_steps[0]["attempt_id"] != all_steps[-1]["attempt_id"]
    assert any(event["title"] == "Verified checkpoint restored" for event in client.get(f"/api/v2/runs/{created['run_id']}/events").json())
    attempts = client.get(f"/api/v2/runs/{created['run_id']}/audit").json()["attempts"]
    assert [item["attempt_number"] for item in attempts] == [1, 2]
    assert attempts[0]["status"] == "failed"
    assert attempts[1]["status"] == "completed"


def test_retry_backoff_and_terminal_reason_after_max_attempts(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"scenario": {"scenario_key": "food_shortfall"}, "max_attempts": 2},
    ).json()
    monkeypatch.setattr(
        lifecycle_executor,
        "run_war_room",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("always fails")),
    )
    first = process_one_queued_job()
    assert first.status == "queued"
    assert first.terminal_reason == "retry_scheduled"
    assert first.next_attempt_at
    _make_due(monkeypatch, created["run_id"])
    second = process_one_queued_job()
    assert second.status == "failed"
    assert second.terminal_reason == "max_attempts_exhausted"
    assert second.attempt_count == 2
