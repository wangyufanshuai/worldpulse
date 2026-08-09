"""Provider-free verification helpers for Plugin SDK envelopes."""

from __future__ import annotations

from .contracts import PluginInputEnvelope, PluginManifest, PluginOutputEnvelope


def _verify_invocation_binding(manifest: PluginManifest, invocation) -> None:
    manifest.verify_hash()
    invocation.verify_hash()
    if (
        invocation.plugin_id != manifest.plugin_id
        or invocation.plugin_version != manifest.version
        or invocation.manifest_hash != manifest.manifest_hash
        or invocation.configuration_hash != manifest.configuration_hash
    ):
        raise ValueError("plugin invocation does not match manifest")


def verify_plugin_input(
    manifest: PluginManifest,
    envelope: PluginInputEnvelope,
) -> PluginInputEnvelope:
    """Verify an input envelope before an adapter touches external state."""

    envelope.verify_hash()
    _verify_invocation_binding(manifest, envelope.invocation)
    if envelope.input_schema != manifest.input_schema:
        raise ValueError("plugin input schema does not match manifest")
    return envelope


def verify_stored_plugin_output(
    manifest: PluginManifest,
    envelope: PluginOutputEnvelope,
    *,
    require_provider_free: bool = False,
) -> PluginOutputEnvelope:
    """Authenticate stored output without invoking the plugin implementation."""

    envelope.verify_hash()
    _verify_invocation_binding(manifest, envelope.invocation)
    if envelope.output_schema != manifest.output_schema:
        raise ValueError("plugin output schema does not match manifest")
    if require_provider_free and envelope.provider_calls != 0:
        raise ValueError("stored plugin replay requires zero provider calls")
    return envelope
