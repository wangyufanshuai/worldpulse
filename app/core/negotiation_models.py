from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.agent_contract.models import ActionType, AgentActionProposal, ActorType


MessageType = Literal["proposal", "counteroffer", "accept", "reject", "withdrawal", "public_statement"]
MessageVisibility = Literal["public", "direct"]
CommitmentStatus = Literal["proposed", "active", "rejected", "withdrawn", "expired"]


class NegotiationAgentProfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    actor_type: ActorType
    country_code: str
    country_name: str
    capabilities: list[ActionType]
    action_budget: int = Field(default=6, ge=1, le=12)
    profile_hash: str


class AgentPackManifest(BaseModel):
    schema_version: str = "agent-pack-manifest.v1"
    agent_pack_id: str
    status: Literal["active", "retired"] = "active"
    seed: int
    profiles: list[NegotiationAgentProfile]
    manifest_hash: str
    created_at: str


class NegotiationEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_type: MessageType
    visibility: MessageVisibility
    sender_agent_id: str
    recipient_agent_ids: list[str] = Field(default_factory=list, max_length=4)
    parent_message_id: str | None = None
    narrative: str = Field(min_length=3, max_length=1200)
    proposal: AgentActionProposal | None = None


class NegotiationMessage(BaseModel):
    message_id: str
    session_id: str
    round_id: str
    tick: int
    seq: int
    sender_agent_id: str
    recipient_agent_ids: list[str]
    message_type: MessageType
    visibility: MessageVisibility
    parent_message_id: str | None = None
    proposal_id: str | None = None
    narrative: str
    payload: dict[str, Any] = Field(default_factory=dict)
    provider: str
    model: str
    latency_ms: int = 0
    estimated_tokens: int = 0
    fallback_used: bool = False
    previous_hash: str | None = None
    message_hash: str
    created_at: str


class CommitmentEvent(BaseModel):
    event_id: str
    commitment_id: str
    session_id: str
    tick: int
    seq: int
    status: CommitmentStatus
    actor_agent_id: str
    source_message_id: str
    reason: str
    event_hash: str
    created_at: str


class NegotiationCommitment(BaseModel):
    commitment_id: str
    session_id: str
    source_message_id: str
    source_proposal_id: str
    action_type: ActionType
    party_agent_ids: list[str]
    terms: dict[str, Any]
    commitment_hash: str
    status: CommitmentStatus = "proposed"
    created_at: str
    events: list[CommitmentEvent] = Field(default_factory=list)


class NegotiationRound(BaseModel):
    round_id: str
    session_id: str
    tick: int
    simulation_day: int
    status: Literal["running", "completed", "failed"]
    scheduled_agents: list[str]
    input: dict[str, Any]
    output: dict[str, Any]
    input_hash: str
    output_hash: str | None = None
    previous_state_hash: str
    modifier_bundle_hash: str | None = None
    result_state_hash: str | None = None
    started_at: str
    completed_at: str | None = None


class NegotiationSession(BaseModel):
    session_id: str
    run_id: str
    agent_pack_id: str
    agent_pack_hash: str
    status: Literal["running", "paused", "cancelled", "failed", "completed"]
    current_tick: int
    baseline_result_hash: str
    final_result_hash: str | None = None
    cumulative_patch: dict[str, Any] = Field(default_factory=dict)
    applied_proposal_ids: list[str] = Field(default_factory=list)
    created_at: str
    completed_at: str | None = None


class NarrativeDiffusionAudit(BaseModel):
    schema_version: str = "narrative-diffusion.v1"
    seed: int = 42
    tone_deltas: dict[str, float]
    country_deltas: dict[str, float]
    applications: list[dict[str, Any]]
    audit_hash: str


class NegotiationReplayManifest(BaseModel):
    schema_version: str = "negotiation-replay.v1"
    session_id: str
    agent_pack_hash: str
    baseline_result_hash: str
    final_result_hash: str
    round_hashes: list[str]
    message_chain_head: str | None
    commitment_hashes: list[str]
    provider_calls_required: int = 0
    replay_hash: str
