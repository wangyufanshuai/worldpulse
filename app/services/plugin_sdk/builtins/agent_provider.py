"""Plugin adapter for the existing controlled Agent Runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from app.core.models import WarRoomRun
from app.services.agent_contract.models import MockAgentBatch
from app.services.agent_runtime import (
    AgentRuntimeConfig,
    AgentRuntimeResult,
    run_agent_runtime,
)

from ..contracts import (
    PluginInputEnvelope,
    PluginManifest,
    PluginOutputEnvelope,
    build_plugin_manifest,
    build_plugin_output,
)
from ..registry import PluginRegistry
from ..verification import verify_plugin_input


class AgentRuntimePluginInputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agent-runtime-request.v1"] = (
        "agent-runtime-request.v1"
    )
    run_id: str
    result: WarRoomRun
    config: AgentRuntimeConfig


class AgentRuntimePluginOutputV1(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["agent-runtime-output.v1"] = (
        "agent-runtime-output.v1"
    )
    runtime: AgentRuntimeResult
    numeric_authority_written: Literal[False] = False


class ControlledAgentProviderAdapter:
    """Resolve the installed runtime without owning governance or world state."""

    plugin_id: ClassVar[str] = "agent_provider.controlled_runtime"
    implementation_id: ClassVar[str] = "builtin.agent_runtime.v1"
    _provider_allowlist: ClassVar[tuple[str, ...]] = (
        "deepseek",
        "mock",
        "siliconflow",
    )

    def __init__(
        self,
        *,
        should_stop: Callable[[], bool] | None = None,
        template_batch_factory: Callable[..., MockAgentBatch] | None = None,
    ) -> None:
        self._should_stop = should_stop
        self._template_batch_factory = template_batch_factory
        self._manifest = build_plugin_manifest(
            plugin_id=self.plugin_id,
            kind="agent_provider",
            version="1.0.0",
            implementation_id=self.implementation_id,
            capabilities=(
                "action.proposal",
                "provider.fallback",
                "structured.output",
            ),
            permissions=("agent.invoke",),
            input_schema="agent-runtime-request.v1",
            output_schema="agent-runtime-output.v1",
            configuration=self.configuration(),
        )

    @classmethod
    def configuration(cls) -> dict[str, Any]:
        return {
            "provider_allowlist": list(cls._provider_allowlist),
            "fallback_modes": ["mock", "skip"],
            "numeric_authority_write": False,
            "raw_prompt_persistence": False,
            "governance_handoff": [
                "consistency",
                "action_adapter",
                "commitment_ledger",
                "projection_audit",
            ],
        }

    @property
    def manifest(self) -> PluginManifest:
        return self._manifest

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope:
        self.manifest.verify_configuration(self.configuration())
        verified = verify_plugin_input(self.manifest, envelope)
        request = AgentRuntimePluginInputV1.model_validate(verified.payload)
        if request.schema_version != self.manifest.input_schema:
            raise ValueError("Agent Runtime input schema does not match manifest")
        if request.config.provider not in self._provider_allowlist:
            raise ValueError("Agent Runtime provider is not allowlisted")
        runtime = run_agent_runtime(
            request.result,
            run_id=request.run_id,
            config=request.config,
            should_stop=self._should_stop,
            template_batch_factory=self._template_batch_factory,
        )
        if runtime.run_id != request.run_id:
            raise ValueError("Agent Runtime returned a mismatched run_id")
        output = AgentRuntimePluginOutputV1(runtime=runtime)
        return build_plugin_output(
            self.manifest,
            verified.invocation,
            output.model_dump(mode="json"),
            provider_calls=runtime.total_calls,
        )


def built_in_agent_provider() -> ControlledAgentProviderAdapter:
    return ControlledAgentProviderAdapter()


def built_in_agent_provider_registry() -> PluginRegistry:
    adapter = built_in_agent_provider()
    return PluginRegistry((adapter.manifest,))
