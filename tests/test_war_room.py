import json
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.core.models import WarRoomScenarioRequest
from app.services import project_store
from app.services.war_room_engine import run_war_room


def _setup_tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "worldpulse_war_room_test.db")


def test_war_room_presets_contract():
    client = TestClient(app)
    response = client.get("/api/war-room/presets")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["countries"]) == 10
    assert len(payload["supply_chains"]) == 5
    assert len(payload["conflict_events"]) == 3
    assert len(payload["scenarios"]) == 3
    assert "策略沙盘" in payload["disclaimer"]


def test_strait_blockade_generates_graph_heatmap_and_decisions():
    client = TestClient(app)
    response = client.post(
        "/api/war-room/run",
        json={"scenario_key": "strait_blockade_30d", "duration_days": 30, "intensity": 0.75, "propagation": 0.48},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["timeline"]
    assert payload["impact_graph"]["nodes"]
    assert payload["impact_graph"]["edges"]
    assert payload["risk_heatmap"]
    assert payload["agent_decisions"]
    assert payload["agent_decisions"][0]["drivers"]
    assert payload["agent_decisions"][0]["expected_tradeoff"]
    assert payload["impact_graph"]["edges"][0]["mechanism"]
    assert "lag_days" in payload["impact_graph"]["edges"][0]
    assert payload["risk_heatmap"][0]["risk_breakdown"]
    assert payload["assumptions"]
    assert "Not a prediction" in payload["disclaimer"]
    assert "策略沙盘" in payload["disclaimer"]
    assert payload["ui_state"]["kpis"]
    assert payload["ui_state"]["map_entities"]
    assert payload["ui_state"]["timeline_events"]
    assert payload["ui_state"]["agent_panels"]
    assert "Not a prediction" in payload["ui_state"]["display"]["disclaimer_zh"]
    timeline_event = payload["ui_state"]["timeline_events"][0]
    assert timeline_event["related_countries"]
    assert "related_chains" in timeline_event
    assert "event_keys" in timeline_event
    top_code = payload["risk_heatmap"][0]["country_code"]
    agent_panel = payload["ui_state"]["agent_panels"][top_code]
    assert agent_panel["strategic_intent_zh"]
    assert agent_panel["trigger_source_zh"]
    assert agent_panel["decision_basis_zh"]
    assert agent_panel["expected_tradeoff_zh"]


def test_war_room_same_input_is_deterministic():
    client = TestClient(app)
    scenario = {
        "scenario_key": "strait_blockade_30d",
        "duration_days": 30,
        "intensity": 0.75,
        "propagation": 0.48,
        "policy_actions": ["alliance_deterrence", "public_messaging"],
    }

    first = client.post("/api/war-room/run", json=scenario)
    second = client.post("/api/war-room/run", json=scenario)

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["risk_heatmap"] == second.json()["risk_heatmap"]
    assert first.json()["supply_chains"] == second.json()["supply_chains"]
    assert first.json()["agent_decisions"] == second.json()["agent_decisions"]
    assert first.json()["impact_graph"] == second.json()["impact_graph"]
    assert first.json()["ui_state"] == second.json()["ui_state"]


def test_war_room_golden_scenario_contract():
    golden = json.loads((Path(__file__).parent / "golden" / "war_room_strait_blockade_v1.json").read_text(encoding="utf-8"))
    result = run_war_room(WarRoomScenarioRequest(**golden["scenario_input"]))
    actual = {
        "risk_heatmap": [[item.country_code, item.risk, item.dominant_channel] for item in result.risk_heatmap],
        "supply_chains": [[item.key, item.pressure_score, item.lag_days] for item in result.supply_chains],
        "timeline_global_risk": [[item.day, item.global_risk] for item in result.timeline],
        "graph": {
            "node_count": len(result.impact_graph.nodes),
            "edge_count": len(result.impact_graph.edges),
            "confidence": result.impact_graph.confidence,
        },
    }
    assert actual == {key: golden[key] for key in actual}


def test_energy_export_cut_prioritizes_energy_chain():
    client = TestClient(app)
    response = client.post(
        "/api/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
    )
    assert response.status_code == 200
    chains = response.json()["supply_chains"]
    energy = next(item for item in chains if item["key"] == "energy")
    assert energy["pressure_score"] >= 55
    assert any("energy" in item["rationale"].lower() for item in response.json()["agent_decisions"])


def test_policy_actions_and_overrides_change_explainable_outputs():
    client = TestClient(app)
    base = client.post(
        "/api/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
    ).json()
    changed = client.post(
        "/api/war-room/run",
        json={
            "scenario_key": "energy_export_cut",
            "duration_days": 30,
            "intensity": 0.8,
            "propagation": 0.55,
            "target_countries": ["EU", "JPN"],
            "target_chains": ["energy", "settlement"],
            "policy_actions": ["energy_reroute", "liquidity_support"],
            "country_overrides": {"JPN": {"energy_dependency": 100, "financial_stress": 60}},
            "chain_overrides": {"energy": {"substitution": 70, "lag_days": 2}},
        },
    ).json()

    base_energy = next(item for item in base["supply_chains"] if item["key"] == "energy")
    changed_energy = next(item for item in changed["supply_chains"] if item["key"] == "energy")
    base_settlement = next(item for item in base["supply_chains"] if item["key"] == "settlement")
    changed_settlement = next(item for item in changed["supply_chains"] if item["key"] == "settlement")

    assert changed["scenario"]["policy_actions"] == ["energy_reroute", "liquidity_support"]
    assert changed["scenario"]["target_countries"] == ["EU", "JPN"]
    assert changed_energy["pressure_score"] < base_energy["pressure_score"]
    assert changed_settlement["pressure_score"] < base_settlement["pressure_score"]
    assert any("Emergency energy reroute" in item for item in changed["assumptions"])
    assert changed["risk_heatmap"][0]["risk_breakdown"]["financial"] >= 0


def test_food_export_limit_raises_food_and_public_pressure():
    client = TestClient(app)
    base = client.post(
        "/api/war-room/run",
        json={"scenario_key": "food_shortfall", "duration_days": 45, "intensity": 0.72, "propagation": 0.5},
    ).json()
    changed = client.post(
        "/api/war-room/run",
        json={"scenario_key": "food_shortfall", "duration_days": 45, "intensity": 0.72, "propagation": 0.5, "policy_actions": ["food_export_limit"]},
    ).json()
    base_food = next(item for item in base["supply_chains"] if item["key"] == "food")
    changed_food = next(item for item in changed["supply_chains"] if item["key"] == "food")
    assert changed_food["pressure_score"] > base_food["pressure_score"]
    assert changed["timeline"][-1]["public_opinion_pressure"] > base["timeline"][-1]["public_opinion_pressure"]


def test_food_shortfall_transmits_to_food_and_stability():
    client = TestClient(app)
    response = client.post(
        "/api/war-room/run",
        json={"scenario_key": "food_shortfall", "duration_days": 45, "intensity": 0.72, "propagation": 0.5},
    )
    assert response.status_code == 200
    payload = response.json()
    food = next(item for item in payload["supply_chains"] if item["key"] == "food")
    assert food["pressure_score"] >= 50
    assert payload["timeline"][-1]["food_pressure"] > payload["timeline"][0]["food_pressure"]
    assert min(item["stability"] for item in payload["country_agents"]) < 75


def test_war_room_project_run_persists_in_research_loop(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "title": "War Room demo",
            "question": "某海峡封锁 30 天会怎样？",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d", "duration_days": 30, "intensity": 0.7, "propagation": 0.45},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    assert created.status_code == 200
    assert created.json()["mode"] == "war_room"

    project_id = created.json()["project_id"]
    run = client.post(f"/api/projects/{project_id}/war-room/run", json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.5})
    assert run.status_code == 200
    detail = run.json()
    assert detail["latest_run"]["data_snapshot"]["run_mode"] == "war_room"
    assert detail["latest_run"]["simulation_snapshot"]["agent_decisions"]
    assert detail["latest_run"]["simulation_snapshot"]["assumptions"]
    assert detail["latest_run"]["simulation_snapshot"]["ui_state"]["kpis"]
    assert detail["latest_run"]["simulation_snapshot"]["ui_state"]["timeline_events"][0]["related_countries"]
    assert detail["latest_run"]["simulation_snapshot"]["ui_state"]["agent_panels"]
    assert detail["graph"]["nodes"]
    assert detail["report"]["mode"] == "war-room-local"
    assert "策略沙盘" in detail["report"]["disclaimer"]


def test_war_room_workspace_returns_stable_empty_state(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={"title": "War Room empty workspace", "question": "No run yet", "mode": "war_room", "event_types": ["conflict"]},
    )
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    response = client.get(f"/api/projects/{project_id}/war-room/workspace")
    assert response.status_code == 200
    payload = response.json()
    assert payload["project_id"] == project_id
    assert payload["run_id"] is None
    assert payload["run_control"]["status_zh"]
    assert payload["entity_index"] == []
    assert payload["entity_details"] == {}
    assert payload["compare_ready"] is False
    assert payload["replay_ready"] is False
    assert "Not a prediction" in payload["disclaimer"]


def test_war_room_workspace_returns_command_index_and_details(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "title": "War Room workspace",
            "question": "Search and control",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    project_id = created.json()["project_id"]
    base = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
    ).json()
    target = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55, "policy_actions": ["energy_reroute", "liquidity_support"]},
    ).json()

    response = client.get(f"/api/projects/{project_id}/war-room/workspace", params={"run_id": target["latest_run"]["run_id"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == target["latest_run"]["run_id"]
    assert payload["run_control"]["current_run_id"] == target["latest_run"]["run_id"]
    assert payload["run_control"]["previous_run_id"] == base["latest_run"]["run_id"]
    assert payload["compare_ready"] is True
    assert payload["replay_ready"] is True
    assert payload["entity_index"]
    assert payload["entity_details"]
    assert payload["command_actions"]
    assert payload["insight_cards"]
    assert payload["ui_state"]["entity_index"]
    assert payload["ui_state"]["run_control"]["compare_ready"] is True
    assert any(item["type"] == "country" and item["section"] == "analysis" for item in payload["entity_index"])
    assert any(item["type"] == "timeline" for item in payload["entity_index"])
    assert any(action["key"] == "compare_runs" and action["enabled"] for action in payload["command_actions"])
    assert "country:CHN" in payload["entity_details"] or "country:TWN" in payload["entity_details"]
    assert "Not a prediction" in payload["disclaimer"]


def test_war_room_project_compare_returns_counterfactual_diff(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "title": "War Room compare",
            "question": "Compare policy actions",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    assert created.status_code == 200
    project_id = created.json()["project_id"]

    base = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
    ).json()
    target = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={
            "scenario_key": "energy_export_cut",
            "duration_days": 30,
            "intensity": 0.8,
            "propagation": 0.55,
            "policy_actions": ["energy_reroute", "liquidity_support"],
        },
    ).json()

    response = client.get(
        f"/api/projects/{project_id}/runs/compare",
        params={"base_run_id": base["latest_run"]["run_id"], "target_run_id": target["latest_run"]["run_id"]},
    )
    assert response.status_code == 200
    war_room = response.json()["changed_metrics"]["war_room"]
    assert war_room["disclaimer"]
    assert "energy_reroute" in war_room["target_policy_actions"]
    assert war_room["country_risk_delta"]
    assert war_room["supply_chain_delta"]
    assert war_room["agent_decision_changes"]
    assert war_room["timeline_delta"]["points"]
    assert war_room["causal_edge_delta"]

    energy = next(item for item in war_room["supply_chain_delta"] if item["key"] == "energy")
    settlement = next(item for item in war_room["supply_chain_delta"] if item["key"] == "settlement")
    assert energy["delta"] < 0
    assert settlement["delta"] < 0


def test_war_room_replay_pack_single_run(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "title": "War Room replay",
            "question": "Export one run",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "strait_blockade_30d", "duration_days": 30, "intensity": 0.7, "propagation": 0.45},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    project_id = created.json()["project_id"]
    run = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "strait_blockade_30d", "duration_days": 30, "intensity": 0.7, "propagation": 0.45},
    ).json()
    from app.services.project_app import service as project_service

    monkeypatch.setattr(project_service, "request_structured_analysis", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("Replay Pack must not call an LLM")))
    response = client.get(f"/api/projects/{project_id}/war-room/replay-pack", params={"run_id": run["latest_run"]["run_id"]})
    assert response.status_code == 200
    payload = response.json()
    assert payload["scenario"]
    assert payload["risk_heatmap"]
    assert payload["agent_decisions"]
    assert payload["assumptions"]
    assert payload["manifest"]["run_id"] == run["latest_run"]["run_id"]
    assert payload["manifest"]["is_counterfactual"] is False
    assert payload["model_inputs"]["duration_days"] == 30
    assert payload["model_outputs"]["risk_heatmap"]
    assert payload["audit_trail"]
    manifest = json.loads(payload["artifacts"]["json_manifest"])
    assert manifest["manifest"]["run_id"] == run["latest_run"]["run_id"]
    assert "Audit Trail" in payload["markdown"]
    assert "Model Inputs" in payload["markdown"]
    assert "Not a prediction" in payload["markdown"]
    assert "策略沙盘" in payload["markdown"]


