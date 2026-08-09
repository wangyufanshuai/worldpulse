"""Closed, hash-addressed Plugin SDK contracts.

This module deliberately has no database, network, provider or Kernel imports.
It can therefore be used by adapters without weakening deterministic replay or
the V2 authority boundary.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


PluginKind = Literal[
    "connector",
    "extractor",
    "agent_provider",
    "rule_pack",
    "evaluator",
    "report_renderer",
]
PluginPermission = Literal[
    "network.read",
    "evidence.read",
    "evidence.write",
    "agent.invoke",
    "rule_pack.read",
    "evaluation.read",
    "report.render",
]
PluginCapability = str

_HEX64 = r"^[0-9a-f]{64}$"
_ID = r"^[a-z][a-z0-9_.-]{2,79}$"
_SCHEMA = r"^[a-z][a-z0-9_.-]{1,79}\.v1$"
_CAPABILITY = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")


def _canonical_hash(value: Any) -> str:
    body = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _ensure_sorted_unique(values: tuple[str, ...], field_name: str) -> tuple[str, ...]:
    if not values or any(not item.strip() for item in values):
        raise ValueError(f"{field_name} must contain non-empty values")
    if field_name == "capabilities" and any(
        _CAPABILITY.fullmatch(item) is None for item in values
    ):
        raise ValueError("capabilities must contain canonical capability tokens")
    if tuple(sorted(set(values))) != values:
        raise ValueError(f"{field_name} must be sorted and unique")
    return values


class PluginManifest(BaseModel):
    """Immutable identity and capability declaration for one installed plugin."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["plugin-manifest.v1"] = "plugin-manifest.v1"
    plugin_id: str = Field(pattern=_ID)
    kind: PluginKind
    version: str = Field(min_length=1, max_length=80)
    implementation_id: str = Field(pattern=_ID)
    capabilities: tuple[PluginCapability, ...] = Field(min_length=1, max_length=64)
    permissions: tuple[PluginPermission, ...] = Field(default=(), max_length=16)
    input_schema: str = Field(pattern=_SCHEMA)
    output_schema: str = Field(pattern=_SCHEMA)
    configuration_hash: str = Field(pattern=_HEX64)
    manifest_hash: str = Field(pattern=_HEX64)

    @field_validator("capabilities")
    @classmethod
    def _validate_capabilities(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ensure_sorted_unique(value, "capabilities")

    @field_validator("permissions")
    @classmethod
    def _validate_permissions(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return _ensure_sorted_unique(value, "permissions") if value else value

    def preimage(self) -> dict[str, Any]:
        """Return the exact payload authenticated by ``manifest_hash``."""

        return self.model_dump(mode="json", exclude={"manifest_hash"})

    def verify_hash(self) -> "PluginManifest":
        expected = _canonical_hash(self.preimage())
        if expected != self.manifest_hash:
            raise ValueError("plugin manifest hash mismatch")
        return self

    def verify_configuration(self, configuration: Any) -> "PluginManifest":
        """Verify runtime configuration against the manifest-pinned digest."""

        if _canonical_hash(configuration) != self.configuration_hash:
            raise ValueError("plugin configuration hash mismatch")
        return self.verify_hash()


class PluginInvocation(BaseModel):
    """Attempt-scoped, provider-neutral identity for one plugin call."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["plugin-invocation.v1"] = "plugin-invocation.v1"
    plugin_id: str = Field(pattern=_ID)
    plugin_version: str = Field(min_length=1, max_length=80)
    manifest_hash: str = Field(pattern=_HEX64)
    configuration_hash: str = Field(pattern=_HEX64)
    organization_id: str | None = Field(default=None, pattern=_ID)
    run_id: str | None = Field(default=None, pattern=_ID)
    input_hash: str = Field(pattern=_HEX64)
    invocation_hash: str = Field(pattern=_HEX64)

    def preimage(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude={"invocation_hash"})

    def verify_hash(self) -> "PluginInvocation":
        expected = _canonical_hash(self.preimage())
        if expected != self.invocation_hash:
            raise ValueError("plugin invocation hash mismatch")
        return self


class PluginInputEnvelope(BaseModel):
    """Schema-labelled input that can be persisted without raw provider state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["plugin-input.v1"] = "plugin-input.v1"
    invocation: PluginInvocation
    input_schema: str = Field(pattern=_SCHEMA)
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=_HEX64)

    def verify_hash(self) -> "PluginInputEnvelope":
        if _canonical_hash(self.payload) != self.payload_hash:
            raise ValueError("plugin input payload hash mismatch")
        self.invocation.verify_hash()
        return self


class PluginOutputEnvelope(BaseModel):
    """Schema-labelled output with explicit provider-call accounting."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["plugin-output.v1"] = "plugin-output.v1"
    invocation: PluginInvocation
    output_schema: str = Field(pattern=_SCHEMA)
    payload: dict[str, Any]
    payload_hash: str = Field(pattern=_HEX64)
    provider_calls: int = Field(default=0, ge=0, le=1000)

    def verify_hash(self) -> "PluginOutputEnvelope":
        if _canonical_hash(self.payload) != self.payload_hash:
            raise ValueError("plugin output payload hash mismatch")
        self.invocation.verify_hash()
        return self


def build_plugin_manifest(
    *,
    plugin_id: str,
    kind: PluginKind,
    version: str,
    implementation_id: str,
    capabilities: tuple[PluginCapability, ...],
    permissions: tuple[PluginPermission, ...] = (),
    input_schema: str,
    output_schema: str,
    configuration: Any,
) -> PluginManifest:
    """Build and authenticate a canonical manifest from configuration."""

    configuration_hash = _canonical_hash(configuration)
    preimage = {
        "schema_version": "plugin-manifest.v1",
        "plugin_id": plugin_id,
        "kind": kind,
        "version": version,
        "implementation_id": implementation_id,
        "capabilities": list(capabilities),
        "permissions": list(permissions),
        "input_schema": input_schema,
        "output_schema": output_schema,
        "configuration_hash": configuration_hash,
    }
    return PluginManifest(
        **preimage,
        manifest_hash=_canonical_hash(preimage),
    ).verify_hash()


def build_plugin_input(
    manifest: PluginManifest,
    payload: dict[str, Any],
    *,
    organization_id: str | None = None,
    run_id: str | None = None,
) -> PluginInputEnvelope:
    """Create an invocation envelope bound to the manifest and input payload."""

    manifest.verify_hash()
    payload_hash = _canonical_hash(payload)
    invocation_preimage = {
        "schema_version": "plugin-invocation.v1",
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.version,
        "manifest_hash": manifest.manifest_hash,
        "configuration_hash": manifest.configuration_hash,
        "organization_id": organization_id,
        "run_id": run_id,
        "input_hash": payload_hash,
    }
    invocation = PluginInvocation(
        **invocation_preimage,
        invocation_hash=_canonical_hash(invocation_preimage),
    ).verify_hash()
    return PluginInputEnvelope(
        invocation=invocation,
        input_schema=manifest.input_schema,
        payload=payload,
        payload_hash=payload_hash,
    ).verify_hash()


def build_plugin_output(
    manifest: PluginManifest,
    invocation: PluginInvocation,
    payload: dict[str, Any],
    *,
    provider_calls: int = 0,
) -> PluginOutputEnvelope:
    """Create an output envelope and require the invocation to match the manifest."""

    manifest.verify_hash()
    invocation.verify_hash()
    if (
        invocation.plugin_id != manifest.plugin_id
        or invocation.plugin_version != manifest.version
        or invocation.manifest_hash != manifest.manifest_hash
        or invocation.configuration_hash != manifest.configuration_hash
    ):
        raise ValueError("plugin output invocation does not match manifest")
    return PluginOutputEnvelope(
        invocation=invocation,
        output_schema=manifest.output_schema,
        payload=payload,
        payload_hash=_canonical_hash(payload),
        provider_calls=provider_calls,
    ).verify_hash()
