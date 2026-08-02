from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from app.core.models import WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.simulation_kernel import (
    KernelEventLog,
    ReplayRequest,
    WarRoomShadowRun,
    build_war_room_shadow_run,
    project_war_room_run,
    simulation_kernel_service,
)
from app.services.simulation_kernel import event_log as kernel_event_log
from app.services.simulation_kernel import war_room_trace
from app.services.simulation_runtime import simulation_runtime_service
from app.services.world_model import world_model_service


RULE_PACK_HASH = "a" * 64
GOLDEN_FIXTURES = sorted(Path("tests/golden_scenarios").glob("*.json"))


def _result():
    return simulation_runtime_service.run_war_room(
        WarRoomScenarioRequest(scenario_key="strait_blockade_30d", seed=42)
    )


def _shadow(result=None):
    result = result or _result()
    return build_war_room_shadow_run(
        result,
        world_model_service.war_room_presets(),
        run_id="run_multi_tick_shadow",
        seed=42,
        rule_pack_hash=RULE_PACK_HASH,
    )


def test_multi_tick_event_log_replays_to_exact_final_projection():
    result = _result()
    presets = world_model_service.war_room_presets()
    shadow = build_war_room_shadow_run(
        result,
        presets,
        run_id="run_multi_tick_shadow",
        seed=42,
        rule_pack_hash=RULE_PACK_HASH,
    )
    final_state = project_war_room_run(
        result,
        run_id=shadow.initial_state.run_id,
        seed=shadow.initial_state.seed,
        rule_pack_hash=shadow.initial_state.rule_pack_hash,
    )
    replayed = simulation_kernel_service.replay_event_log(
        shadow.initial_state,
        shadow.event_log,
        ReplayRequest(checkpoint_id=shadow.checkpoints[0].checkpoint_id),
    )

    assert len(shadow.event_log.transitions) == len(result.timeline) - 1
    assert [item.event.sequence for item in shadow.event_log.transitions] == list(
        range(1, len(result.timeline))
    )
    assert [item.event.tick for item in shadow.event_log.transitions] == [
        point.day for point in result.timeline[1:]
    ]
    assert replayed.content_hash() == final_state.content_hash()
    assert shadow.event_log.final_state_hash == final_state.content_hash()
    assert shadow.checkpoints[-1].world_state.content_hash() == final_state.content_hash()

    expected_cursors = [0] + [
        index
        for index, point in enumerate(result.timeline[1:], start=1)
        if point.turning_point
    ]
    assert [item.event_cursor for item in shadow.checkpoints] == expected_cursors

    preset_usa = next(item for item in presets.countries if item.code == "USA")
    assert shadow.initial_state.entities["country:USA"].components["risk_score"] == preset_usa.risk_score
    assert all(
        not any(change.is_numeric_authority for change in transition.delta.changes)
        for transition in shadow.event_log.transitions[:-1]
    )
    assert {"risk_score", "supply_chain_pressure"} <= {
        change.component for change in shadow.event_log.transitions[-1].delta.changes
    }


def test_shadow_event_log_and_checkpoint_hashes_are_deterministic():
    result = _result()
    first = _shadow(result)
    second = _shadow(result)

    assert first.event_log.content_hash() == second.event_log.content_hash()
    assert first.content_hash() == second.content_hash()
    assert [item.checkpoint_id for item in first.checkpoints] == [
        item.checkpoint_id for item in second.checkpoints
    ]
    assert [item.content_hash() for item in first.checkpoints] == [
        item.content_hash() for item in second.checkpoints
    ]


