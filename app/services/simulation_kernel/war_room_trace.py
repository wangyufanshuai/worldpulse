"""Provider-free multi-tick shadow chain for the legacy War Room timeline."""

from __future__ import annotations

from pydantic import Field, model_validator

from app.core.models import WarRoomPresetBundle, WarRoomRun, WarRoomTimelinePoint
from app.services.consistency.hashing import stable_hash

from .contracts import Checkpoint, KernelContract, ReplayRequest, WorldState
from .event_log import KernelEventLog, replay_event_log
from .transitions import CompiledTransition, compile_deterministic_transition
from .war_room_projection import project_war_room_initial_state, project_war_room_run


TRACE_ENTITY_ID = "run:deterministic_trace"
TRACE_REDUCER_VERSION = "war-room-timeline-shadow.v1"


class WarRoomShadowRun(KernelContract):
    """Initial state, Event Log and turning-point checkpoints for one shadow run."""

    schema_version: str = "war-room-shadow-run.v1"
    initial_state: WorldState
    event_log: KernelEventLog
    checkpoints: tuple[Checkpoint, ...] = Field(min_length=2)

    @model_validator(mode="after")
    def verify_checkpoints(self) -> WarRoomShadowRun:
        if self.initial_state.run_id != self.event_log.run_id:
            raise ValueError("War Room shadow run id mismatch")
        if self.initial_state.content_hash() != self.event_log.initial_state_hash:
            raise ValueError("War Room shadow initial state hash mismatch")

        first = self.checkpoints[0]
        if first.event_cursor != 0 or first.parent_checkpoint_hash is not None:
            raise ValueError("War Room shadow initial checkpoint is malformed")
        if first.world_state.content_hash() != self.event_log.initial_state_hash:
            raise ValueError("War Room shadow initial checkpoint state mismatch")

        previous_checkpoint = first
        for checkpoint in self.checkpoints[1:]:
            if checkpoint.branch_id != first.branch_id:
                raise ValueError("War Room shadow checkpoint branch id mismatch")
            if checkpoint.event_cursor <= previous_checkpoint.event_cursor:
                raise ValueError("War Room shadow checkpoint cursors must increase")
            if checkpoint.event_cursor > len(self.event_log.transitions):
                raise ValueError("War Room shadow checkpoint cursor exceeds Event Log")
            if checkpoint.parent_checkpoint_hash != previous_checkpoint.content_hash():
                raise ValueError("War Room shadow checkpoint parent hash mismatch")
            event = self.event_log.transitions[checkpoint.event_cursor - 1].event
            if checkpoint.world_state.content_hash() != event.output_state_hash:
                raise ValueError("War Room shadow checkpoint state hash mismatch")
            previous_checkpoint = checkpoint

        final = self.checkpoints[-1]
        if final.event_cursor != len(self.event_log.transitions):
            raise ValueError("War Room shadow final checkpoint cursor mismatch")
        if final.world_state.content_hash() != self.event_log.final_state_hash:
            raise ValueError("War Room shadow final checkpoint state mismatch")
        return self

    def content_hash(self) -> str:
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


def build_war_room_shadow_run(
    result: WarRoomRun,
    presets: WarRoomPresetBundle,
    *,
    run_id: str,
    seed: int,
    rule_pack_hash: str,
    branch_id: str = "main",
) -> WarRoomShadowRun:
    """Build and verify a truthful shadow chain over the existing timeline."""

    initial_state = project_war_room_initial_state(
        result,
        presets,
        run_id=run_id,
        seed=seed,
        rule_pack_hash=rule_pack_hash,
    )
    final_state = project_war_room_run(
        result,
        run_id=run_id,
        seed=seed,
        rule_pack_hash=rule_pack_hash,
    )
    if not result.timeline[-1].turning_point:
        raise ValueError("War Room shadow final timeline point must be a turning point")

    initial_checkpoint = _checkpoint(
        branch_id=branch_id,
        event_cursor=0,
        world_state=initial_state,
        parent_checkpoint_hash=None,
    )
    checkpoints = [initial_checkpoint]
    transitions: list[CompiledTransition] = []
    source_state = initial_state
    timeline_prefix = [result.timeline[0]]

    for sequence, point in enumerate(result.timeline[1:], start=1):
        timeline_prefix.append(point)
        is_final = sequence == len(result.timeline) - 1
        target_state = (
            final_state
            if is_final
            else _advance_trace_state(source_state, timeline_prefix)
        )
        transition = compile_deterministic_transition(
            source_state,
            target_state,
            event_id=_event_id(run_id, sequence, point.day, target_state.content_hash()),
            sequence=sequence,
            reducer_version=TRACE_REDUCER_VERSION,
            event_type="war_room_final_state" if is_final else "war_room_timeline_tick",
        )
        transitions.append(transition)
        source_state = target_state

        if point.turning_point:
            previous_checkpoint = checkpoints[-1]
            checkpoints.append(
                _checkpoint(
                    branch_id=branch_id,
                    event_cursor=sequence,
                    world_state=target_state,
                    parent_checkpoint_hash=previous_checkpoint.content_hash(),
                )
            )

    event_log = KernelEventLog(
        run_id=run_id,
        initial_state_hash=initial_state.content_hash(),
        final_state_hash=final_state.content_hash(),
        transitions=tuple(transitions),
    )
    shadow_run = WarRoomShadowRun(
        initial_state=initial_state,
        event_log=event_log,
        checkpoints=tuple(checkpoints),
    )
    replayed = replay_event_log(
        initial_state,
        event_log,
        ReplayRequest(checkpoint_id=initial_checkpoint.checkpoint_id),
    )
    if replayed.content_hash() != final_state.content_hash():
        raise ValueError("War Room shadow replay does not match final projection")
    return shadow_run


def _advance_trace_state(
    source_state: WorldState,
    timeline_prefix: list[WarRoomTimelinePoint],
) -> WorldState:
    trace = source_state.entities[TRACE_ENTITY_ID]
    components = dict(trace.components)
    components["timeline"] = [item.model_dump(mode="json") for item in timeline_prefix]
    entities = dict(source_state.entities)
    entities[TRACE_ENTITY_ID] = trace.model_copy(update={"components": components})
    return source_state.model_copy(
        update={"tick": timeline_prefix[-1].day, "entities": entities}
    )


def _event_id(run_id: str, sequence: int, tick: int, target_state_hash: str) -> str:
    digest = stable_hash(
        {
            "run_id": run_id,
            "sequence": sequence,
            "tick": tick,
            "target_state_hash": target_state_hash,
            "reducer_version": TRACE_REDUCER_VERSION,
        }
    )
    return f"evt_kernel_{digest[:24]}"


def _checkpoint(
    *,
    branch_id: str,
    event_cursor: int,
    world_state: WorldState,
    parent_checkpoint_hash: str | None,
) -> Checkpoint:
    digest = stable_hash(
        {
            "run_id": world_state.run_id,
            "branch_id": branch_id,
            "event_cursor": event_cursor,
            "world_state_hash": world_state.content_hash(),
        }
    )
    return Checkpoint(
        checkpoint_id=f"cp_kernel_{digest[:24]}",
        branch_id=branch_id,
        parent_checkpoint_hash=parent_checkpoint_hash,
        event_cursor=event_cursor,
        world_state=world_state,
    )
