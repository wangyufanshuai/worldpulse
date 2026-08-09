"""Provider-free Agent context resolution for V2 Run Control."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.models import WarRoomRun
from app.services.agent_contract import build_mock_agent_batch
from app.services.agent_contract.models import (
    AgentActionProposal,
    AgentConstraintContext,
    MockAgentBatch,
)
from app.services.consistency.hashing import stable_hash
from app.services.negotiation.agent_pack import build_agent_pack
from app.services.simulation_kernel.resolver_contracts import (
    AgentPackResolverPayload,
    ConstraintContextResolverPayload,
    agent_pack_resolver_payload_hash,
    build_agent_pack_resolver_payload,
    build_constraint_context_resolver_payload,
    constraint_context_resolver_payload_hash,
)


@dataclass(frozen=True)
class ResolvedModeContext:
    agent_pack: AgentPackResolverPayload
    constraint_context: ConstraintContextResolverPayload
    runtime_constraint_context: AgentConstraintContext
    agent_pack_hash: str
    constraint_context_hash: str


def resolve_mode_context(
    result: WarRoomRun,
    *,
    effective_seed: int,
) -> ResolvedModeContext:
    """Run the pinned v1 resolvers without Provider, storage, or wall clock."""

    if type(effective_seed) is not int:
        raise ValueError("effective_seed must be a strict integer")
    agent_pack = build_agent_pack_resolver_payload(
        build_agent_pack(result, effective_seed)
    )
    known = _known_evidence_coordinates(result)
    runtime_context = AgentConstraintContext(
        actor_capabilities={
            profile.agent_id: list(profile.capabilities)
            for profile in agent_pack.profiles
        },
        action_budgets={
            profile.agent_id: profile.action_budget
            for profile in agent_pack.profiles
        },
        known_entities=known,
        known_evidence_refs=known,
    )
    constraint_context = build_constraint_context_resolver_payload(
        runtime_context,
        agent_pack=agent_pack,
    )
    return ResolvedModeContext(
        agent_pack=agent_pack,
        constraint_context=constraint_context,
        runtime_constraint_context=runtime_context,
        agent_pack_hash=agent_pack_resolver_payload_hash(agent_pack),
        constraint_context_hash=constraint_context_resolver_payload_hash(
            constraint_context
        ),
    )


def build_resolved_mock_agent_batch(
    result: WarRoomRun,
    *,
    run_id: str,
    effective_seed: int,
    context: ResolvedModeContext,
    turn: int = 1,
) -> MockAgentBatch:
    """Bind deterministic mock proposals to the resolved Agent capability set."""

    if context.agent_pack.seed != effective_seed:
        raise ValueError("mock Agent Pack seed does not match effective_seed")
    legacy = build_mock_agent_batch(
        result,
        run_id=run_id,
        seed=effective_seed,
        turn=turn,
    )
    proposals: list[AgentActionProposal] = []
    for source in legacy.proposals:
        candidates = tuple(
            profile
            for profile in context.agent_pack.profiles
            if profile.actor_type == source.actor_type
            and source.action_type in profile.capabilities
        )
        if not candidates:
            raise ValueError("resolved Agent Pack cannot own a mock proposal")
        profile = min(candidates, key=lambda item: item.agent_id.encode("utf-8"))
        proposal_payload = source.model_dump(mode="json", exclude={"proposal_id"})
        proposal_payload["actor_id"] = profile.agent_id
        identity = {
            "schema_version": "resolved-mock-agent-proposal.v1",
            "effective_seed": effective_seed,
            "proposal": {
                key: value
                for key, value in proposal_payload.items()
                if key != "run_id"
            },
        }
        proposals.append(
            AgentActionProposal.model_validate(
                {
                    **proposal_payload,
                    "proposal_id": f"proposal_{stable_hash(identity)[:16]}",
                }
            )
        )

    proposal_ids = [item.proposal_id for item in proposals]
    batch_identity: dict[str, object] = {
        "provider": "mock-deterministic",
        "seed": effective_seed,
        "proposal_ids": proposal_ids,
    }
    if proposals:
        batch_identity["constraint_context"] = (
            context.runtime_constraint_context.model_dump(mode="json")
        )
    return MockAgentBatch(
        seed=effective_seed,
        proposals=proposals,
        constraint_context=context.runtime_constraint_context,
        batch_hash=stable_hash(batch_identity),
    )


def _known_evidence_coordinates(result: WarRoomRun) -> list[str]:
    return sorted(
        {f"country:{country.code}" for country in result.country_agents}
        | {f"chain:{chain.key}" for chain in result.supply_chains}
        | {f"timeline:{point.day}" for point in result.timeline}
        | {
            str(node.get("id"))
            for node in result.impact_graph.nodes
            if node.get("id")
        }
        | {"scenario"},
        key=lambda value: value.encode("utf-8"),
    )
