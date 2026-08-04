"""Provider-free Simulation Kernel V2 domain contracts.

These contracts are deliberately separate from the current production
engines.  They make determinism, authority and replay rules executable before
any lifecycle adapter is changed.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, model_validator

from app.services.consistency.hashing import stable_hash

from .immutability import freeze_value


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

# Shared with mode finalization so execution records cannot accept a
# caller-supplied authority lineage without a contracts/finalizer import cycle.
AUTHORITY_PATH_BY_KERNEL_MODE: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "deterministic": (
            "deterministic_rule_engine",
            "consistency_evaluator",
            "simulation_kernel",
        ),
        "hybrid": (
            "deterministic_rule_engine",
            "consistency_evaluator",
            "simulation_kernel",
        ),
        "negotiation": (
            "deterministic_rule_engine",
            "consistency_evaluator",
            "negotiation_engine",
            "simulation_kernel",
        ),
    }
)


class KernelContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    _hash_cache: dict[str, str] | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def freeze_nested_values(self) -> Self:
        for field_name in type(self).model_fields:
            value = getattr(self, field_name)
            frozen_value = freeze_value(value)
            if frozen_value is not value:
                object.__setattr__(self, field_name, frozen_value)
        return self

    def model_copy(
        self,
        *,
        update: Mapping[str, Any] | None = None,
        deep: bool = False,
    ) -> Self:
        if update is not None:
            values = {
                field_name: getattr(self, field_name)
                for field_name in type(self).model_fields
            }
            values.update(update)
            return type(self).model_validate(values)
        return super().model_copy(deep=deep)

    def _memoized_hash(self, key: str, payload_factory: Callable[[], Any]) -> str:
        cache = self._hash_cache
        if cache is None:
            cache = {}
            self._hash_cache = cache
        cached = cache.get(key)
        if cached is not None:
            return cached
        digest = stable_hash(payload_factory())
        cache[key] = digest
        return digest


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
        return self._memoized_hash("content", self.content_payload)

    def apply_delta(self, delta: StateDelta) -> WorldState:
        if delta.run_id != self.run_id:
            raise ValueError("StateDelta run id does not match WorldState")
        if delta.parent_state_hash != self.content_hash():
            raise ValueError("StateDelta parent hash does not match WorldState")
        if delta.tick <= self.tick:
            raise ValueError("StateDelta tick must advance the WorldState")
        if delta.source == "agent_observation":
            raise ValueError("Agent observations cannot write WorldState")
        if delta.source == "action_adapter" and any(change.is_numeric_authority for change in delta.changes):
            raise ValueError("Action Adapter cannot write numeric-authority components")

        entities = dict(self.entities)
        changes_by_entity: dict[str, dict[str, Any]] = {}
        for change in delta.changes:
            if change.entity_id not in entities:
                raise ValueError(f"Unknown WorldState entity: {change.entity_id}")
            changes_by_entity.setdefault(change.entity_id, {})[change.component] = change.value

        for entity_id, component_changes in changes_by_entity.items():
            entity = entities[entity_id]
            components = dict(entity.components)
            components.update(component_changes)
            entities[entity_id] = entity.model_copy(update={"components": components})
        return self.model_copy(update={"tick": delta.tick, "entities": entities})


class StateDelta(KernelContract):
    schema_version: str = "kernel-state-delta.v1"
    run_id: str = Field(min_length=1, max_length=160)
    tick: int = Field(ge=1)
    parent_state_hash: str = Field(min_length=64, max_length=128)
    reducer_version: str = Field(min_length=1, max_length=120)
    source: DeltaSource
    changes: tuple[StateChange, ...] = ()

    @model_validator(mode="after")
    def reject_agent_numeric_writes(self) -> StateDelta:
        if self.source != "deterministic_reducer" and any(change.is_numeric_authority for change in self.changes):
            raise ValueError("Only deterministic reducers may write numeric-authority components")
        return self

    def content_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    def content_hash(self) -> str:
        return self._memoized_hash("content", self.content_payload)


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
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


class Checkpoint(KernelContract):
    schema_version: str = "kernel-checkpoint.v1"
    checkpoint_id: str = Field(min_length=1, max_length=160)
    branch_id: str = Field(min_length=1, max_length=160)
    parent_checkpoint_hash: str | None = Field(default=None, max_length=128)
    event_cursor: int = Field(default=0, ge=0)
    world_state: WorldState
    artifact_hashes: tuple[str, ...] = ()

    def content_hash(self) -> str:
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))


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
        return self._memoized_hash("content", lambda: self.model_dump(mode="json"))
