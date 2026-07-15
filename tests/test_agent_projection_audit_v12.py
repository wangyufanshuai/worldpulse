from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import process_one_queued_job


def _project(client: TestClient) -> str:
    response = client.post(
        "/api/projects",
        json={
            "title": "V1.2 projection audit",
            "question": "Controlled Agent projection audit",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d", "duration_days": 30},
            "event_types": ["conflict", "trade"],
        },
    )
    assert response.status_code == 200
    return response.json()["project_id"]


def test_hybrid_run_persists_per_action_projection_audit(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v12_projection.db")
    client = TestClient(app)
    project_id = _project(client)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "hybrid", "scenario": {"scenario_key": "strait_blockade_30d"}, "seed": 42},
    ).json()

    process_one_queued_job(worker_id="worker_v12")
    audit = client.get(f"/api/v2/runs/{created['run_id']}/audit").json()
    projection = audit["action_projection_audit"]
    assert projection["schema_version"] == "agent-action-projection-audit.v1"
    assert projection["projection_mode"] == "hybrid"
    assert projection["projected_count"] == 4
    assert len(projection["records"]) == 4
    assert all(item["projection_status"] == "projected" for item in projection["records"])
    assert all(item["input_hash"] and item["rule_version"] for item in projection["records"])
    assert projection["final_result_hash"] == audit["hybrid"]["replay_record"]["final_result_hash"]


def test_controlled_agent_keeps_projection_audit_read_only(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v12_audit_only.db")
    client = TestClient(app)
    project_id = _project(client)
    created = client.post(
        f"/api/v2/projects/{project_id}/runs",
        json={"engine_mode": "controlled_agent", "scenario": {"scenario_key": "strait_blockade_30d"}, "seed": 42},
    ).json()

    process_one_queued_job(worker_id="worker_v12")
    audit = client.get(f"/api/v2/runs/{created['run_id']}/audit").json()
    projection = audit["action_projection_audit"]
    assert projection["projection_mode"] == "audit_only"
    assert projection["projected_count"] == 0
    assert {item["projection_status"] for item in projection["records"]} == {"not_projected"}
