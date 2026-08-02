from __future__ import annotations

import inspect
import time

import pytest

from app.services.simulation_kernel import (
    Checkpoint,
    CompiledTransition,
    DeterministicClock,
    Entity,
    EventEnvelope,
    ExperimentBranch,
    ReplayIntegrityError,
    ReplayRequest,
    StateChange,
    StateDelta,
    TransitionIntegrityError,
    WorldState,
    branch_world_state,
    compile_deterministic_transition,
    replay_state,
    SimulationKernelApplicationPort,
    simulation_kernel_service,
)
from app.services.simulation_kernel import contracts as kernel_contracts
from app.services.simulation_kernel import transitions as kernel_transitions


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


def test_world_state_rejects_cross_run_delta_even_with_valid_parent_hash():
    state = _initial_state()
    foreign_delta = _delta(state).model_copy(update={"run_id": "run_kernel_foreign"})
    with pytest.raises(ValueError, match="run id does not match"):
        state.apply_delta(foreign_delta)


def test_kernel_contracts_are_deeply_immutable_and_keep_plain_json_dumps():
    state = WorldState(
        run_id="run_immutable",
        seed=9,
        rule_pack_hash="c" * 64,
        entities={
            "country:USA": Entity(
                entity_id="country:USA",
                entity_type="country",
                components={"nested": {"values": [1, {"label": "stable"}]}},
            )
        },
    )
    before = state.model_dump(mode="json")
    before_hash = state.content_hash()

    with pytest.raises(TypeError, match="mappings are immutable"):
        state.entities["country:NEW"] = state.entities["country:USA"]
    with pytest.raises(TypeError, match="sequences are immutable"):
        state.entities["country:USA"].components["nested"]["values"].append(2)
    with pytest.raises(TypeError, match="mappings are immutable"):
        state.entities["country:USA"].components["nested"]["values"][1]["label"] = "changed"

    dumped = state.model_dump(mode="json")
    assert dumped == before
    assert type(dumped["entities"]) is dict
    assert type(dumped["entities"]["country:USA"]["components"]["nested"]["values"]) is list
    assert state.content_hash() == before_hash


def test_hash_memoization_is_private_and_updated_copies_get_fresh_hashes(monkeypatch):
    calls = 0
    original_stable_hash = kernel_contracts.stable_hash

    def counted_stable_hash(value):
        nonlocal calls
        calls += 1
        return original_stable_hash(value)

    monkeypatch.setattr(kernel_contracts, "stable_hash", counted_stable_hash)
    state = _initial_state()
    original_hash = state.content_hash()
    assert state.content_hash() == original_hash
    assert calls == 1
    assert "_hash_cache" not in state.model_dump(mode="json")

    advanced = state.model_copy(update={"tick": 1})
    assert advanced.content_hash() != original_hash
    assert advanced.content_hash() == advanced.content_hash()
    assert calls == 2


def test_apply_delta_structurally_shares_only_unchanged_immutable_entities():
    initial = _initial_state()
    observer = Entity(
        entity_id="country:CAN",
        entity_type="country",
        components={"risk_score": 12, "notes": ["unchanged"]},
    )
    state = initial.model_copy(
        update={"entities": {**initial.entities, observer.entity_id: observer}}
    )
    parent_hash = state.content_hash()
    delta = StateDelta(
        run_id=state.run_id,
        tick=1,
        parent_state_hash=parent_hash,
        reducer_version="structural-sharing-test.v1",
        source="deterministic_reducer",
        changes=(
            StateChange(
                entity_id="country:USA",
                component="sentiment_pressure",
                value=37,
            ),
        ),
    )
    updated = state.apply_delta(delta)

    assert updated.entities[observer.entity_id] is state.entities[observer.entity_id]
    assert updated.entities["country:USA"] is not state.entities["country:USA"]
    assert state.content_hash() == parent_hash
    assert updated.content_hash() != parent_hash


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


