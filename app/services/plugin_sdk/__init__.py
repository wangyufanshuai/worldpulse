"""Pure, versioned contracts for the Phase 3 Plugin SDK."""

from .contracts import (
    PluginCapability,
    PluginInputEnvelope,
    PluginInvocation,
    PluginKind,
    PluginManifest,
    PluginOutputEnvelope,
    PluginPermission,
    build_plugin_manifest,
    build_plugin_input,
    build_plugin_output,
    canonical_hash,
)
from .registry import (
    PluginManifestError,
    PluginNotFoundError,
    PluginPermissionError,
    PluginRegistry,
)
from .verification import verify_plugin_input, verify_stored_plugin_output
from .ports import AgentProviderPluginPort, DataConnectorPluginPort

__all__ = [
    "PluginCapability",
    "PluginInputEnvelope",
    "PluginInvocation",
    "PluginKind",
    "PluginManifest",
    "PluginOutputEnvelope",
    "PluginPermission",
    "PluginManifestError",
    "PluginNotFoundError",
    "PluginPermissionError",
    "PluginRegistry",
    "build_plugin_manifest",
    "build_plugin_input",
    "build_plugin_output",
    "canonical_hash",
    "verify_plugin_input",
    "verify_stored_plugin_output",
    "AgentProviderPluginPort",
    "DataConnectorPluginPort",
]
