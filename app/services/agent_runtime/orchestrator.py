from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
import os
from time import perf_counter
from collections.abc import Callable

from app.core.models import WarRoomRun
from app.services.agent_contract import build_mock_agent_batch
from app.services.agent_contract.models import AgentActionProposal, AgentConstraintContext
from app.services.consistency.hashing import stable_hash

from .action_parser import parse_action_proposal
from .audit import invocation_audit
from .budget import RuntimeBudget, estimate_tokens
from .context_builder import build_provider_request
from .mock_provider import DeterministicMockProvider
from .models import AgentInvocationAudit, AgentRuntimeConfig, AgentRuntimeResult
from .provider import AgentProvider, ConfiguredLLMAgentProvider
from .registry import role_for_actor_type


def runtime_config_from_env(seed: int | None = None, overrides: dict | None = None) -> AgentRuntimeConfig:
    provider = str(os.getenv("AGENT_PROVIDER", "mock")).lower()
    if provider not in {"mock", "siliconflow", "deepseek"}:
        provider = "mock"
    default_model = "mock-deterministic-v1" if provider == "mock" else "configured-provider-default"
    model = str(os.getenv("AGENT_MODEL", default_model)).strip()[:120] or default_model
    values = {
        "provider": provider,
        "model": model,
        "max_turns": _env_int("AGENT_MAX_TURNS", 1, 1, 5),
        "max_agents": _env_int("AGENT_MAX_AGENTS", 4, 1, 8),
        "timeout_seconds": _env_float("AGENT_TIMEOUT_SECONDS", 30, 0.05, 120),
        "max_calls": _env_int("AGENT_MAX_CALLS", 8, 1, 40),
        "token_budget": _env_int("AGENT_TOKEN_BUDGET", 12000, 100, 200000),
        "max_input_chars": _env_int("AGENT_MAX_INPUT_CHARS", 16000, 1000, 50000),
        "max_output_chars": _env_int("AGENT_MAX_OUTPUT_CHARS", 6000, 500, 20000),
        "fallback_mode": _fallback_mode(),
        "seed": int(seed) if seed is not None else _env_int("AGENT_SEED", 42, -2147483648, 2147483647),
    }
    if overrides:
        allowed = set(values)
        values.update({key: value for key, value in overrides.items() if key in allowed and value is not None})
    return AgentRuntimeConfig(
        **values,
    )


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _fallback_mode() -> str:
    value = str(os.getenv("AGENT_FALLBACK_MODE", "mock")).lower()
    return value if value in {"mock", "skip"} else "mock"


