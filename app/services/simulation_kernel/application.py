"""Pure application port for Kernel V2 contract operations."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .branching import branch_world_state
from .contracts import Checkpoint, EventEnvelope, ExperimentBranch, ReplayRequest, StateDelta, WorldState
from .replay import replay_state


class SimulationKernelApplicationPort(Protocol):
    def apply_delta(self, state: WorldState, delta: StateDelta) -> WorldState: ...

    def replay(
        self,
        initial_state: WorldState,
        transitions: Sequence[tuple[EventEnvelope, StateDelta]],
        request: ReplayRequest,
    ) -> WorldState: ...

    def branch(self, checkpoint: Checkpoint, branch: ExperimentBranch) -> WorldState: ...


class SimulationKernelApplicationService:
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
