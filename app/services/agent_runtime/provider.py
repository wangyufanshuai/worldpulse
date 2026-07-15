from __future__ import annotations

import json
from typing import Protocol

from app.services.llm_client import LLMMessage, call_llm_json_for_provider, get_provider_config

from .models import AgentProviderRequest, AgentProviderResponse


class AgentProvider(Protocol):
    name: str
    model: str
    enabled: bool

    def generate(self, request: AgentProviderRequest) -> AgentProviderResponse: ...


class ProviderUnavailable(RuntimeError):
    pass


class ConfiguredLLMAgentProvider:
    def __init__(self, provider: str):
        if provider not in {"siliconflow", "deepseek"}:
            raise ValueError(f"Provider is not allowlisted: {provider}")
        self.config = get_provider_config(provider)
        self.name = self.config.provider
        self.model = self.config.model
        self.enabled = self.config.enabled

    def generate(self, request: AgentProviderRequest) -> AgentProviderResponse:
        if not self.enabled:
            raise ProviderUnavailable(f"{self.name} API key is not configured")
        result = call_llm_json_for_provider(
            self.name,
            [
                LLMMessage(role="system", content=request.system_prompt),
                LLMMessage(role="user", content=request.user_prompt),
            ],
            request.schema_hint,
            timeout=max(1, int(request.timeout_seconds)),
        )
        if not result.enabled:
            raise ProviderUnavailable(result.error or f"{self.name} returned no usable result")
        payload = json.loads(result.content)
        return AgentProviderResponse(
            provider=result.provider,
            model=result.model,
            mode="live",
            payload=payload,
            output_text=result.content,
        )