def run_agent_runtime(
    result: WarRoomRun,
    *,
    run_id: str,
    config: AgentRuntimeConfig | None = None,
    provider: AgentProvider | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> AgentRuntimeResult:
    config = config or runtime_config_from_env()
    selected, fallback_reason = _select_provider(config, provider)
    proposals, context, invocations, budget = _execute(result, run_id, config, selected, should_stop=should_stop)

    stopped = bool(should_stop and should_stop())
    if not stopped and not proposals and selected.name != "mock" and config.fallback_mode == "mock" and budget.calls < config.max_calls:
        fallback_reason = fallback_reason or f"{selected.name} produced no valid proposals"
        mock_proposals, mock_context, mock_invocations, budget = _execute(
            result,
            run_id,
            config,
            DeterministicMockProvider(),
            budget=budget,
            should_stop=should_stop,
        )
        proposals.extend(mock_proposals)
        invocations.extend(mock_invocations)
        context = mock_context
        selected = DeterministicMockProvider()

    mode = "mock" if selected.name == "mock" and proposals else "live" if proposals else "skipped"
    runtime_identity = {
        "provider": selected.name,
        "model": selected.model,
        "mode": mode,
        "proposal_ids": [proposal.proposal_id for proposal in proposals],
        "invocations": [
            {
                "turn": item.turn,
                "actor_id": item.actor_id,
                "role_id": item.role_id,
                "provider": item.provider,
                "model": item.model,
                "prompt_version": item.prompt_version,
                "prompt_hash": item.prompt_hash,
                "response_hash": item.response_hash,
                "status": item.status,
                "error_code": item.error_code,
            }
            for item in invocations
        ],
    }
    return AgentRuntimeResult(
        run_id=run_id,
        provider=selected.name,
        model=selected.model,
        mode=mode,
        fallback_reason=fallback_reason,
        runtime_config=config.model_dump(mode="json"),
        proposals=proposals,
        constraint_context=context,
        invocations=invocations,
        total_calls=budget.calls,
        total_estimated_tokens=budget.tokens,
        failed_calls=sum(1 for item in invocations if item.status in {"failed", "timeout"}),
        runtime_hash=stable_hash(runtime_identity),
    )


def _select_provider(config: AgentRuntimeConfig, provider: AgentProvider | None) -> tuple[AgentProvider, str | None]:
    if provider is not None:
        if provider.name not in {"mock", "siliconflow", "deepseek"}:
            raise ValueError(f"Provider is not allowlisted: {provider.name}")
        if provider.enabled:
            return provider, None
        if config.fallback_mode == "mock":
            return DeterministicMockProvider(), f"{provider.name} is unavailable; using deterministic mock fallback"
        return provider, f"{provider.name} is unavailable and fallback is disabled"
    if config.provider == "mock":
        return DeterministicMockProvider(), None
    live = ConfiguredLLMAgentProvider(config.provider)
    if live.enabled:
        return live, None
    if config.fallback_mode == "mock":
        return DeterministicMockProvider(), f"{live.name} API key is not configured; using deterministic mock fallback"
    return live, f"{live.name} API key is not configured and fallback is disabled"


def _execute(
    result: WarRoomRun,
    run_id: str,
    config: AgentRuntimeConfig,
    provider: AgentProvider,
    *,
    budget: RuntimeBudget | None = None,
    should_stop: Callable[[], bool] | None = None,
) -> tuple[list[AgentActionProposal], AgentConstraintContext, list[AgentInvocationAudit], RuntimeBudget]:
    budget = budget or RuntimeBudget(config.max_calls, config.token_budget)
    proposals: list[AgentActionProposal] = []
    invocations: list[AgentInvocationAudit] = []
    combined_capabilities: dict = {}
    combined_budgets: dict = {}
    known_entities: set[str] = set()
    known_evidence: set[str] = set()

    if not provider.enabled:
        empty = build_mock_agent_batch(result, run_id=run_id, seed=config.seed)
        return [], empty.constraint_context, [], budget

    stop_for_budget = False
    for turn in range(1, config.max_turns + 1):
        if should_stop and should_stop():
            break
        batch = build_mock_agent_batch(result, run_id=run_id, seed=config.seed, turn=turn)
        combined_capabilities.update(batch.constraint_context.actor_capabilities)
        combined_budgets.update(batch.constraint_context.action_budgets)
        known_entities.update(batch.constraint_context.known_entities)
        known_evidence.update(batch.constraint_context.known_evidence_refs)
        for template in batch.proposals[: config.max_agents]:
            if should_stop and should_stop():
                stop_for_budget = True
                break
            role = role_for_actor_type(template.actor_type)
            if role is None or not role.allowed_actions:
                continue
            request = build_provider_request(
                result,
                run_id=run_id,
                turn=turn,
                role=role,
                actor_id=template.actor_id,
                timeout_seconds=config.timeout_seconds,
                max_input_chars=config.max_input_chars,
                mock_payload=template.model_dump(mode="json"),
            )
            input_tokens = estimate_tokens(request.system_prompt, request.user_prompt)
            if not budget.can_start(input_tokens):
                invocations.append(invocation_audit(
                    request,
                    provider=provider.name,
                    model=provider.model,
                    mode="mock" if provider.name == "mock" else "live",
                    status="skipped",
                    input_tokens=input_tokens,
                    error=RuntimeError("Agent runtime call/token budget exhausted"),
                ))
                stop_for_budget = True
                break
            started = perf_counter()
            try:
                response = _invoke_with_timeout(provider, request, config.timeout_seconds)
                if len(response.output_text) > config.max_output_chars:
                    raise ValueError("Agent provider output exceeds max_output_chars")
                proposal = parse_action_proposal(response.payload, request, seed=config.seed)
                output_tokens = response.usage_tokens if response.usage_tokens is not None else estimate_tokens(response.output_text)
                budget.consume(input_tokens, output_tokens)
                proposals.append(proposal)
                invocations.append(invocation_audit(
                    request,
                    provider=response.provider,
                    model=response.model,
                    mode=response.mode,
                    status="completed",
                    input_tokens=input_tokens,
                    output_chars=len(response.output_text),
                    output_tokens=output_tokens,
                    duration_ms=int((perf_counter() - started) * 1000),
                    response_text=response.output_text,
                ))
            except FutureTimeoutError as exc:
                budget.consume(input_tokens, 0)
                invocations.append(invocation_audit(
                    request,
                    provider=provider.name,
                    model=provider.model,
                    mode="mock" if provider.name == "mock" else "live",
                    status="timeout",
                    input_tokens=input_tokens,
                    duration_ms=int((perf_counter() - started) * 1000),
                    error=exc,
                ))
            except Exception as exc:
                budget.consume(input_tokens, 0)
                invocations.append(invocation_audit(
                    request,
                    provider=provider.name,
                    model=provider.model,
                    mode="mock" if provider.name == "mock" else "live",
                    status="failed",
                    input_tokens=input_tokens,
                    duration_ms=int((perf_counter() - started) * 1000),
                    error=exc,
                ))
        if stop_for_budget:
            break

    context = AgentConstraintContext(
        actor_capabilities=combined_capabilities,
        action_budgets=combined_budgets,
        known_entities=sorted(known_entities),
        known_evidence_refs=sorted(known_evidence),
        source_label="explicit simulation capability envelope",
    )
    return proposals, context, invocations, budget


def _invoke_with_timeout(provider: AgentProvider, request, timeout_seconds: float):
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(provider.generate, request)
    try:
        return future.result(timeout=timeout_seconds)
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
