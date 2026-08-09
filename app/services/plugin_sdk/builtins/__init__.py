"""Installed, auditable WorldPulse Plugin SDK implementations."""

from importlib import import_module
from typing import Any

from .data_connectors import (
    FredConnector,
    NoaaNasaConnector,
    WorldBankConnector,
    built_in_data_connector_registry,
    built_in_data_connectors,
)
from .agent_provider import (
    AgentRuntimePluginInputV1,
    AgentRuntimePluginOutputV1,
    ControlledAgentProviderAdapter,
    built_in_agent_provider,
    built_in_agent_provider_registry,
)
from .rule_pack import (
    ActiveRulePackAdapter,
    ActiveRulePackOutputV1,
    ActiveRulePackRequestV1,
    built_in_rule_pack,
    built_in_rule_pack_registry,
)
from .report_renderer import (
    MarkdownRenderOutputV1,
    MarkdownRenderRequestV1,
    ReportRendererAdapter,
    build_renderer_lineage,
    built_in_report_renderer_registry,
    installed_report_renderer_manifest,
    verify_renderer_lineage,
)


_LAZY_EVALUATOR_EXPORTS = {
    "EvaluationReportAdapter",
    "EvaluationReportOutputV1",
    "EvaluationReportRequestV1",
    "built_in_evaluator",
    "built_in_evaluator_registry",
}


def __getattr__(name: str) -> Any:
    if name not in _LAZY_EVALUATOR_EXPORTS:
        raise AttributeError(name)
    value = getattr(import_module(".evaluator", __name__), name)
    globals()[name] = value
    return value

__all__ = [
    "FredConnector",
    "NoaaNasaConnector",
    "WorldBankConnector",
    "built_in_data_connector_registry",
    "built_in_data_connectors",
    "AgentRuntimePluginInputV1",
    "AgentRuntimePluginOutputV1",
    "ControlledAgentProviderAdapter",
    "built_in_agent_provider",
    "built_in_agent_provider_registry",
    "ActiveRulePackAdapter",
    "ActiveRulePackOutputV1",
    "ActiveRulePackRequestV1",
    "built_in_rule_pack",
    "built_in_rule_pack_registry",
    "EvaluationReportAdapter",
    "EvaluationReportOutputV1",
    "EvaluationReportRequestV1",
    "built_in_evaluator",
    "built_in_evaluator_registry",
    "MarkdownRenderOutputV1",
    "MarkdownRenderRequestV1",
    "ReportRendererAdapter",
    "build_renderer_lineage",
    "built_in_report_renderer_registry",
    "installed_report_renderer_manifest",
    "verify_renderer_lineage",
]
