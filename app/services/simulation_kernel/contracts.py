"""Provider-free Simulation Kernel V2 domain contracts.

These contracts are deliberately separate from the current production
engines.  They make determinism, authority and replay rules executable before
any lifecycle adapter is changed.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.services.consistency.hashing import stable_hash


NumericAuthorityComponent = Literal[
    "risk_score",
    "supply_chain_pressure",
    "country_capability",
    "numeric_authority",
]
NUMERIC_AUTHORITY_COMPONENTS = frozenset(
    {"risk_score", "supply_chain_pressure", "country_capability", "numeric_authority"}
)
DeltaSource = Literal["deterministic_reducer", "action_adapter", "agent_observation", "replay"]


class KernelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Entity(KernelContract):
    entity_id: str = Field(min_length=1, max_length=160)
    entity_type: str = Field(min_length=1, max_length=80)
    components: dict[str, Any] = Field(default_factory=dict)


class StateChange(KernelContract):
    entity_id: str = Field(min_length=1, max_length=160)
    component: str = Field(min_length=1, max_length=160)
    value: Any

    @property
    def is_numeric_authority(self) -> bool:
        return self.component in NUMERIC_AUTHORITY_COMPONENTS or self.component.startswith("numeric.")


class WorldState(KernelContract):
    schema_version: str = "kernel-world-state.v1"
    run_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(default=0, ge=0)
    seed: int
    rule_pack_hash: str = Field(min_length=1, max_length=128)
    entities: dict[str, Entity] = Field(default_factory=dict)

    def content_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "run_id": self.run_id,
            "tick": self.tick,
            "seed": self.seed,
            "rule_pack_hash": self.rule_pack_hash,
            "entities": {
                entity_id: self.entities[entity_id].model_dump(mode="json")
                for entity_id in sorted(self.entities)
            },
        }

    def content_hash(self) -> str:
        return stable_hash(self.content_payload())

    def apply_delta(self, delta: StateDelta) -> WorldState:
        if delta.parent_state_hash != self.content_hash():
            raise ValueError("StateDelta parent hash does not match WorldState")
        if delta.tick <= self.tick:
            raise ValueError("StateDelta tick must advance the WorldState")
        if delta.source == "agent_observation":
            raise ValueError("Agent observations cannot write WorldState")
        if delta.source == "action_adapter" and any(change.is_numeric_authority for change in delta.changes):
            raise ValueError("Action Adapter cannot write numeric-authority components")

        entities = {entity_id: entity.model_copy(deep=True) for entity_id, entity in self.entities.items()}
        for change in delta.changes:
            entity = entities.get(change.entity_id)
            if entity is None:
                raise ValueError(f"Unknown WorldState entity: {change.entity_id}")
            components = dict(entity.components)
            components[change.component] = change.value
            entities[change.entity_id] = entity.model_copy(update={"components": components})
        return self.model_copy(update={"tick": delta.tick, "entities": entities})


class StateDelta(KernelContract):
    schema_version: str = "kernel-state-delta.v1"
    run_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1)
    parent_state_hash: str = Field(min_length=64, max_length=128)
    reducer_version: str = Field(min_length=1, max_length=120)
    source: DeltaSource
    changes: tuple[StateChange, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def reject_agent_numeric_writes(self) -> StateDelta:
        if self.source != "deterministic_reducer" and any(change.is_numeric_authority for change in self.changes):
            raise ValueError("Only deterministic reducers may write numeric-authority components")
        return self

    def content_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        return stable_hash(self.content_payload())


class EventEnvelope(KernelContract):
    schema_version: str = "kernel-event-envelope.v1"
    event_id: str = Field(min_length=1, max_length=160)
    sequence: int = Field(ge=1)
    tick: int = Field(ge=0)
    event_type: str = Field(min_length=1, max_length=120)
    input_state_hash: str = Field(min_length=64, max_length=128)
    output_state_hash: str = Field(min_length=64, max_length=128)
    delta_hash: str = Field(min_length=64, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class Checkpoint(KernelContract):
    schema_version: str = "kernel-checkpoint.v1"
    checkpoint_id: str = Field(min_length=1, max_length=160)
    branch_id: str = Field(min_length=1, max_length=160)
    parent_checkpoint_hash: str | None = Field(default=None, max_length=128)
    event_cursor: int = Field(default=0, ge=0)
    world_state: WorldState
    artifact_hashes: tuple[str, ...] = ()

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))


class ReplayRequest(KernelContract):
    schema_version: str = "kernel-replay-request.v1"
    checkpoint_id: str = Field(min_length=1, max_length=160)
    event_start: int = Field(default=1, ge=1)
    event_end: int | None = Field(default=None, ge=1)
    provider_policy: Literal["stored_only"] = "stored_only"


class ExperimentBranch(KernelContract):
    schema_version: str = "kernel-experiment-branch.v1"
    branch_id: str = Field(min_length=1, max_length=160)
    parent_checkpoint_hash: str = Field(min_length=64, max_length=128)
    treatment: Literal["control", "treated"]
    seed: int
    scenario_diff: dict[str, Any] = Field(default_factory=dict)

    def content_hash(self) -> str:
        return stable_hash(self.model_dump(mode="json"))
