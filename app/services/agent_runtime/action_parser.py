from __future__ import annotations

from typing import Any

from app.services.agent_contract.models import AgentActionProposal
from app.services.consistency.hashing import stable_hash

from .models import AgentProviderRequest


ALLOWED_PROVIDER_FIELDS = {
    "action_type",
    "target_ids",
    "parameters",
    "justification",
    "evidence_refs",
    "expected_direction",
    "confidence",
}


def parse_action_proposal(payload: dict[str, Any], request: AgentProviderRequest, *, seed: int) -> AgentActionProposal:
    raw = payload.get("proposal", payload)
    if not isinstance(raw, dict):
        raise ValueError("Agent provider output must be a JSON object")
    unknown = sorted(set(raw) - ALLOWED_PROVIDER_FIELDS)
    if unknown:
        raise ValueError(f"Agent provider output contains forbidden or unknown fields: {', '.join(unknown)}")
    core = {
        "seed": seed,
        "turn": request.turn,
        "actor_id": request.actor_id,
        "actor_type": request.role.actor_type,
        **raw,
    }
    proposal_id = f"proposal_{stable_hash(core)[:16]}"
    return AgentActionProposal(
        proposal_id=proposal_id,
        run_id=request.run_id,
        turn=request.turn,
        actor_id=request.actor_id,
        actor_type=request.role.actor_type,
        created_at=f"2000-01-01T00:00:{request.turn:02d}.000Z",
        **raw,
    )
