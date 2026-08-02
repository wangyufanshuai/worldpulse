"""Canonical deterministic transition compiler for Kernel V2 snapshots."""

from __future__ import annotations

from pydantic import model_validator

from .contracts import EventEnvelope, KernelContract, StateChange, StateDelta, WorldState


class TransitionIntegrityError(ValueError):
    """Raised when two states cannot form one deterministic transition."""


class CompiledTransition(KernelContract):
    """A hash-linked delta and event pair that is safe to append or replay."""

    schema_version: str = "kernel-compiled-transition.v1"
    delta: StateDelta
    event: EventEnvelope

    @model_validator(mode="after")
    def verify_hash_links(self) -> CompiledTransition:
        if self.event.input_state_hash != self.delta.parent_state_hash:
            raise ValueError("Compiled transition input hash mismatch")
        if self.event.delta_hash != self.delta.content_hash():
            raise ValueError("Compiled transition delta hash mismatch")
        if self.event.tick != self.delta.tick:
            raise ValueError("Compiled transition tick mismatch")
        return self

    def content_hash(self) -> str:
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


def compile_deterministic_transition(
    source_state: WorldState,
    target_state: WorldState,
    *,
    event_id: str,
    sequence: int,
    reducer_version: str,
    event_type: str = "deterministic_state_transition",
) -> CompiledTransition:
    """Compile and verify a canonical component delta between two snapshots."""

    _validate_transition_metadata(source_state, target_state)
    changes = _component_changes(source_state, target_state)
    source_hash = source_state.content_hash()
    delta = StateDelta(
        run_id=source_state.run_id,
        tick=target_state.tick,
        parent_state_hash=source_hash,
        reducer_version=reducer_version,
        source="deterministic_reducer",
        changes=tuple(changes),
    )
    applied_state = source_state.apply_delta(delta)
    target_hash = target_state.content_hash()
    if applied_state.content_hash() != target_hash:
        raise TransitionIntegrityError("Compiled delta does not reproduce target WorldState hash")

    event = EventEnvelope(
        event_id=event_id,
        sequence=sequence,
        tick=target_state.tick,
        event_type=event_type,
        input_state_hash=source_hash,
        output_state_hash=target_hash,
        delta_hash=delta.content_hash(),
        payload={
            "change_count": len(changes),
            "reducer_version": reducer_version,
            "source": "deterministic_reducer",
        },
    )
    return CompiledTransition(delta=delta, event=event)


def _validate_transition_metadata(source_state: WorldState, target_state: WorldState) -> None:
    metadata_pairs = (
        ("schema version", source_state.schema_version, target_state.schema_version),
        ("run id", source_state.run_id, target_state.run_id),
        ("seed", source_state.seed, target_state.seed),
        ("Rule Pack hash", source_state.rule_pack_hash, target_state.rule_pack_hash),
    )
    for label, source_value, target_value in metadata_pairs:
        if source_value != target_value:
            raise TransitionIntegrityError(f"Deterministic transition {label} mismatch")
    if target_state.tick <= source_state.tick:
        raise TransitionIntegrityError("Deterministic transition target tick must advance")

    source_entity_ids = set(source_state.entities)
    target_entity_ids = set(target_state.entities)
    if source_entity_ids != target_entity_ids:
        raise TransitionIntegrityError("Deterministic transition entity topology mismatch")


def _component_changes(source_state: WorldState, target_state: WorldState) -> list[StateChange]:
    changes: list[StateChange] = []
    for entity_id in sorted(source_state.entities):
        source_entity = source_state.entities[entity_id]
        target_entity = target_state.entities[entity_id]
        if source_entity.entity_type != target_entity.entity_type:
            raise TransitionIntegrityError(f"Deterministic transition entity type mismatch: {entity_id}")

        removed_components = set(source_entity.components) - set(target_entity.components)
        if removed_components:
            raise TransitionIntegrityError(
                f"Deterministic transition cannot remove components from {entity_id}"
            )
        for component in sorted(target_entity.components):
            target_value = target_entity.components[component]
            source_has_component = component in source_entity.components
            source_value = source_entity.components.get(component)
            if source_has_component and _canonical_equal(source_value, target_value):
                continue
            changes.append(
                StateChange(
                    entity_id=entity_id,
                    component=component,
                    value=target_value,
                )
            )
    return changes


def _canonical_equal(source_value: object, target_value: object) -> bool:
    """Compare JSON-compatible values without serializing unchanged fields."""

    if type(source_value) is not type(target_value):
        return False
    if isinstance(source_value, dict) and isinstance(target_value, dict):
        if source_value.keys() != target_value.keys():
            return False
        return all(
            _canonical_equal(source_value[key], target_value[key])
            for key in source_value
        )
    if isinstance(source_value, (list, tuple)) and isinstance(target_value, (list, tuple)):
        return len(source_value) == len(target_value) and all(
            _canonical_equal(source_item, target_item)
            for source_item, target_item in zip(source_value, target_value, strict=True)
        )
    if isinstance(source_value, float) and isinstance(target_value, float):
        return repr(source_value) == repr(target_value)
    return source_value == target_value
