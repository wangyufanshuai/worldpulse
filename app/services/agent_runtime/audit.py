from __future__ import annotations

from datetime import datetime

from app.services.consistency.hashing import stable_hash
from app.services.security import redact_secrets

from .models import AgentInvocationAudit, AgentProviderRequest


def invocation_audit(
    request: AgentProviderRequest,
    *,
    provider: str,
    model: str,
    mode: str,
    status: str,
    input_tokens: int,
    output_chars: int = 0,
    output_tokens: int = 0,
    duration_ms: int = 0,
    response_text: str | None = None,
    error: Exception | None = None,
) -> AgentInvocationAudit:
    prompt_hash = stable_hash({"system": request.system_prompt, "user": request.user_prompt})
    identity = {
        "run_id": request.run_id,
        "turn": request.turn,
        "actor_id": request.actor_id,
        "role_id": request.role.role_id,
        "prompt_hash": prompt_hash,
    }
    return AgentInvocationAudit(
        invocation_id=f"invoke_{stable_hash(identity)[:16]}",
        run_id=request.run_id,
        turn=request.turn,
        actor_id=request.actor_id,
        role_id=request.role.role_id,
        provider=provider,
        model=model,
        mode=mode,
        model_parameters={
            "structured_output": True,
            "temperature": 0.0 if mode == "mock" else 0.2,
            "timeout_seconds": request.timeout_seconds,
            "tool_allowlist": request.role.tools,
        },
        prompt_version=request.role.prompt_version,
        prompt_hash=prompt_hash,
        response_hash=stable_hash(response_text) if response_text else None,
        status=status,
        input_chars=len(request.system_prompt) + len(request.user_prompt),
        output_chars=output_chars,
        estimated_tokens=input_tokens + output_tokens,
        duration_ms=max(0, duration_ms),
        error_code=type(error).__name__ if error else None,
        error_message=redact_secrets(str(error)) if error else None,
        created_at=datetime.now().isoformat(timespec="milliseconds"),
    )
