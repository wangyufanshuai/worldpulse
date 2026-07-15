from time import sleep

import pytest
from pydantic import ValidationError

from app.core.models import WarRoomScenarioRequest
from app.services.agent_runtime import AgentRuntimeConfig, run_agent_runtime
from app.services.agent_runtime.action_parser import parse_action_proposal
from app.services.agent_runtime.context_builder import build_provider_request
from app.services.agent_runtime.mock_provider import DeterministicMockProvider
from app.services.agent_runtime.models import AgentProviderResponse
from app.services.agent_runtime.registry import role_for_actor_type
from app.services.agent_contract import build_mock_agent_batch
from app.services.war_room_engine import run_war_room


def _result():
    return run_war_room(WarRoomScenarioRequest(seed=42))


def test_runtime_provider_allowlist_and_repeatable_mock_hash():
    with pytest.raises(ValidationError):
        AgentRuntimeConfig(provider="arbitrary-network-provider")
    config = AgentRuntimeConfig(provider="mock", max_calls=4, token_budget=20000, seed=42)
    first = run_agent_runtime(_result(), run_id="job_one", config=config)
    second = run_agent_runtime(_result(), run_id="job_two", config=config)

    assert first.mode == "mock"
    assert first.total_calls == 4
    assert first.runtime_hash == second.runtime_hash
    assert [item.proposal_id for item in first.proposals] == [item.proposal_id for item in second.proposals]
    assert all(item.status == "completed" for item in first.invocations)
    assert all(item.prompt_hash and item.response_hash for item in first.invocations)


def test_runtime_call_and_token_budgets_stop_invocation():
    result = run_agent_runtime(
        _result(),
        run_id="job_budget",
        config=AgentRuntimeConfig(provider="mock", max_calls=1, token_budget=100, max_agents=4),
    )
    assert result.mode == "skipped"
    assert result.total_calls == 0
    assert result.proposals == []
    assert result.invocations[0].status == "skipped"
    assert result.invocations[0].error_code == "RuntimeError"


class PartialFailureProvider:
    name = "deepseek"
    model = "fake-structured-model"
    enabled = True

    def generate(self, request):
        if request.role.role_id == "diplomacy":
            raise RuntimeError("Bearer token-for-redaction-test must never be persisted")
        mock = DeterministicMockProvider().generate(request)
        return AgentProviderResponse(
            provider=self.name,
            model=self.model,
            mode="live",
            payload=mock.payload,
            output_text=mock.output_text,
        )


def test_single_agent_failure_is_isolated_and_secrets_are_redacted():
    runtime = run_agent_runtime(
        _result(),
        run_id="job_partial_failure",
        config=AgentRuntimeConfig(provider="deepseek", fallback_mode="skip", max_calls=4, token_budget=20000),
        provider=PartialFailureProvider(),
    )
    assert runtime.mode == "live"
    assert len(runtime.proposals) == 3
    assert runtime.failed_calls == 1
    failed = next(item for item in runtime.invocations if item.status == "failed")
    assert failed.error_message == "[REDACTED] must never be persisted"
    serialized = runtime.model_dump_json()
    assert "token-for-redaction-test" not in serialized
    assert "UNTRUSTED_WORLD_STATE" not in serialized
    assert runtime.runtime_config["provider"] == "deepseek"
    assert all(item.model_parameters["structured_output"] is True for item in runtime.invocations)
    assert all(item.model_parameters["tool_allowlist"] == [] for item in runtime.invocations)


class SlowProvider:
    name = "deepseek"
    model = "slow-test-model"
    enabled = True

    def generate(self, request):
        sleep(0.2)
        return DeterministicMockProvider().generate(request)


def test_runtime_timeout_is_audited_without_destroying_baseline():
    runtime = run_agent_runtime(
        _result(),
        run_id="job_timeout",
        config=AgentRuntimeConfig(provider="deepseek", fallback_mode="skip", max_agents=1, max_calls=1, timeout_seconds=0.05, token_budget=20000),
        provider=SlowProvider(),
    )
    assert runtime.mode == "skipped"
    assert runtime.proposals == []
    assert runtime.failed_calls == 1
    assert runtime.invocations[0].status == "timeout"


def test_action_parser_rejects_provider_numeric_authority_output():
    result = _result()
    batch = build_mock_agent_batch(result, run_id="job_parser", seed=42)
    template = batch.proposals[0]
    role = role_for_actor_type(template.actor_type)
    request = build_provider_request(
        result,
        run_id="job_parser",
        turn=1,
        role=role,
        actor_id=template.actor_id,
        timeout_seconds=1,
        max_input_chars=16000,
        mock_payload=template.model_dump(mode="json"),
    )
    payload = DeterministicMockProvider().generate(request).payload
    payload["risk_score"] = 90
    with pytest.raises(ValueError, match="forbidden or unknown"):
        parse_action_proposal(payload, request, seed=42)


class DisabledProvider:
    name = "deepseek"
    model = "disabled-test-model"
    enabled = False

    def generate(self, request):  # pragma: no cover - must never run
        raise AssertionError("disabled provider must not be invoked")


def test_unavailable_live_provider_falls_back_to_deterministic_mock():
    runtime = run_agent_runtime(
        _result(),
        run_id="job_provider_fallback",
        config=AgentRuntimeConfig(provider="deepseek", fallback_mode="mock", max_calls=4, token_budget=20000),
        provider=DisabledProvider(),
    )
    assert runtime.mode == "mock"
    assert runtime.provider == "mock"
    assert len(runtime.proposals) == 4
    assert "unavailable" in runtime.fallback_reason


def test_runtime_obeys_lifecycle_stop_callback_before_agent_calls():
    runtime = run_agent_runtime(
        _result(),
        run_id="job_cancelled_before_agents",
        config=AgentRuntimeConfig(provider="mock", max_calls=4, token_budget=20000),
        should_stop=lambda: True,
    )
    assert runtime.mode == "skipped"
    assert runtime.total_calls == 0
    assert runtime.proposals == []