def test_war_room_replay_pack_counterfactual_diff(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={
            "title": "War Room replay diff",
            "question": "Export diff",
            "mode": "war_room",
            "scenario_config": {"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
            "event_types": ["conflict", "energy", "trade"],
        },
    )
    project_id = created.json()["project_id"]
    base = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55},
    ).json()
    target = client.post(
        f"/api/projects/{project_id}/war-room/run",
        json={"scenario_key": "energy_export_cut", "duration_days": 30, "intensity": 0.8, "propagation": 0.55, "policy_actions": ["energy_reroute", "liquidity_support"]},
    ).json()
    response = client.get(
        f"/api/projects/{project_id}/war-room/replay-pack",
        params={"base_run_id": base["latest_run"]["run_id"], "target_run_id": target["latest_run"]["run_id"]},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["counterfactual_observations"]
    assert payload["supply_chain_delta"]
    assert payload["timeline_delta"]["points"]
    assert payload["manifest"]["is_counterfactual"] is True
    assert payload["manifest"]["base_run_id"] == base["latest_run"]["run_id"]
    assert payload["manifest"]["target_run_id"] == target["latest_run"]["run_id"]
    assert payload["model_outputs"]["diff_metrics"]["base_run_id"] == base["latest_run"]["run_id"]
    assert {"project_id", "run_id", "base_run_id", "target_run_id", "scenario", "risk_heatmap", "supply_chain_delta", "agent_decisions", "timeline", "timeline_delta", "impact_graph", "manifest", "model_inputs", "model_outputs", "audit_trail", "artifacts", "markdown", "disclaimer"}.issubset(payload)
    manifest = json.loads(payload["artifacts"]["json_manifest"])
    assert manifest["manifest"]["base_run_id"] == base["latest_run"]["run_id"]
    assert manifest["manifest"]["target_run_id"] == target["latest_run"]["run_id"]
    assert "Not a prediction" in payload["artifacts"]["json_manifest"]
    assert "策略沙盘" in payload["artifacts"]["json_manifest"]
    energy = next(item for item in payload["supply_chain_delta"] if item["key"] == "energy")
    settlement = next(item for item in payload["supply_chain_delta"] if item["key"] == "settlement")
    assert energy["delta"] < 0
    assert settlement["delta"] < 0
    assert "Counterfactual Observations" in payload["markdown"]
    assert "Not a prediction" in payload["disclaimer"]


def test_war_room_replay_pack_unknown_run_returns_404(monkeypatch, tmp_path):
    _setup_tmp_db(monkeypatch, tmp_path)
    client = TestClient(app)
    created = client.post(
        "/api/projects",
        json={"title": "War Room replay missing", "question": "Missing run", "mode": "war_room", "event_types": ["conflict"]},
    )
    project_id = created.json()["project_id"]
    response = client.get(f"/api/projects/{project_id}/war-room/replay-pack", params={"run_id": "missing"})
    assert response.status_code == 404
