from __future__ import annotations

from app.core.models import WarRoomRun
from app.core.negotiation_models import AgentPackManifest, NegotiationAgentProfile
from app.services.consistency.hashing import stable_hash


ROLE_LAYOUT = (
    ("country_policy", 6),
    ("diplomacy", 2),
    ("alliance", 2),
    ("public_opinion", 2),
)

CAPABILITIES = {
    "country_policy": ["sanction_proposal", "trade_reroute_request", "humanitarian_offer", "intelligence_request", "alliance_request"],
    "diplomacy": ["diplomatic_signal", "deescalation_offer", "humanitarian_offer"],
    "alliance": ["alliance_request", "alliance_response", "diplomatic_signal"],
    "public_opinion": ["public_narrative"],
}


def build_agent_pack(result: WarRoomRun, seed: int) -> AgentPackManifest:
    countries = sorted(result.country_agents, key=lambda item: (-item.risk_score, item.code))
    if len(countries) < 6:
        raise ValueError("Negotiation mode requires at least six country agents")
    profiles: list[NegotiationAgentProfile] = []
    offset = 0
    for role, count in ROLE_LAYOUT:
        for index in range(count):
            country = countries[(offset + index) % len(countries)]
            core = {
                "agent_id": f"agent:{role}:{country.code}",
                "actor_type": role,
                "country_code": country.code,
                "country_name": country.name,
                "capabilities": CAPABILITIES[role],
                "action_budget": 6,
            }
            profiles.append(NegotiationAgentProfile(**core, profile_hash=stable_hash(core)))
        offset += count
    manifest_core = {
        "schema_version": "agent-pack-manifest.v1",
        "seed": int(seed),
        "profiles": [item.model_dump(mode="json") for item in profiles],
    }
    manifest_hash = stable_hash(manifest_core)
    return AgentPackManifest(
        agent_pack_id=f"agent_pack_{manifest_hash[:20]}",
        seed=int(seed),
        profiles=profiles,
        manifest_hash=manifest_hash,
        created_at="2000-01-01T00:00:00.000Z",
    )


def scheduled_profiles(pack: AgentPackManifest, tick: int) -> list[NegotiationAgentProfile]:
    ordered = sorted(pack.profiles, key=lambda item: item.agent_id)
    start = ((tick - 1) * 6) % len(ordered)
    return [ordered[(start + index) % len(ordered)] for index in range(6)]
