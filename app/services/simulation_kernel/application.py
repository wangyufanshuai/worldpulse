"""Pure application port for Kernel V2 contract operations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .branching import branch_world_state
from .contracts import Checkpoint, EventEnvelope, ExperimentBranch, ReplayRequest, StateDelta, WorldState
from .replay import replay_state
from .transitions import CompiledTransition, compile_deterministic_transition


class SimulationKernelApplicationPort(Protocol):
    def compile_transition(
        self,
        source_state: WorldState,
        target_state: WorldState,
        *,
        event_id: str,
        sequence: int,
        reducer_version: str,
        event_type: str = "deterministic_state_transition",
    ) -> CompiledTransition: ...

    def apply_delta(self, state: WorldState, delta: StateDelta) -> WorldState: ...

    def replay(
        self,
        initial_state: WorldState,
        transitions: Sequence[tuple[EventEnvelope, StateDelta]],
        request: ReplayRequest,
    ) -> WorldState: ...

    def branch(self, checkpoint: Checkpoint, branch: ExperimentBranch) -> WorldState: ...


class SimulationKernelApplicationService:
    def compile_transition(
        self,
        source_state: WorldState,
        target_state: WorldState,
        *,
        event_id: str,
        sequence: int,
        reducer_version: str,
        event_type: str = "deterministic_state_transition",
    ) -> CompiledTransition:
        return compile_deterministic_transition(
            source_state,
            target_state,
            event_id=event_id,
            sequence=sequence,
            reducer_version=reducer_version,
            event_type=event_type,
        )

    def apply_delta(self, state: WorldState, delta: StateDelta) -> WorldState:
        return state.apply_delta(delta)

    def replay(
        self,
        initial_state: WorldState,
        transitions: Sequence[tuple[EventEnvelope, StateDelta]],
        request: ReplayRequest,
    ) -> WorldState:
        return replay_state(initial_state, transitions, request)

    def branch(self, checkpoint: Checkpoint, branch: ExperimentBranch) -> WorldState:
        return branch_world_state(checkpoint, branch)


simulation_kernel_service: SimulationKernelApplicationPort = SimulationKernelApplicationService()
