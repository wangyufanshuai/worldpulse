from __future__ import annotations

import inspect
import time

import pytest

from app.services.simulation_kernel import (
    Checkpoint,
    DeterministicClock,
    Entity,
    EventEnvelope,
    ExperimentBranch,
    ReplayIntegrityError,
    ReplayRequest,
    StateChange,
    StateDelta,
    WorldState,
    branch_world_state,
    replay_state,
    SimulationKernelApplicationPort,
    simulation_kernel_service,
)
from app.services.simulation_kernel import contracts as kernel_contracts


def _initial_state() -> WorldState:
    return WorldState(
        run_id="run_kernel_1",
        seed=17,
        rule_pack_hash="a" * 64,
        entities={
            "country:USA": Entity(
                entity_id="country:USA",
                entity_type="country",
                components={"sentiment_pressure": 32, "risk_score": 41},
            )
        },
    )


def _delta(state: WorldState, *, tick: int = 1) -> StateDelta:
    return StateDelta(
        run_id=state.run_id,
        tick=tick,
        parent_state_hash=state.content_hash(),
        reducer_version="deterministic-test.v1",
        source="deterministic_reducer",
        changes=(StateChange(entity_id="country:USA", component="sentiment_pressure", value=37),),
    )


def test_deterministic_clock_is_monotonic_and_phase_aware():
    clock = DeterministicClock()
    assert clock.advance(tick=0, phase="shock") == DeterministicClock(tick=0, phase="shock")
    assert clock.advance(tick=1, phase="assessment").tick == 1
    with pytest.raises(ValueError, match="cannot move backwards"):
        clock.advance(tick=-1, phase="invalid")
    with pytest.raises(ValueError, match="must change"):
        DeterministicClock(tick=1, phase="assessment").advance(tick=1, phase="assessment")


def test_world_state_and_delta_hashes_are_canonical():
    first = _initial_state()
    second = WorldState(
        run_id=first.run_id,
        seed=first.seed,
        rule_pack_hash=first.rule_pack_hash,
        entities=dict(reversed(list(first.entities.items()))),
    )
    assert first.content_hash() == second.content_hash()
    assert _delta(first).content_hash() == _delta(second).content_hash()


def test_agent_and_action_adapter_numeric_writes_fail_closed():
    state = _initial_state()
    with pytest.raises(ValueError, match="Only deterministic reducers"):
        StateDelta(
            run_id=state.run_id,
            tick=1,
            parent_state_hash=state.content_hash(),
            reducer_version="agent-observation.v1",
            source="agent_observation",
            changes=(StateChange(entity_id="country:USA", component="risk_score", value=99),),
        )
    with pytest.raises(ValueError, match="Only deterministic reducers"):
        StateDelta(
            run_id=state.run_id,
            tick=1,
            parent_state_hash=state.content_hash(),
            reducer_version="action-adapter.v1",
            source="action_adapter",
            changes=(StateChange(entity_id="country:USA", component="risk_score", value=99),),
        )


def test_provider_free_replay_verifies_event_and_state_hashes():
    initial = _initial_state()
    delta = _delta(initial)
    final = initial.apply_delta(delta)
    event = EventEnvelope(
        event_id="evt_kernel_1",
        sequence=1,
        tick=1,
        event_type="state_delta_applied",
        input_state_hash=initial.content_hash(),
        output_state_hash=final.content_hash(),
        delta_hash=delta.content_hash(),
    )
    replayed = replay_state(initial, [(event, delta)], ReplayRequest(checkpoint_id="cp_1"))
    assert replayed.content_hash() == final.content_hash()

    tampered = event.model_copy(update={"output_state_hash": "b" * 64})
    with pytest.raises(ReplayIntegrityError, match="output hash mismatch"):
        replay_state(initial, [(tampered, delta)], ReplayRequest(checkpoint_id="cp_1"))
    with pytest.raises(ValueError, match="stored_only"):
        ReplayRequest(checkpoint_id="cp_1", provider_policy="provider_allowed")


def test_checkpoint_branch_does_not_mutate_parent():
    initial = _initial_state()
    checkpoint = Checkpoint(
        checkpoint_id="cp_1",
        branch_id="main",
        event_cursor=0,
        world_state=initial,
    )
    branch = ExperimentBranch(
        branch_id="treated-1",
        parent_checkpoint_hash=checkpoint.content_hash(),
        treatment="treated",
        seed=23,
        scenario_diff={"intensity": 0.8},
    )
    branched = branch_world_state(checkpoint, branch)
    assert branched.run_id == "run_kernel_1:treated-1"
    assert branched.seed == 23
    assert checkpoint.world_state.content_hash() == initial.content_hash()
    assert branched.content_hash() != initial.content_hash()


def test_kernel_contracts_are_provider_and_storage_free():
    source = inspect.getsource(kernel_contracts)
    assert "agent_runtime" not in source
    assert "project_store" not in source
    assert "requests" not in source


def test_kernel_application_port_is_pure_and_public():
    port: SimulationKernelApplicationPort = simulation_kernel_service
    state = _initial_state()
    delta = _delta(state)
    assert port.apply_delta(state, delta).tick == 1
    assert callable(port.replay)
    assert callable(port.branch)


def test_kernel_hash_contract_has_a_small_local_budget():
    state = _initial_state()
    started = time.perf_counter()
    for _ in range(1000):
        state.content_hash()
    assert time.perf_counter() - started < 2.0
