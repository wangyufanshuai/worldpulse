from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import process_one_queued_job


def _setup_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "worldpulse_lifecycle_test.db")


def _create_war_room_project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={
            "title": "Lifecycle War Room",
            "question": "Run lifecycle test",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d", "duration_days": 30, "intensity": 0.7, "propagation": 0.45},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    assert response.status_code == 200
    return response.json()["project_id"]


def test_lifecycle_tables_are_created(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    project_store.init_db()
    with project_store.connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()}
    assert {"run_jobs", "run_events", "run_artifacts"}.issubset(tables)


def test_v2_create_run_returns_queued_and_events_filter(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)

    response = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "deterministic", "scenario": {"scenario_key": "energy_export_cut", "duration_days": 30}, "seed": 42},
    )
    assert response.status_code == 200
    run = response.json()
    assert run["status"] == "queued"
    assert run["current_phase"] == "scenario_compile"

    events = client.get(f"/api/v2/runs/{run['run_id']}/events").json()
    assert events[0]["seq"] == 1
    assert events[0]["event_type"] == "WORKER"
    assert client.get(f"/api/v2/runs/{run['run_id']}/events", params={"after_seq": events[0]["seq"]}).json() == []
    assert client.get(f"/api/v2/runs/{run['run_id']}/audit").json()["consistency_audit"] is None


def test_worker_once_completes_and_projects_to_v1_war_room(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "deterministic", "scenario": {"scenario_key": "strait_blockade_30d", "duration_days": 30}, "seed": 42},
    ).json()

    processed = process_one_queued_job()
    assert processed is not None
    assert processed.status == "completed"
    assert processed.result_run_id

    status = client.get(f"/api/v2/runs/{created['run_id']}").json()
    assert status["status"] == "completed"
    assert status["result_run_id"] == processed.result_run_id

    workspace = client.get(f"/api/projects/{project_id}/war-room/workspace", params={"run_id": processed.result_run_id})
    assert workspace.status_code == 200
    assert workspace.json()["replay_ready"] is True

    replay = client.get(f"/api/projects/{project_id}/war-room/replay-pack", params={"run_id": processed.result_run_id})
    assert replay.status_code == 200
    assert replay.json()["manifest"]["run_id"] == processed.result_run_id

    artifacts = client.get(f"/api/v2/runs/{created['run_id']}/artifacts").json()
    assert {item["artifact_type"] for item in artifacts} >= {"scenario", "war_room_result", "consistency_audit", "projection"}

    audit = client.get(f"/api/v2/runs/{created['run_id']}/audit")
    assert audit.status_code == 200
    report = audit.json()["consistency_audit"]
    assert report["schema_version"] == "consistency-audit.v1"
    assert report["overall_status"] == "warning"
    assert report["summary"]["read_only"] is True
    assert report["audit_hash"]
    consistency_events = [event for event in audit.json()["events"] if event["event_type"] == "CONSISTENCY"]
    assert consistency_events[-1]["payload"]["audit_hash"] == report["audit_hash"]


def test_cancel_queued_and_retry_creates_child_job(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)
    run = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()

    cancelled = client.post(f"/api/v2/runs/{run['run_id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["run"]["status"] == "cancelled"

    retried = client.post(f"/api/v2/runs/{run['run_id']}/retry")
    assert retried.status_code == 200
    assert retried.json()["run"]["status"] == "queued"
    assert retried.json()["run"]["parent_run_id"] == run["run_id"]


def test_pause_and_resume_queued_job(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)
    run = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()

    paused = client.post(f"/api/v2/runs/{run['run_id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["run"]["status"] == "paused"

    resumed = client.post(f"/api/v2/runs/{run['run_id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["run"]["status"] == "queued"

    processed = process_one_queued_job()
    assert processed is not None
    assert processed.status == "completed"


def test_mock_agent_lifecycle_records_proposals_and_action_decisions(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "mock_agent", "scenario": {"scenario_key": "strait_blockade_30d"}, "seed": 42},
    ).json()

    processed = process_one_queued_job()
    assert processed is not None
    assert processed.status == "completed"
    assert processed.engine_mode == "mock_agent"

    audit = client.get(f"/api/v2/runs/{created['run_id']}/audit").json()
    artifacts = {item["artifact_type"] for item in audit["artifacts"]}
    report = audit["consistency_audit"]
    assert "agent_action_proposals" in artifacts
    assert report["schema_version"] == "consistency-audit.v2"
    assert report["summary"]["agent_action_count"] == 4
    assert report["summary"]["accepted_action_count"] == 4
    assert {item["decision"] for item in report["proposal_decisions"]} == {"accepted"}
    agent_events = [event for event in audit["events"] if event["event_type"] == "AGENT"]
    assert agent_events[-1]["payload"]["proposal_count"] == 4
    assert agent_events[-1]["payload"]["batch_hash"]


def test_sse_stream_returns_existing_event(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    project_id = _create_war_room_project(client)
    run = client.post(f"/api/v2/projects/{project_id}/runs", json={"scenario": {"scenario_key": "food_shortfall"}}).json()

    with client.stream("GET", f"/api/v2/runs/{run['run_id']}/events/stream") as response:
        assert response.status_code == 200
        body = next(response.iter_text())
    assert "event: WORKER" in body
    assert "Run lifecycle job queued" in body