@pytest.mark.parametrize("fixture_path", GOLDEN_FIXTURES, ids=lambda path: path.stem)
def test_all_golden_runs_build_provider_free_replayable_event_logs(fixture_path: Path):
    record = json.loads(fixture_path.read_text(encoding="utf-8"))
    request = WarRoomScenarioRequest(**record["scenario"])
    result = simulation_runtime_service.run_war_room(request)
    assert stable_hash(result.model_dump(mode="json")) == record["baseline_hash"]

    shadow = build_war_room_shadow_run(
        result,
        world_model_service.war_room_presets(),
        run_id=f"event_log:{fixture_path.stem}",
        seed=record["scenario"]["seed"],
        rule_pack_hash=RULE_PACK_HASH,
    )
    replayed = simulation_kernel_service.replay_event_log(
        shadow.initial_state,
        shadow.event_log,
        ReplayRequest(checkpoint_id=shadow.checkpoints[0].checkpoint_id),
    )
    assert replayed.content_hash() == shadow.event_log.final_state_hash


def test_shadow_chain_fails_closed_on_source_and_chain_ambiguity():
    result = _result()
    presets = world_model_service.war_room_presets()
    invalid_day_zero = result.model_copy(
        update={
            "timeline": [
                result.timeline[0].model_copy(update={"day": 1}),
                *result.timeline[1:],
            ]
        }
    )
    with pytest.raises(ValueError, match="day-zero"):
        build_war_room_shadow_run(
            invalid_day_zero,
            presets,
            run_id="run_invalid_day_zero",
            seed=42,
            rule_pack_hash=RULE_PACK_HASH,
        )

    missing_country = presets.model_copy(update={"countries": presets.countries[1:]})
    with pytest.raises(ValueError, match="country topology mismatch"):
        build_war_room_shadow_run(
            result,
            missing_country,
            run_id="run_invalid_topology",
            seed=42,
            rule_pack_hash=RULE_PACK_HASH,
        )

    shadow = _shadow(result)
    first_transition = shadow.event_log.transitions[0]
    sequence_gap = first_transition.model_copy(
        update={"event": first_transition.event.model_copy(update={"sequence": 2})}
    )
    with pytest.raises(ValueError, match="sequence must be contiguous"):
        KernelEventLog(
            run_id=shadow.event_log.run_id,
            initial_state_hash=shadow.event_log.initial_state_hash,
            final_state_hash=shadow.event_log.final_state_hash,
            transitions=(sequence_gap, *shadow.event_log.transitions[1:]),
        )

    with pytest.raises(ValueError, match="full stored event range"):
        simulation_kernel_service.replay_event_log(
            shadow.initial_state,
            shadow.event_log,
            ReplayRequest(
                checkpoint_id=shadow.checkpoints[0].checkpoint_id,
                event_end=1,
            ),
        )

    invalid_checkpoint = shadow.checkpoints[1].model_copy(
        update={"parent_checkpoint_hash": "b" * 64}
    )
    with pytest.raises(ValueError, match="checkpoint parent hash mismatch"):
        WarRoomShadowRun(
            initial_state=shadow.initial_state,
            event_log=shadow.event_log,
            checkpoints=(
                shadow.checkpoints[0],
                invalid_checkpoint,
                *shadow.checkpoints[2:],
            ),
        )


def test_shadow_builder_is_provider_and_storage_free_with_spy(monkeypatch):
    import app.services.agent_runtime as agent_runtime

    def forbidden_provider_call(*args, **kwargs):
        raise AssertionError("Agent Provider must not be called by Kernel shadow replay")

    monkeypatch.setattr(agent_runtime, "run_agent_runtime", forbidden_provider_call)
    shadow = _shadow()
    replayed = simulation_kernel_service.replay_event_log(
        shadow.initial_state,
        shadow.event_log,
        ReplayRequest(checkpoint_id=shadow.checkpoints[0].checkpoint_id),
    )
    assert replayed.content_hash() == shadow.event_log.final_state_hash

    imported_modules: set[str] = set()
    for module in (war_room_trace, kernel_event_log):
        tree = ast.parse(inspect.getsource(module))
        imported_modules.update(
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        imported_modules.update(
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
    assert not imported_modules & {
        "app.services.agent_runtime",
        "app.services.project_store",
        "requests",
        "httpx",
    }
