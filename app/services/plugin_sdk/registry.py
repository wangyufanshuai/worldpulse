"""Deterministic, allowlisted Plugin SDK manifest registry."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import PluginCapability, PluginKind, PluginManifest, PluginPermission


class PluginManifestError(ValueError):
    """Raised when a plugin descriptor is malformed or tampered."""


class PluginNotFoundError(LookupError):
    """Raised when a plugin is not explicitly registered."""


class PluginPermissionError(PermissionError):
    """Raised when a caller asks for capabilities outside the manifest."""


class PluginRegistry:
    """In-memory registry with explicit registration and fail-closed resolution."""

    def __init__(self, manifests: Iterable[PluginManifest] = ()) -> None:
        self._manifests: dict[str, PluginManifest] = {}
        for manifest in manifests:
            self.register(manifest)

    def register(self, manifest: PluginManifest) -> PluginManifest:
        try:
            manifest.verify_hash()
        except ValueError as exc:
            raise PluginManifestError(str(exc)) from exc
        existing = self._manifests.get(manifest.plugin_id)
        if existing is not None:
            raise PluginManifestError(
                f"plugin id already registered: {manifest.plugin_id}"
            )
        self._manifests[manifest.plugin_id] = manifest
        return manifest

    def resolve(
        self,
        plugin_id: str,
        *,
        kind: PluginKind | None = None,
        required_capabilities: Iterable[PluginCapability] = (),
        required_permissions: Iterable[PluginPermission] = (),
    ) -> PluginManifest:
        manifest = self._manifests.get(plugin_id)
        if manifest is None:
            raise PluginNotFoundError(f"unknown plugin: {plugin_id}")
        try:
            manifest.verify_hash()
        except ValueError as exc:
            raise PluginManifestError(str(exc)) from exc
        if kind is not None and manifest.kind != kind:
            raise PluginManifestError(
                f"plugin kind mismatch for {plugin_id}: {manifest.kind} != {kind}"
            )
        missing_capabilities = set(required_capabilities) - set(manifest.capabilities)
        missing_permissions = set(required_permissions) - set(manifest.permissions)
        if missing_capabilities or missing_permissions:
            details = []
            if missing_capabilities:
                details.append(f"capabilities={sorted(missing_capabilities)}")
            if missing_permissions:
                details.append(f"permissions={sorted(missing_permissions)}")
            raise PluginPermissionError(
                f"plugin {plugin_id} does not satisfy requirements: {', '.join(details)}"
            )
        return manifest

    def list_manifests(self) -> tuple[PluginManifest, ...]:
        """Return manifests in stable plugin-ID order."""

        return tuple(self._manifests[key] for key in sorted(self._manifests))

    def __len__(self) -> int:
        return len(self._manifests)
