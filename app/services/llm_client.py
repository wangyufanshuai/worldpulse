from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class LLMProviderConfig:
    provider: str
    api_key: str | None
    base_url: str
    model: str

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)


@dataclass(frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(frozen=True)
class LLMResult:
    enabled: bool
    provider: str
    model: str
    mode: str
    content: str
    error: str | None = None


DEFAULTS = {
    "siliconflow": {
        "base_url": "https://api.siliconflow.com/v1",
        "model": "deepseek-ai/DeepSeek-V3",
        "key_env": "SILICONFLOW_API_KEY",
        "base_env": "SILICONFLOW_BASE_URL",
        "model_env": "SILICONFLOW_MODEL",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "key_env": "DEEPSEEK_API_KEY",
        "base_env": "DEEPSEEK_BASE_URL",
        "model_env": "DEEPSEEK_MODEL",
    },
}


def get_provider_config(provider: str | None = None) -> LLMProviderConfig:
    normalized = (provider or os.getenv("AI_PROVIDER") or "siliconflow").lower()
    if normalized not in DEFAULTS:
        normalized = "siliconflow"
    defaults = DEFAULTS[normalized]
    return LLMProviderConfig(
        provider=normalized,
        api_key=os.getenv(defaults["key_env"]),
        base_url=os.getenv(defaults["base_env"], defaults["base_url"]).rstrip("/"),
        model=os.getenv(defaults["model_env"], defaults["model"]),
    )


def get_llm_status() -> dict[str, Any]:
    primary = get_provider_config()
    fallback_provider = (os.getenv("AI_FALLBACK_PROVIDER") or "deepseek").lower()
    fallback = get_provider_config(fallback_provider)
    enabled = primary.enabled or fallback.enabled
    return {
        "enabled": enabled,
        "provider": primary.provider,
        "model": primary.model,
        "base_url": primary.base_url,
        "provider_enabled": primary.enabled,
        "fallback_provider": fallback.provider,
        "fallback_model": fallback.model,
        "fallback_enabled": fallback.enabled,
        "mode": "live" if enabled else "disabled",
    }


def call_llm_json(messages: list[LLMMessage], schema_hint: dict[str, Any], timeout: int = 45) -> LLMResult:
    providers = _provider_chain()
    errors: list[str] = []
    for config in providers:
        if not config.enabled:
            errors.append(f"{config.provider} API key not configured")
            continue
        try:
            payload = {
                "model": config.model,
                "messages": [{"role": message.role, "content": message.content} for message in messages],
                "temperature": 0.2,
                "max_tokens": int(os.getenv("AI_MAX_TOKENS", "1800")),
                "stream": False,
            }
            if os.getenv("AI_USE_RESPONSE_FORMAT", "true").lower() != "false":
                payload["response_format"] = {"type": "json_object"}
            response = _post_chat_completion(config, payload, timeout)
            content = _extract_chat_content(response.json())
            try:
                parsed = extract_json(content)
            except Exception:
                parsed = {"summary": content.strip()}
            _validate_required_keys(parsed, schema_hint)
            return LLMResult(enabled=True, provider=config.provider, model=config.model, mode="live", content=json.dumps(parsed, ensure_ascii=False))
        except Exception as exc:
            errors.append(f"{config.provider}: {type(exc).__name__}: {exc}")
    fallback = providers[-1] if providers else get_provider_config("siliconflow")
    return LLMResult(enabled=False, provider=fallback.provider, model=fallback.model, mode="disabled", content="", error=" | ".join(errors) if errors else None)


def extract_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("{"):
        return json.loads(stripped)
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", stripped, flags=re.DOTALL)
    if fenced:
        return json.loads(fenced.group(1))
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start >= 0 and end > start:
        return json.loads(stripped[start : end + 1])
    raise ValueError("LLM output does not contain JSON object")


def _provider_chain() -> list[LLMProviderConfig]:
    primary = get_provider_config()
    fallback_name = (os.getenv("AI_FALLBACK_PROVIDER") or "deepseek").lower()
    fallback = get_provider_config(fallback_name)
    return [primary] if fallback.provider == primary.provider else [primary, fallback]


def _extract_chat_content(payload: dict[str, Any]) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise ValueError("chat completion response has no choices")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if not content:
        raise ValueError("chat completion response has no message content")
    return str(content)


def _post_chat_completion(config: LLMProviderConfig, payload: dict[str, Any], timeout: int) -> requests.Response:
    url = f"{config.base_url}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key}", "Content-Type": "application/json"}
    response = requests.post(url, headers=headers, json=payload, timeout=timeout)
    if response.status_code < 400:
        return response
    if response.status_code in {400, 422} and "response_format" in payload:
        retry_payload = dict(payload)
        retry_payload.pop("response_format", None)
        response = requests.post(url, headers=headers, json=retry_payload, timeout=timeout)
    response.raise_for_status()
    return response


def _validate_required_keys(payload: dict[str, Any], schema_hint: dict[str, Any]) -> None:
    required = schema_hint.get("required") or []
    missing = [key for key in required if key not in payload]
    if missing:
        raise ValueError(f"LLM JSON missing required keys: {', '.join(missing)}")
