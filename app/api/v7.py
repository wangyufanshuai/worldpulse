from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.core.negotiation_models import AgentPackManifest, NegotiationCommitment, NegotiationMessage, NegotiationRound
from app.services.negotiation.repository import NegotiationRepository


router = APIRouter()
repository = NegotiationRepository()


def _session(run_id: str):
    try:
        return repository.get_session(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/agent-packs", response_model=list[AgentPackManifest])
def agent_pack_list() -> list[AgentPackManifest]:
    return repository.list_agent_packs()


@router.get("/runs/{run_id}/negotiation")
def negotiation_detail(run_id: str) -> dict:
    session = _session(run_id)
    rounds = repository.list_rounds(session.session_id)
    commitments = repository.list_commitments(session.session_id)
    messages = repository.list_messages(session.session_id)
    return {
        "session": session.model_dump(mode="json"),
        "agent_pack": repository.get_agent_pack(session.agent_pack_id).model_dump(mode="json"),
        "summary": {
            "round_count": len(rounds),
            "message_count": len(messages),
            "active_commitment_count": sum(1 for item in commitments if item.status == "active"),
            "message_chain_head": messages[-1].message_hash if messages else None,
        },
    }


@router.get("/runs/{run_id}/negotiation/rounds", response_model=list[NegotiationRound])
def negotiation_rounds(run_id: str) -> list[NegotiationRound]:
    return repository.list_rounds(_session(run_id).session_id)


@router.get("/runs/{run_id}/negotiation/messages", response_model=list[NegotiationMessage])
def negotiation_messages(
    run_id: str,
    after_seq: int = Query(default=0, ge=0, le=10_000_000),
    tick: int | None = Query(default=None, ge=1, le=6),
) -> list[NegotiationMessage]:
    return repository.list_messages(_session(run_id).session_id, after_seq=after_seq, tick=tick)


@router.get("/runs/{run_id}/negotiation/commitments", response_model=list[NegotiationCommitment])
def negotiation_commitments(run_id: str) -> list[NegotiationCommitment]:
    return repository.list_commitments(_session(run_id).session_id)
