from __future__ import annotations

from app.services.consistency.hashing import stable_hash


def proposal_semantic_key(proposal) -> str:
    return stable_hash({
        "actor_id": proposal.actor_id,
        "action_type": proposal.action_type,
        "target_ids": sorted(proposal.target_ids),
        "parameters": proposal.parameters,
    })


def response_is_authorized(parent_message, response_message) -> bool:
    return bool(
        response_message.parent_message_id == parent_message.message_id
        and response_message.tick > parent_message.tick
        and response_message.sender_agent_id in parent_message.recipient_agent_ids
        and parent_message.sender_agent_id in response_message.recipient_agent_ids
    )


def alliance_commitment_conflicts(candidate, active_commitments) -> bool:
    if candidate.action_type != "alliance_request":
        return False
    candidate_parties = set(candidate.party_agent_ids)
    for active in active_commitments:
        if active.status != "active" or active.action_type != "alliance_request":
            continue
        parties = set(active.party_agent_ids)
        if candidate_parties == parties:
            return True
    return False
