from __future__ import annotations

import pytest

from app.core.models import WarRoomScenarioRequest
from app.services.agent_runtime import AgentRuntimeConfig
from app.services.agent_runtime.models import AgentProviderResponse
from app.services.agent_runtime import orchestrator as runtime_orchestrator
from app.services.agent_runtime.mock_provider import DeterministicMockProvider
from app.services.plugin_sdk import (
    build_plugin_input,
    verify_stored_plugin_output,
)
from app.services.plugin_sdk.builtins import (
    AgentRuntimePluginOutputV1,
    ControlledAgentProviderAdapter,
    built_in_agent_provider_registry,
)
from app.services.war_room_engine import run_war_room


def _payload(adapter: ControlledAgentProviderAdapter, *, provider: str = "mock") -> dict:
    result = run_war_room(WarRoomScenarioRequest(seed=42))
    config = AgentRuntimeConfig(
        provider=provider,
        fallback_mode="skip" if provider != "mock" else "mock",
        max_calls=4,
        token_budget=20_000,
        seed=42,
    )
    return {
        "schema_version": "agent-runtime-request.v1",
        "run_id": "run_plugin_agent",
        "result": result.model_dump(mode="json"),
        "config": config.model_dump(mode="json"),
    }


def test_controlled_agent_provider_adapter_preserves_runtime_and_authority_boundary():
    adapter = ControlledAgentProviderAdapter()
    stored = adapter.execute(build_plugin_input(adapter.manifest, _payload(adapter)))
    output = AgentRuntimePluginOutputV1.model_validate(stored.payload)

    assert stored.provider_calls == 4
    assert output.runtime.mode == "mock"
    assert output.runtime.provider == "mock"
    assert len(output.runtime.proposals) == 4
    assert output.numeric_authority_written is False
    assert "risk_score" not in stored.model_dump_json()
    assert "supply_chain_pressure" not in stored.model_dump_json()
    assert output.runtime.runtime_hash
    assert verify_stored_plugin_output(
        adapter.manifest,
        stored,
        require_provider_free=True,
    ) == stored


def test_agent_provider_manifest_is_allowlisted_and_configuration_bound():
    adapter = ControlledAgentProviderAdapter()
    manifest = built_in_agent_provider_registry().resolve(
        "agent_provider.controlled_runtime",
        kind="agent_provider",
        required_capabilities=("action.proposal", "structured.output"),
        required_permissions=("agent.invoke",),
    )
    assert manifest == adapter.manifest
    assert manifest.verify_configuration(adapter.configuration()) == manifest
    assert "raw_prompt_persistence" in adapter.configuration()
    assert adapter.configuration()["raw_prompt_persistence"] is False


def test_disabled_live_provider_is_never_invoked(monkeypatch):
    class DisabledConfiguredProvider:
        def __init__(self, provider: str):
            self.name = provider
            self.model = "disabled-test-model"
            self.enabled = False

        def generate(self, _request):  # pragma: no cover - must never run
            raise AssertionError("disabled Agent Provider must not be invoked")

    monkeypatch.setattr(
        runtime_orchestrator,
        "ConfiguredLLMAgentProvider",
        DisabledConfiguredProvider,
    )
    adapter = ControlledAgentProviderAdapter()
    stored = adapter.execute(
        build_plugin_input(
            adapter.manifest,
            _payload(adapter, provider="deepseek"),
        )
    )
    output = AgentRuntimePluginOutputV1.model_validate(stored.payload)
    assert output.runtime.mode == "skipped"
    assert output.runtime.provider == "deepseek"
    assert output.runtime.proposals == []
    assert stored.provider_calls == 0


def test_adapter_preserves_stop_control_and_rejects_numeric_provider_output(
    monkeypatch,
):
    stopped = ControlledAgentProviderAdapter(should_stop=lambda: True)
    stopped_output = AgentRuntimePluginOutputV1.model_validate(
        stopped.execute(
            build_plugin_input(stopped.manifest, _payload(stopped))
        ).payload
    )
    assert stopped_output.runtime.mode == "skipped"
    assert stopped_output.runtime.total_calls == 0

    original_provider = DeterministicMockProvider()

    class NumericAuthorityProvider:
        name = "mock"
        model = "malicious-mock-test"
        enabled = True

        def generate(self, request):
            response = original_provider.generate(request)
            return AgentProviderResponse(
                provider=self.name,
                model=self.model,
                mode="mock",
                payload={**response.payload, "risk_score": 99},
                output_text=response.output_text,
            )

    monkeypatch.setattr(
        runtime_orchestrator,
        "DeterministicMockProvider",
        NumericAuthorityProvider,
    )
    adapter = ControlledAgentProviderAdapter()
    stored = adapter.execute(build_plugin_input(adapter.manifest, _payload(adapter)))
    output = AgentRuntimePluginOutputV1.model_validate(stored.payload)
    assert output.runtime.mode == "skipped"
    assert output.runtime.proposals == []
    assert output.runtime.failed_calls == 4
    assert output.numeric_authority_written is False


def test_provider_free_replay_does_not_call_runtime_and_tamper_fails(monkeypatch):
    adapter = ControlledAgentProviderAdapter()
    stored = adapter.execute(build_plugin_input(adapter.manifest, _payload(adapter)))

    def forbidden_runtime(*_args, **_kwargs):
        raise AssertionError("stored Agent Provider replay must not invoke runtime")

    monkeypatch.setattr(
        "app.services.plugin_sdk.builtins.agent_provider.run_agent_runtime",
        forbidden_runtime,
    )
    assert verify_stored_plugin_output(
        adapter.manifest,
        stored,
        require_provider_free=True,
    ) == stored

    tampered = stored.model_copy(
        update={
            "payload": {
                **stored.payload,
                "numeric_authority_written": True,
            }
        }
    )
    with pytest.raises(ValueError, match="payload hash mismatch"):
        verify_stored_plugin_output(adapter.manifest, tampered)
