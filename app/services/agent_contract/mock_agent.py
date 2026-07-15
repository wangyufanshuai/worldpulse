from __future__ import annotations

from app.core.models import WarRoomRun
from app.services.consistency.hashing import stable_hash

from .models import AgentActionProposal, AgentConstraintContext, MockAgentBatch


def build_mock_agent_batch(result: WarRoomRun, *, run_id: str, seed: int | None = 42, turn: int = 1) -> MockAgentBatch:
    """Build repeatable proposals from a read-only deterministic result."""

    countries = sorted(result.country_agents, key=lambda item: (-item.risk_score, item.code))
    chains = sorted(result.supply_chains, key=lambda item: (-item.pressure_score, item.key))
    if len(countries) < 4 or not chains:
        return _empty_batch(result, seed or 0)

    actors = countries[:4]
    top_country = f"country:{countries[0].code}"
    top_chain = f"chain:{chains[0].key}"
    timeline_ref = f"timeline:{result.timeline[-1].day}" if result.timeline else "scenario"
    specs = [
        {
            "actor": actors[0], "actor_type": "country_policy", "action_type": "trade_reroute_request",
            "targets": [top_chain],
            "parameters": {"chain_key": chains[0].key, "alternative_route": "规则沙盘备用通道", "duration_days": min(30, result.scenario.duration_days)},
            "direction": "reroute",
            "justification": f"{chains[0].name} 是当前确定性结果中的最高压力链路，提出受审计的替代路径请求。",
        },
        {
            "actor": actors[1], "actor_type": "diplomacy", "action_type": "diplomatic_signal",
            "targets": [top_country],
            "parameters": {"signal": "deescalatory", "channel": "backchannel", "public": False},
            "direction": "deescalate",
            "justification": "针对最高风险国家节点提出私下沟通信号；该提案不包含任何风险数值修改。",
        },
        {
            "actor": actors[2], "actor_type": "alliance", "action_type": "alliance_request",
            "targets": [f"country:{actors[1].code}"],
            "parameters": {"objective": "协调情报与人道保障", "requested_support": ["diplomatic", "intelligence"], "duration_days": min(21, result.scenario.duration_days)},
            "direction": "coordinate",
            "justification": "请求在仿真能力信封内协调外交与情报支持，等待一致性评估后再决定准入。",
        },
        {
            "actor": actors[3], "actor_type": "public_opinion", "action_type": "public_narrative",
            "targets": [top_country],
            "parameters": {"theme": "公开说明供应链与人道风险", "audience": "regional", "tone": "stabilizing"},
            "direction": "inform",
            "justification": "基于已保存的确定性节点发布稳定性叙事提案，不创建或覆盖权威数值。",
        },
    ]
    proposals = []
    capabilities = {}
    budgets = {}
    for spec in specs:
        actor_id = f"country:{spec['actor'].code}"
        core = {
            "seed": int(seed or 0),
            "turn": turn,
            "actor_id": actor_id,
            "actor_type": spec["actor_type"],
            "action_type": spec["action_type"],
            "target_ids": spec["targets"],
            "parameters": spec["parameters"],
            "justification": spec["justification"],
            "evidence_refs": [actor_id, *spec["targets"], timeline_ref],
            "expected_direction": spec["direction"],
            "confidence": round(min(90, 55 + spec["actor"].risk_score * 0.25), 1),
        }
        proposal_id = f"proposal_{stable_hash(core)[:16]}"
        proposals.append(AgentActionProposal(
            proposal_id=proposal_id,
            run_id=run_id,
            created_at=f"2000-01-01T00:00:{turn:02d}.000Z",
            **{key: value for key, value in core.items() if key != "seed"},
        ))
        capabilities[actor_id] = [spec["action_type"]]
        budgets[actor_id] = 1

    known_entities = sorted(
        {f"country:{country.code}" for country in result.country_agents}
        | {f"chain:{chain.key}" for chain in result.supply_chains}
        | {f"timeline:{point.day}" for point in result.timeline}
        | {str(node.get("id")) for node in result.impact_graph.nodes if node.get("id")}
        | {"scenario"}
    )
    context = AgentConstraintContext(
        actor_capabilities=capabilities,
        action_budgets=budgets,
        known_entities=known_entities,
        known_evidence_refs=known_entities,
    )
    batch_identity = {
        "provider": "mock-deterministic",
        "seed": int(seed or 0),
        "proposal_ids": [proposal.proposal_id for proposal in proposals],
        "constraint_context": context.model_dump(mode="json"),
    }
    return MockAgentBatch(seed=int(seed or 0), proposals=proposals, constraint_context=context, batch_hash=stable_hash(batch_identity))


def _empty_batch(result: WarRoomRun, seed: int) -> MockAgentBatch:
    known = sorted({f"country:{country.code}" for country in result.country_agents} | {f"chain:{chain.key}" for chain in result.supply_chains})
    context = AgentConstraintContext(known_entities=known, known_evidence_refs=known)
    return MockAgentBatch(seed=seed, proposals=[], constraint_context=context, batch_hash=stable_hash({"provider": "mock-deterministic", "seed": seed, "proposal_ids": []}))
