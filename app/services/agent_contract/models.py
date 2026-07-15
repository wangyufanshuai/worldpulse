from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .parameters import validate_parameters


ActionType = Literal[
    "diplomatic_signal",
    "alliance_request",
    "alliance_response",
    "sanction_proposal",
    "trade_reroute_request",
    "public_narrative",
    "humanitarian_offer",
    "deescalation_offer",
    "intelligence_request",
]
ActorType = Literal["country_policy", "diplomacy", "alliance", "public_opinion", "explanation"]
ExpectedDirection = Literal["deescalate", "deter", "stabilize", "coordinate", "reroute", "inform", "assist", "observe"]

NUMERIC_AUTHORITY_KEYS = {
    "risk_score",
    "global_risk",
    "supply_chain_pressure",
    "pressure_score",
    "risk_delta",
    "numeric_weight",
    "deterministic_modifier",
}


class AgentActionProposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str = Field(min_length=12, max_length=80)
    schema_version: str = "agent-action-proposal.v1"
    run_id: str = Field(min_length=3, max_length=80)
    turn: int = Field(ge=0, le=100)
    actor_id: str = Field(min_length=3, max_length=80)
    actor_type: ActorType
    action_type: ActionType
    target_ids: list[str] = Field(min_length=1, max_length=4)
    parameters: dict[str, Any]
    justification: str = Field(min_length=8, max_length=1200)
    evidence_refs: list[str] = Field(min_length=1, max_length=20)
    expected_direction: ExpectedDirection
    confidence: float = Field(ge=0, le=100)
    created_at: str
    expires_after_turn: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="before")
    @classmethod
    def reject_numeric_authority_fields(cls, value):
        forbidden = _find_forbidden_keys(value)
        if forbidden:
            raise ValueError(f"Agent proposals cannot contain deterministic numeric authority fields: {', '.join(sorted(forbidden))}")
        return value

    @model_validator(mode="after")
    def validate_action_parameters(self):
        self.parameters = validate_parameters(self.action_type, self.parameters)
        return self


class AgentConstraintContext(BaseModel):
    schema_version: str = "agent-constraint-context.v1"
    actor_capabilities: dict[str, list[ActionType]] = Field(default_factory=dict)
    action_budgets: dict[str, int] = Field(default_factory=dict)
    known_entities: list[str] = Field(default_factory=list)
    known_evidence_refs: list[str] = Field(default_factory=list)
    source_label: str = "explicit simulation capability envelope"


class MockAgentBatch(BaseModel):
    schema_version: str = "mock-agent-batch.v1"
    provider: str = "mock-deterministic"
    seed: int
    proposals: list[AgentActionProposal]
    constraint_context: AgentConstraintContext
    batch_hash: str


def _find_forbidden_keys(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).strip().lower().replace("-", "_")
            if normalized in NUMERIC_AUTHORITY_KEYS:
                found.add(normalized)
            found.update(_find_forbidden_keys(nested))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_forbidden_keys(item))
    return found
