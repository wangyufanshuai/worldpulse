from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.run_lifecycle import process_one_queued_job
from app.core.models import WarRoomScenarioRequest
from app.services.consistency.projection import verify_action_projection_audit
from app.services.hybrid_simulation import replay_hybrid_from_artifacts, run_hybrid_simulation
from app.services.agent_contract import build_mock_agent_batch
from app.services.consistency import evaluate_war_room_result
from app.services.war_room_engine import run_war_room
import pytest


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


def test_projection_audit_tampering_fails_closed_and_replay_checks_linkage():
    baseline = run_war_room(WarRoomScenarioRequest(scenario_key="strait_blockade_30d"))
    batch = build_mock_agent_batch(baseline, run_id="job_projection_replay", seed=42)
    report = evaluate_war_room_result(
        baseline,
        run_id="job_projection_replay",
        proposals=batch.proposals,
        constraint_context=batch.constraint_context,
    )
    outcome = run_hybrid_simulation(baseline, batch.proposals, report, seed=42)
    projection = outcome.projection_audit.model_dump(mode="json")
    verify_action_projection_audit(outcome.projection_audit)

    tampered = dict(projection)
    tampered["records"] = [dict(projection["records"][0], projection_status="blocked")] + projection["records"][1:]
    with pytest.raises(ValueError, match="audit hash mismatch"):
        verify_action_projection_audit(type(outcome.projection_audit).model_validate(tampered))

    replayed = replay_hybrid_from_artifacts(
        baseline.model_dump(mode="json"),
        {"proposals": [item.model_dump(mode="json") for item in batch.proposals]},
        report.model_dump(mode="json"),
        outcome.modifier_bundle.model_dump(mode="json"),
        outcome.replay_record.model_dump(mode="json"),
        projection,
    )
    assert replayed.timeline[-1].global_risk == outcome.final_result.timeline[-1].global_risk