def test_transition_compiler_builds_canonical_delta_event_and_replay():
    initial = _initial_state()
    target_entity = initial.entities["country:USA"].model_copy(
        update={"components": {"sentiment_pressure": 37, "risk_score": 45}}
    )
    target = initial.model_copy(update={"tick": 1, "entities": {"country:USA": target_entity}})

    compiled: CompiledTransition = compile_deterministic_transition(
        initial,
        target,
        event_id="evt_compiled_1",
        sequence=1,
        reducer_version="deterministic-compiler-test.v1",
    )
    assert [(change.entity_id, change.component) for change in compiled.delta.changes] == [
        ("country:USA", "risk_score"),
        ("country:USA", "sentiment_pressure"),
    ]
    assert compiled.event.delta_hash == compiled.delta.content_hash()
    assert compiled.event.output_state_hash == target.content_hash()
    replayed = replay_state(
        initial,
        [(compiled.event, compiled.delta)],
        ReplayRequest(checkpoint_id="cp_compiled_1"),
    )
    assert replayed.content_hash() == target.content_hash()


def test_transition_compiler_supports_hash_verified_no_op_ticks():
    initial = _initial_state()
    advanced = initial.model_copy(update={"tick": 1})
    compiled = compile_deterministic_transition(
        initial,
        advanced,
        event_id="evt_no_op",
        sequence=1,
        reducer_version="deterministic-compiler-test.v1",
    )
    assert compiled.delta.changes == ()
    assert initial.apply_delta(compiled.delta).content_hash() == advanced.content_hash()


def test_transition_compiler_fails_closed_on_metadata_and_topology_ambiguity():
    initial = _initial_state()
    advanced = initial.model_copy(update={"tick": 1})

    with pytest.raises(TransitionIntegrityError, match="seed mismatch"):
        compile_deterministic_transition(
            initial,
            advanced.model_copy(update={"seed": 18}),
            event_id="evt_seed",
            sequence=1,
            reducer_version="deterministic-compiler-test.v1",
        )

    removed_component = initial.entities["country:USA"].model_copy(
        update={"components": {"risk_score": 41}}
    )
    with pytest.raises(TransitionIntegrityError, match="cannot remove components"):
        compile_deterministic_transition(
            initial,
            advanced.model_copy(update={"entities": {"country:USA": removed_component}}),
            event_id="evt_removed",
            sequence=1,
            reducer_version="deterministic-compiler-test.v1",
        )

    with pytest.raises(TransitionIntegrityError, match="entity topology mismatch"):
        compile_deterministic_transition(
            initial,
            advanced.model_copy(update={"entities": {}}),
            event_id="evt_topology",
            sequence=1,
            reducer_version="deterministic-compiler-test.v1",
        )

    changed_type = initial.entities["country:USA"].model_copy(update={"entity_type": "organization"})
    with pytest.raises(TransitionIntegrityError, match="entity type mismatch"):
        compile_deterministic_transition(
            initial,
            advanced.model_copy(update={"entities": {"country:USA": changed_type}}),
            event_id="evt_entity_type",
            sequence=1,
            reducer_version="deterministic-compiler-test.v1",
        )


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

    transition_source = inspect.getsource(kernel_transitions)
    assert "agent_runtime" not in transition_source
    assert "project_store" not in transition_source
    assert "requests" not in transition_source


def test_kernel_application_port_is_pure_and_public():
    port: SimulationKernelApplicationPort = simulation_kernel_service
    state = _initial_state()
    delta = _delta(state)
    assert port.apply_delta(state, delta).tick == 1
    assert callable(port.replay)
    assert callable(port.branch)
    assert callable(port.compile_transition)


def test_kernel_hash_contract_has_a_small_local_budget():
    state = _initial_state()
    started = time.perf_counter()
    for _ in range(1000):
        state.content_hash()
    assert time.perf_counter() - started < 2.0
