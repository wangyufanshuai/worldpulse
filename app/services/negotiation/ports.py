"""Public read contract for persisted negotiation state."""

from __future__ import annotations

from typing import Protocol

from app.core.negotiation_models import (
    AgentPackManifest,
    NegotiationCommitment,
    NegotiationMessage,
    NegotiationRound,
    NegotiationSession,
)


class NegotiationReadApplicationPort(Protocol):
    def list_agent_packs(self) -> list[AgentPackManifest]: ...

    def get_agent_pack(self, agent_pack_id: str) -> AgentPackManifest: ...

    def get_session(self, run_id: str) -> NegotiationSession: ...

    def list_rounds(self, session_id: str) -> list[NegotiationRound]: ...

    def list_messages(
        self,
        session_id: str,
        *,
        after_seq: int = 0,
        tick: int | None = None,
    ) -> list[NegotiationMessage]: ...

    def list_commitments(self, session_id: str) -> list[NegotiationCommitment]: ...
