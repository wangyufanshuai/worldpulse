from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext, ActionType, ActorType


class AgentRoleDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role_id: str
    actor_type: ActorType
    title_zh: str
    allowed_actions: list[ActionType]
    system_prompt: str
    prompt_version: str = "worldpulse-agent.v1"
    tools: list[str] = Field(default_factory=list)


class AgentRuntimeConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["mock", "siliconflow", "deepseek"] = "mock"
    model: str = "mock-deterministic-v1"
    max_turns: int = Field(default=1, ge=1, le=5)
    max_agents: int = Field(default=4, ge=1, le=8)
    timeout_seconds: float = Field(default=30, ge=0.05, le=120)
    max_calls: int = Field(default=8, ge=1, le=40)
    token_budget: int = Field(default=12000, ge=100, le=200000)
    max_input_chars: int = Field(default=16000, ge=1000, le=50000)
    max_output_chars: int = Field(default=6000, ge=500, le=20000)
    fallback_mode: Literal["mock", "skip"] = "mock"
    seed: int = 42


class AgentProviderRequest(BaseModel):
    run_id: str
    turn: int
    role: AgentRoleDefinition
    actor_id: str
    system_prompt: str
    user_prompt: str
    schema_hint: dict[str, Any]
    timeout_seconds: float
    mock_payload: dict[str, Any] | None = None


class AgentProviderResponse(BaseModel):
    provider: str
    model: str
    mode: Literal["live", "mock"]
    payload: dict[str, Any]
    output_text: str
    usage_tokens: int | None = None


class AgentInvocationAudit(BaseModel):
    schema_version: str = "agent-invocation-audit.v1"
    invocation_id: str
    run_id: str
    turn: int
    actor_id: str
    role_id: str
    provider: str
    model: str
    mode: str
    model_parameters: dict[str, Any] = Field(default_factory=dict)
    prompt_version: str
    prompt_hash: str
    response_hash: str | None = None
    status: Literal["completed", "failed", "timeout", "skipped"]
    input_chars: int
    output_chars: int = 0
    estimated_tokens: int = 0
    duration_ms: int = 0
    error_code: str | None = None
    error_message: str | None = None
    secret_redacted: bool = True
    created_at: str


class AgentRuntimeResult(BaseModel):
    schema_version: str = "agent-runtime-result.v1"
    run_id: str
    provider: str
    model: str
    mode: Literal["live", "mock", "skipped"]
    fallback_reason: str | None = None
    runtime_config: dict[str, Any] = Field(default_factory=dict)
    proposals: list[AgentActionProposal] = Field(default_factory=list)
    constraint_context: AgentConstraintContext
    invocations: list[AgentInvocationAudit] = Field(default_factory=list)
    total_calls: int = 0
    total_estimated_tokens: int = 0
    failed_calls: int = 0
    runtime_hash: str
