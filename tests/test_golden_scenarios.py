from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.models import WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.war_room_engine import run_war_room


FIXTURES = sorted(Path("tests/golden_scenarios").glob("*.json"))


def test_golden_fixture_corpus_has_ten_versioned_scenarios():
    assert len(FIXTURES) >= 10
    records = [json.loads(path.read_text(encoding="utf-8")) for path in FIXTURES]
    assert len({record["name"] for record in records}) == len(records)
    assert all(record["rule_set_version"] for record in records)
    assert all(record["agent_proposals"].keys() >= {"accepted", "rejected"} for record in records)


@pytest.mark.parametrize("fixture_path", FIXTURES, ids=lambda path: path.stem)
def test_golden_scenario_hashes_and_turning_points(fixture_path):
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = WarRoomScenarioRequest(**record["scenario"])
    result = run_war_room(request)
    payload = result.model_dump(mode="json")
    assert stable_hash(payload) == record["baseline_hash"]
    assert record["final_hash"] == record["baseline_hash"]
    top_countries = sorted(result.country_agents, key=lambda item: item.risk_score, reverse=True)[:3]
    assert [{"country_code": item.code, "risk": item.risk_score} for item in top_countries] == record["top_risk_countries"]
    top_chains = sorted(result.supply_chains, key=lambda item: item.pressure_score, reverse=True)[:3]
    assert [{"key": item.key, "pressure": item.pressure_score} for item in top_chains] == record["top_supply_chains"]
    turning_points = [item for item in result.timeline if item.turning_point]
    assert [item.day for item in turning_points] == [item["day"] for item in record["timeline_turning_points"]]
    assert all(item["global_risk"] == turning.global_risk for item, turning in zip(record["timeline_turning_points"], turning_points, strict=False))


def test_sensitivity_intensity_propagation_duration_and_policy_are_directional():
    base = WarRoomScenarioRequest(scenario_key="strait_blockade_30d", duration_days=30, intensity=0.4, propagation=0.3, seed=42)
    high_intensity = base.model_copy(update={"intensity": 0.8})
    high_propagation = base.model_copy(update={"propagation": 0.7})
    long_duration = base.model_copy(update={"duration_days": 60})
    sanctioned = base.model_copy(update={"policy_actions": ["sanctions"]})
    base_result = run_war_room(base)
    assert run_war_room(high_intensity).timeline[-1].global_risk >= base_result.timeline[-1].global_risk
    assert run_war_room(high_propagation).timeline[-1].global_risk >= base_result.timeline[-1].global_risk
    assert run_war_room(long_duration).timeline[-1].global_risk >= base_result.timeline[-1].global_risk
    assert run_war_room(sanctioned).timeline[-1].global_risk >= base_result.timeline[-1].global_risk


def test_sensitivity_chain_substitution_and_lag_are_explicit():
    low_substitution = WarRoomScenarioRequest(
        scenario_key="strait_blockade_30d", target_chains=["chips"],
        chain_overrides={"chips": {"substitution": 5, "lag_days": 30}}, seed=42,
    )
    high_substitution = low_substitution.model_copy(update={"chain_overrides": {"chips": {"substitution": 80, "lag_days": 3}}})
    low_pressure = run_war_room(high_substitution).supply_chains
    high_pressure = run_war_room(low_substitution).supply_chains
    low_value = next(item.pressure_score for item in low_pressure if item.key == "chips")
    high_value = next(item.pressure_score for item in high_pressure if item.key == "chips")
    assert high_value >= low_value
