"""Read-only application adapter for persisted negotiation state."""

from __future__ import annotations

from app.core.negotiation_models import (
    AgentPackManifest,
    NegotiationCommitment,
    NegotiationMessage,
    NegotiationRound,
    NegotiationSession,
)

from .ports import NegotiationReadApplicationPort
from .repository import NegotiationRepository


class NegotiationReadApplicationService:
    def __init__(self, repository: NegotiationRepository | None = None) -> None:
        self._repository = repository or NegotiationRepository()

    def list_agent_packs(self) -> list[AgentPackManifest]:
        return self._repository.list_agent_packs()

    def get_agent_pack(self, agent_pack_id: str) -> AgentPackManifest:
        return self._repository.get_agent_pack(agent_pack_id)

    def get_session(self, run_id: str) -> NegotiationSession:
        return self._repository.get_session(run_id)

    def list_rounds(self, session_id: str) -> list[NegotiationRound]:
        return self._repository.list_rounds(session_id)

    def list_messages(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        tick: int | None = None,
    ) -> list[NegotiationMessage]:
        return self._repository.list_messages(session_id, after_seq=after_seq, tick=tick)

    def list_commitments(self, session_id: str) -> list[NegotiationCommitment]:
        return self._repository.list_commitments(session_id)


negotiation_read_service: NegotiationReadApplicationPort = NegotiationReadApplicationService()
