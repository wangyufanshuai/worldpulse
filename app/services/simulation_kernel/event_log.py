"""Hash-linked append-only Event Log and provider-free replay helpers."""

from __future__ import annotations

from pydantic import Field, model_validator

from .contracts import EventEnvelope, KernelContract, ReplayRequest, StateDelta, WorldState
from .replay import ReplayIntegrityError, replay_state
from .transitions import CompiledTransition


class KernelEventLog(KernelContract):
    """A contiguous deterministic chain of compiled Kernel transitions."""

    schema_version: str = "kernel-event-log.v1"
    run_id: str = Field(min_length=1, max_length=160)
    initial_state_hash: str = Field(min_length=64, max_length=128)
    final_state_hash: str = Field(min_length=64, max_length=128)
    transitions: tuple[CompiledTransition, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def verify_chain(self) -> KernelEventLog:
        previous_state_hash = self.initial_state_hash
        previous_tick = -1
        for expected_sequence, transition in enumerate(self.transitions, start=1):
            event = transition.event
            delta = transition.delta
            if event.sequence != expected_sequence:
                raise ValueError("Kernel Event Log sequence must be contiguous")
            if delta.run_id != self.run_id:
                raise ValueError("Kernel Event Log run id mismatch")
            if event.input_state_hash != previous_state_hash:
                raise ValueError("Kernel Event Log state hash chain mismatch")
            if event.output_state_hash == event.input_state_hash and delta.changes:
                raise ValueError("Kernel Event Log changed Delta cannot retain the input state hash")
            if event.delta_hash != delta.content_hash():
                raise ValueError("Kernel Event Log delta hash mismatch")
            if event.tick <= previous_tick:
                raise ValueError("Kernel Event Log ticks must be strictly increasing")
            previous_state_hash = event.output_state_hash
            previous_tick = event.tick
        if previous_state_hash != self.final_state_hash:
            raise ValueError("Kernel Event Log final state hash mismatch")
        return self

    def replay_pairs(self) -> tuple[tuple[EventEnvelope, StateDelta], ...]:
        return tuple((item.event, item.delta) for item in self.transitions)

    def content_hash(self) -> str:
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


def replay_event_log(
    initial_state: WorldState,
    event_log: KernelEventLog,
    request: ReplayRequest,
) -> WorldState:
    if request.event_start != 1 or request.event_end not in {None, len(event_log.transitions)}:
        raise ReplayIntegrityError("Kernel Event Log replay requires the full stored event range")
    if initial_state.run_id != event_log.run_id:
        raise ReplayIntegrityError("Kernel Event Log initial run id mismatch")
    if initial_state.content_hash() != event_log.initial_state_hash:
        raise ReplayIntegrityError("Kernel Event Log initial state hash mismatch")
    replayed = replay_state(initial_state, event_log.replay_pairs(), request)
    if replayed.content_hash() != event_log.final_state_hash:
        raise ReplayIntegrityError("Kernel Event Log replay final state hash mismatch")
    return replayed
