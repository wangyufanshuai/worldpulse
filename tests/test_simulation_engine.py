from fastapi.testclient import TestClient

from app.core.models import PolicyShock, SimulationRequest
from app.main import app
from app.services.simulation_engine import list_agents, list_scenarios, run_simulation
from app.services.simulation_health import build_simulation_data_health


def test_agents_cover_g20_plus_regions():
    agents = list_agents()
    codes = {agent.code for agent in agents}
    assert len(agents) >= 26
    assert {"USA", "CHN", "EU", "RUS", "IND", "SAU", "UKR", "ISR", "VNM", "TWN"}.issubset(codes)
    assert all(0 <= agent.risk_score <= 100 for agent in agents)
    assert all(0 <= agent.data_quality_score <= 100 for agent in agents)
    assert all(agent.source_breakdown for agent in agents)


def test_simulation_quantiles_are_ordered():
    request = SimulationRequest(
        shocks=[PolicyShock(shock_type="energy", target_codes=["EU", "JPN", "KOR"], intensity=0.5, duration_months=6, propagation=0.35)],
        runs=80,
        horizon_months=12,
        seed=7,
    )
    result = run_simulation(request)
    assert len(result.global_path) == 13
    assert result.countries
    assert result.map_points
    assert result.propagation_edges
    for point in result.global_path:
        assert point.p10 <= point.p50 <= point.p90


def test_energy_shock_hits_import_vulnerable_economies():
    result = run_simulation(
        SimulationRequest(
            shocks=[PolicyShock(shock_type="energy", target_codes=["JPN", "KOR", "EU"], intensity=0.7, duration_months=8, propagation=0.3)],
            runs=80,
            horizon_months=12,
            seed=11,
        )
    )
    top_codes = {country.code for country in result.countries[:6]}
    assert {"JPN", "KOR"} & top_codes


def test_tariff_shock_hits_trade_open_economies():
    result = run_simulation(
        SimulationRequest(
            shocks=[PolicyShock(shock_type="tariff", target_codes=["VNM", "SGP", "KOR", "TWN"], intensity=0.65, duration_months=7, propagation=0.35)],
            runs=80,
            horizon_months=12,
            seed=13,
        )
    )
    top_codes = {country.code for country in result.countries[:8]}
    assert {"VNM", "SGP", "KOR", "TWN"} & top_codes


def test_simulation_data_health_reports_fallbacks():
    health = build_simulation_data_health()
    assert health
    assert any(item.agent_count >= 26 for item in health)
    assert all(item.note for item in health)


def test_simulation_api_contracts():
    client = TestClient(app)
    agents = client.get("/api/simulation/agents")
    scenarios = client.get("/api/simulation/scenarios")
    run = client.post(
        "/api/simulation/run",
        json={"shocks": [list_scenarios()[0].shocks[0].model_dump()], "horizon_months": 12, "runs": 60, "seed": 3},
    )
    detail = client.get("/api/simulation/agent/USA")
    health = client.get("/api/simulation/data-health")
    assert agents.status_code == 200
    assert scenarios.status_code == 200
    assert run.status_code == 200
    assert detail.status_code == 200
    assert health.status_code == 200
    assert run.json()["global_path"]
    assert "raw_indicators" in detail.json()
