from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.plugin_sdk import (
    PluginManifestError,
    PluginNotFoundError,
    PluginPermissionError,
    PluginRegistry,
    build_plugin_input,
    build_plugin_manifest,
    build_plugin_output,
)


def _manifest():
    return build_plugin_manifest(
        plugin_id="connector.fred",
        kind="connector",
        version="1.0.0",
        implementation_id="builtin.fred.csv",
        capabilities=("evidence.snapshot", "series.read"),
        permissions=("evidence.write", "network.read"),
        input_schema="connector-request.v1",
        output_schema="connector-output.v1",
        configuration={"series": ("VIXCLS", "SP500"), "timeout_seconds": 10},
    )


def test_manifest_and_envelopes_are_canonical_and_hash_bound():
    manifest = _manifest()
    assert manifest.verify_hash() == manifest
    assert manifest.configuration_hash

    input_envelope = build_plugin_input(
        manifest,
        {"cutoff_at": "2026-08-09T00:00:00Z", "series": ["VIXCLS"]},
        organization_id="org_default",
        run_id="run_plugin_contract",
    )
    assert input_envelope.verify_hash() == input_envelope
    output = build_plugin_output(
        manifest,
        input_envelope.invocation,
        {"observations": [], "source": "FRED"},
    )
    assert output.verify_hash() == output
    assert output.invocation.invocation_hash == input_envelope.invocation.invocation_hash


def test_manifest_mutations_and_noncanonical_declarations_fail_closed():
    manifest = _manifest()
    with pytest.raises(ValueError, match="manifest hash mismatch"):
        manifest.model_copy(update={"version": "1.0.1"}).verify_hash()
    with pytest.raises(ValueError, match="configuration hash mismatch"):
        manifest.verify_configuration({"timeout_seconds": 999})
    with pytest.raises(ValueError, match="sorted and unique"):
        build_plugin_manifest(
            plugin_id="connector.bad",
            kind="connector",
            version="1.0.0",
            implementation_id="builtin.bad",
            capabilities=("z", "a"),
            input_schema="connector-request.v1",
            output_schema="connector-output.v1",
            configuration={},
        )
    with pytest.raises(ValidationError):
        build_plugin_manifest(
            plugin_id="connector.bad",
            kind="connector",
            version="1.0.0",
            implementation_id="builtin.bad",
            capabilities=("series.read",),
            permissions=("filesystem.write",),  # type: ignore[arg-type]
            input_schema="connector-request.v1",
            output_schema="connector-output.v1",
            configuration={},
        )
    with pytest.raises(ValidationError):
        build_plugin_manifest(
            plugin_id="connector.future",
            kind="connector",
            version="1.0.0",
            implementation_id="builtin.future",
            capabilities=("series.read",),
            input_schema="connector-request.v2",
            output_schema="connector-output.v1",
            configuration={},
        )


def test_registry_is_explicit_sorted_and_requirement_checked():
    first = _manifest()
    second = build_plugin_manifest(
        plugin_id="agent.mock",
        kind="agent_provider",
        version="1.0.0",
        implementation_id="builtin.mock",
        capabilities=("action.proposal",),
        permissions=("agent.invoke",),
        input_schema="agent-request.v1",
        output_schema="agent-output.v1",
        configuration={"provider": "mock"},
    )
    registry = PluginRegistry((second, first))
    assert [item.plugin_id for item in registry.list_manifests()] == [
        "agent.mock",
        "connector.fred",
    ]
    assert registry.resolve(
        "connector.fred",
        kind="connector",
        required_capabilities=("series.read",),
        required_permissions=("network.read",),
    ) == first
    with pytest.raises(PluginNotFoundError):
        registry.resolve("connector.missing")
    with pytest.raises(PluginPermissionError):
        registry.resolve("connector.fred", required_permissions=("agent.invoke",))
    with pytest.raises(PluginManifestError):
        registry.resolve("connector.fred", kind="evaluator")
    with pytest.raises(PluginManifestError, match="already registered"):
        registry.register(first)
