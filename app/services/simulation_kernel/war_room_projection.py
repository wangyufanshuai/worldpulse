"""Read-only projection from the V1 War Room result into Kernel V2 state.

The adapter is deliberately a pure boundary mapper.  It does not execute the
War Room engine, resolve a Rule Pack, call an Agent Provider, read storage, or
include UI projections.  Callers must provide the lifecycle run id, seed and
pinned Rule Pack manifest hash so the resulting state cannot be mistaken for
an unpinned simulation snapshot.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from app.core.models import (
    SupplyChainLink,
    WarRoomCountryAgent,
    WarRoomPresetBundle,
    WarRoomRun,
    WarRoomScenario,
    WarRoomTimelinePoint,
)
from app.services.consistency.hashing import stable_hash

from .contracts import Entity, KernelContract, WorldState


PROJECTION_SCHEMA_VERSION = "war-room-world-state.v1"
DETERMINISTIC_AUTHORITY_OWNER = "war_room.deterministic_rule_engine"
WORLD_MODEL_PRESET_AUTHORITY_OWNER = "world_model.war_room_preset"


class WarRoomProjection(KernelContract):
    """Hash-addressed correspondence between a V1 run and Kernel state."""

    schema_version: str = "war-room-projection.v1"
    source_run_hash: str = Field(min_length=64, max_length=64)
    deterministic_source_hash: str = Field(min_length=64, max_length=64)
    world_state_hash: str = Field(min_length=64, max_length=64)
    world_state: WorldState

    @model_validator(mode="after")
    def verify_world_state_hash(self) -> WarRoomProjection:
        if self.world_state_hash != self.world_state.content_hash():
            raise ValueError("WarRoom projection WorldState hash mismatch")
        return self


def build_war_room_projection(
    result: WarRoomRun,
    *,
    run_id: str,
    seed: int,
    rule_pack_hash: str,
) -> WarRoomProjection:
    """Build the state plus explicit V1-to-Kernel hash correspondence."""

    world_state = project_war_room_run(
        result,
        run_id=run_id,
        seed=seed,
        rule_pack_hash=rule_pack_hash,
    )
    return WarRoomProjection(
        source_run_hash=stable_hash(result.model_dump(mode="json")),
        deterministic_source_hash=stable_hash(_deterministic_source_payload(result)),
        world_state_hash=world_state.content_hash(),
        world_state=world_state,
    )


def project_war_room_run(
    result: WarRoomRun,
    *,
    run_id: str,
    seed: int,
    rule_pack_hash: str,
) -> WorldState:
    """Project a completed ``WarRoomRun`` into an immutable Kernel snapshot.

    The V1 run model intentionally remains unchanged.  Only deterministic
    world-model data is promoted to Kernel entities: scenario metadata,
    country state, supply-chain state and the deterministic timeline trace.
    Agent decisions, impact-graph/UI data and summary/report narrative stay
    outside numeric-authority state and are therefore not silently promoted.
    """

    normalized_rule_pack_hash = _validate_projection_metadata(run_id, rule_pack_hash)
    _validate_source_collections(result)

    entities: dict[str, Entity] = {}
    scenario = result.scenario
    entities[f"scenario:{scenario.key}"] = _scenario_entity(scenario)

    for agent in sorted(result.country_agents, key=lambda item: item.code):
        entities[f"country:{agent.code}"] = _country_entity(agent)

    for chain in sorted(result.supply_chains, key=lambda item: item.key):
        entities[f"supply_chain:{chain.key}"] = _supply_chain_entity(chain)

    entities["run:deterministic_trace"] = _trace_entity(
        result.timeline,
        result.assumptions,
    )

    final_tick = max((point.day for point in result.timeline), default=0)
    return WorldState(
        run_id=run_id,
        tick=final_tick,
        seed=seed,
        rule_pack_hash=normalized_rule_pack_hash,
        entities={entity_id: entities[entity_id] for entity_id in sorted(entities)},
    )


def project_war_room_initial_state(
    result: WarRoomRun,
    presets: WarRoomPresetBundle,
    *,
    run_id: str,
    seed: int,
    rule_pack_hash: str,
) -> WorldState:
    """Project the public World Model catalog and day-zero trace into Kernel state."""

    normalized_rule_pack_hash = _validate_projection_metadata(run_id, rule_pack_hash)
    _validate_source_collections(result)
    _validate_preset_topology(result, presets)
    if result.timeline[0].day != 0:
        raise ValueError("WarRoom initial projection requires a day-zero timeline point")

    scenario = result.scenario
    entities: dict[str, Entity] = {
        f"scenario:{scenario.key}": _scenario_entity(scenario),
        "run:deterministic_trace": _trace_entity(
            [result.timeline[0]],
            result.assumptions,
        ),
    }
    for agent in sorted(presets.countries, key=lambda item: item.code):
        entities[f"country:{agent.code}"] = _country_entity(
            agent,
            authority_owner=WORLD_MODEL_PRESET_AUTHORITY_OWNER,
            source_field="WarRoomPresetBundle.countries[].risk_score",
        )
    for chain in sorted(presets.supply_chains, key=lambda item: item.key):
        entities[f"supply_chain:{chain.key}"] = _supply_chain_entity(
            chain,
            authority_owner=WORLD_MODEL_PRESET_AUTHORITY_OWNER,
            source_field="WarRoomPresetBundle.supply_chains[].pressure_score",
        )
    return WorldState(
        run_id=run_id,
        tick=0,
        seed=seed,
        rule_pack_hash=normalized_rule_pack_hash,
        entities={entity_id: entities[entity_id] for entity_id in sorted(entities)},
    )


def _scenario_entity(scenario: WarRoomScenario) -> Entity:
    return Entity(
        entity_id=f"scenario:{scenario.key}",
        entity_type="scenario",
        components={
            "projection_schema_version": PROJECTION_SCHEMA_VERSION,
            "scenario_config": scenario.model_dump(mode="json"),
            "metadata": {
                "key": scenario.key,
                "name": scenario.name,
                "description": scenario.description,
                "target_countries": list(scenario.target_countries),
                "target_chains": list(scenario.target_chains),
                "policy_actions": list(scenario.policy_actions),
            },
            "numeric_input_source": "war_room.scenario_compiler",
        },
    )


def _trace_entity(
    timeline: list[WarRoomTimelinePoint],
    assumptions: list[str],
) -> Entity:
    return Entity(
        entity_id="run:deterministic_trace",
        entity_type="deterministic_trace",
        components={
            "timeline": [item.model_dump(mode="json") for item in timeline],
            "assumptions": list(assumptions),
            "trace_source": DETERMINISTIC_AUTHORITY_OWNER,
        },
    )


def _country_entity(
    agent: WarRoomCountryAgent,
    *,
    authority_owner: str = DETERMINISTIC_AUTHORITY_OWNER,
    source_field: str = "WarRoomCountryAgent.risk_score",
) -> Entity:
    identity = {
        "code": agent.code,
        "name": agent.name,
        "region": agent.region,
        "latitude": agent.latitude,
        "longitude": agent.longitude,
        "alliance": agent.alliance,
    }
    numeric = {
        "energy_dependency": agent.energy_dependency,
        "food_dependency": agent.food_dependency,
        "trade_exposure": agent.trade_exposure,
        "chip_dependency": agent.chip_dependency,
        "military_pressure": agent.military_pressure,
        "public_opinion_pressure": agent.public_opinion_pressure,
        "financial_stress": agent.financial_stress,
        "stability": agent.stability,
        "risk_score": agent.risk_score,
    }
    return Entity(
        entity_id=f"country:{agent.code}",
        entity_type="country",
        components={
            "identity": identity,
            **numeric,
            "authority_provenance": _authority_provenance(
                ("risk_score",),
                authority_owner=authority_owner,
                source_field=source_field,
            ),
        },
    )


def _supply_chain_entity(
    chain: SupplyChainLink,
    *,
    authority_owner: str = DETERMINISTIC_AUTHORITY_OWNER,
    source_field: str = "SupplyChainLink.pressure_score",
) -> Entity:
    return Entity(
        entity_id=f"supply_chain:{chain.key}",
        entity_type="supply_chain",
        components={
            "identity": {"key": chain.key, "name": chain.name},
            "capacity": chain.capacity,
            "disruption": chain.disruption,
            "substitution": chain.substitution,
            "lag_days": chain.lag_days,
            "affected_countries": list(chain.affected_countries),
            # Kernel vocabulary names the authoritative pressure component;
            # the V1 ``pressure_score`` field remains unchanged at its source.
            "supply_chain_pressure": chain.pressure_score,
            "authority_provenance": _authority_provenance(
                ("supply_chain_pressure",),
                authority_owner=authority_owner,
                source_field=source_field,
            ),
        },
    )


def _authority_provenance(
    components: tuple[str, ...],
    *,
    authority_owner: str,
    source_field: str,
) -> dict[str, Any]:
    return {
        "owner": authority_owner,
        "source_field": source_field,
        "components": list(components),
    }


def _deterministic_source_payload(result: WarRoomRun) -> dict[str, Any]:
    return {
        "scenario": result.scenario.model_dump(mode="json"),
        "timeline": [item.model_dump(mode="json") for item in result.timeline],
        "country_agents": [
            item.model_dump(mode="json")
            for item in sorted(result.country_agents, key=lambda country: country.code)
        ],
        "supply_chains": [
            item.model_dump(mode="json")
            for item in sorted(result.supply_chains, key=lambda chain: chain.key)
        ],
        "assumptions": list(result.assumptions),
    }


def _validate_source_collections(result: WarRoomRun) -> None:
    country_codes = [item.code for item in result.country_agents]
    if len(country_codes) != len(set(country_codes)):
        raise ValueError("WarRoom projection requires unique country codes")

    supply_chain_keys = [item.key for item in result.supply_chains]
    if len(supply_chain_keys) != len(set(supply_chain_keys)):
        raise ValueError("WarRoom projection requires unique supply-chain keys")

    timeline_days = [item.day for item in result.timeline]
    timeline_pairs = zip(timeline_days, timeline_days[1:], strict=False)
    if not timeline_days or any(current <= previous for previous, current in timeline_pairs):
        raise ValueError("WarRoom projection requires a strictly increasing deterministic timeline")


def _validate_projection_metadata(run_id: str, rule_pack_hash: str) -> str:
    if not run_id.strip() or run_id != run_id.strip():
        raise ValueError("WarRoom projection requires a non-empty run_id")
    normalized_rule_pack_hash = rule_pack_hash.strip().lower()
    is_sha256 = len(normalized_rule_pack_hash) == 64 and all(
        character in "0123456789abcdef" for character in normalized_rule_pack_hash
    )
    if not is_sha256:
        raise ValueError("WarRoom projection requires a pinned SHA-256 rule_pack_hash")
    return normalized_rule_pack_hash


def _validate_preset_topology(result: WarRoomRun, presets: WarRoomPresetBundle) -> None:
    preset_country_codes = [item.code for item in presets.countries]
    preset_chain_keys = [item.key for item in presets.supply_chains]
    if len(preset_country_codes) != len(set(preset_country_codes)):
        raise ValueError("WarRoom initial projection requires unique preset country codes")
    if len(preset_chain_keys) != len(set(preset_chain_keys)):
        raise ValueError("WarRoom initial projection requires unique preset supply-chain keys")
    if set(preset_country_codes) != {item.code for item in result.country_agents}:
        raise ValueError("WarRoom initial projection country topology mismatch")
    if set(preset_chain_keys) != {item.key for item in result.supply_chains}:
        raise ValueError("WarRoom initial projection supply-chain topology mismatch")
