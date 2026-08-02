from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from app.core.models import WarRoomRun, WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.simulation_kernel import (
    Checkpoint,
    EventEnvelope,
    ReplayRequest,
    StateChange,
    StateDelta,
    build_war_room_projection,
    project_war_room_run,
    replay_state,
)
from app.services.simulation_kernel import war_room_projection
from app.services.war_room_engine import run_war_room


RULE_PACK_HASH = "a" * 64


def _result() -> WarRoomRun:
    return run_war_room(WarRoomScenarioRequest(scenario_key="strait_blockade_30d", seed=42))


def test_projection_is_stable_and_canonical_for_reordered_v1_lists():
    result = _result()
    source_before = result.model_dump(mode="json")
    first_projection = build_war_room_projection(
        result,
        run_id="run_projection",
        seed=42,
        rule_pack_hash=RULE_PACK_HASH,
    )
    reordered = result.model_copy(
        update={
            "country_agents": list(reversed(result.country_agents)),
            "supply_chains": list(reversed(result.supply_chains)),
        }
    )
    second_projection = build_war_room_projection(
        reordered,
        run_id="run_projection",
        seed=42,
        rule_pack_hash=RULE_PACK_HASH,
    )
    first = first_projection.world_state
    second = second_projection.world_state
    assert first.content_hash() == second.content_hash()
    assert first_projection.deterministic_source_hash == second_projection.deterministic_source_hash
    assert list(first.entities) == sorted(first.entities)
    assert first.tick == result.timeline[-1].day
    assert result.model_dump(mode="json") == source_before


def test_projection_pins_run_seed_and_rule_pack_without_storage_or_provider():
    result = _result()
    with pytest.raises(ValueError, match="run_id"):
        project_war_room_run(result, run_id="", seed=42, rule_pack_hash=RULE_PACK_HASH)
    with pytest.raises(ValueError, match="rule_pack_hash"):
        project_war_room_run(result, run_id="run_projection", seed=42, rule_pack_hash="")
    with pytest.raises(ValueError, match="SHA-256"):
        project_war_room_run(result, run_id="run_projection", seed=42, rule_pack_hash="not-a-hash")

    tree = ast.parse(inspect.getsource(war_room_projection))
    imported_names = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported_from = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not imported_names & {"requests", "httpx"}
    assert not {"app.services.project_store", "app.services.agent_runtime"} & imported_from
    source = inspect.getsource(war_room_projection)
    assert "active_rule_pack" not in source
    assert "run_war_room(" not in source


def test_projection_fails_closed_on_ambiguous_v1_entities():
    result = _result()
    duplicate_country = result.model_copy(
        update={"country_agents": [*result.country_agents, result.country_agents[0]]}
    )
    with pytest.raises(ValueError, match="unique country codes"):
        project_war_room_run(
            duplicate_country,
            run_id="run_duplicate",
            seed=42,
            rule_pack_hash=RULE_PACK_HASH,
        )


@pytest.mark.parametrize("fixture_path", [Path("tests/golden_scenarios/01_strait_baseline.json")])
def test_projection_keeps_golden_scenario_output_unchanged(fixture_path: Path):
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    result = run_war_room(WarRoomScenarioRequest(**record["scenario"]))
    assert stable_hash(result.model_dump(mode="json")) == record["baseline_hash"]

    projection = build_war_room_projection(
        result,
        run_id="golden_projection_01",
        seed=record["scenario"]["seed"],
        rule_pack_hash=RULE_PACK_HASH,
    )
    state = projection.world_state
    assert projection.source_run_hash == record["baseline_hash"]
    assert projection.world_state_hash == state.content_hash()
    assert len(projection.deterministic_source_hash) == 64
    taiwan = state.entities["country:TWN"]
    chips = state.entities["supply_chain:chips"]
    assert taiwan.components["risk_score"] == 96.0
    assert chips.components["supply_chain_pressure"] == 69.6
    assert state.entities["scenario:strait_blockade_30d"].components["scenario_config"] == result.scenario.model_dump(mode="json")


def test_numeric_authority_components_are_explicitly_deterministic():
    result = _result()
    state = project_war_room_run(result, run_id="run_authority", seed=42, rule_pack_hash=RULE_PACK_HASH)
    country = state.entities["country:USA"]
    chain = state.entities["supply_chain:energy"]
    source_country = next(item for item in result.country_agents if item.code == "USA")
    source_chain = next(item for item in result.supply_chains if item.key == "energy")

    assert country.components["risk_score"] == source_country.risk_score
    assert country.components["authority_provenance"] == {
        "owner": "war_room.deterministic_rule_engine",
        "source_field": "WarRoomCountryAgent.risk_score",
        "components": ["risk_score"],
    }
    assert chain.components["supply_chain_pressure"] == source_chain.pressure_score
    assert chain.components["authority_provenance"]["owner"] == "war_room.deterministic_rule_engine"
    assert all("agent_decisions" not in entity.components for entity in state.entities.values())


def test_projected_world_state_round_trips_through_checkpoint_and_provider_free_replay():
    initial = project_war_room_run(_result(), run_id="run_replay_projection", seed=42, rule_pack_hash=RULE_PACK_HASH)
    checkpoint = Checkpoint(
        checkpoint_id="cp_projection",
        branch_id="main",
        event_cursor=0,
        world_state=initial,
    )
    delta = StateDelta(
        run_id=initial.run_id,
        tick=initial.tick + 1,
        parent_state_hash=initial.content_hash(),
        reducer_version="projection-test-reducer.v1",
        source="deterministic_reducer",
        changes=(StateChange(entity_id="scenario:strait_blockade_30d", component="replay_marker", value=True),),
    )
    final = initial.apply_delta(delta)
    event = EventEnvelope(
        event_id="evt_projection",
        sequence=1,
        tick=delta.tick,
        event_type="state_delta_applied",
        input_state_hash=initial.content_hash(),
        output_state_hash=final.content_hash(),
        delta_hash=delta.content_hash(),
    )
    replayed = replay_state(initial, [(event, delta)], ReplayRequest(checkpoint_id=checkpoint.checkpoint_id))

    assert checkpoint.world_state.content_hash() == initial.content_hash()
    assert replayed.content_hash() == final.content_hash()
    assert replayed.entities["scenario:strait_blockade_30d"].components["replay_marker"] is True
