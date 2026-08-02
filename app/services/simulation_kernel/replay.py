"""Provider-free replay adapter for Kernel V2 contracts."""

from __future__ import annotations

from collections.abc import Sequence

from .contracts import EventEnvelope, ReplayRequest, StateDelta, WorldState


class ReplayIntegrityError(ValueError):
    """Raised when stored Kernel inputs cannot be replayed fail-closed."""


def replay_state(
    initial_state: WorldState,
    transitions: Sequence[tuple[EventEnvelope, StateDelta]],
    request: ReplayRequest,
) -> WorldState:
    if request.provider_policy != "stored_only":
        raise ReplayIntegrityError("Kernel replay requires provider_policy=stored_only")
    selected = [
        item
        for event, delta in transitions
        if request.event_end is None or event.sequence <= request.event_end
        if event.sequence >= request.event_start
        for item in [(event, delta)]
    ]
    previous_sequence = request.event_start - 1
    state = initial_state
    for event, delta in selected:
        if event.sequence <= previous_sequence:
            raise ReplayIntegrityError("Kernel replay event sequence is not strictly increasing")
        if event.input_state_hash != state.content_hash():
            raise ReplayIntegrityError(f"Kernel replay input hash mismatch at event {event.event_id}")
        if event.delta_hash != delta.content_hash():
            raise ReplayIntegrityError(f"Kernel replay delta hash mismatch at event {event.event_id}")
        if delta.run_id != state.run_id:
            raise ReplayIntegrityError(f"Kernel replay run id mismatch at event {event.event_id}")
        next_state = state.apply_delta(delta)
        if event.output_state_hash != next_state.content_hash():
            raise ReplayIntegrityError(f"Kernel replay output hash mismatch at event {event.event_id}")
        previous_sequence = event.sequence
        state = next_state
    return state
