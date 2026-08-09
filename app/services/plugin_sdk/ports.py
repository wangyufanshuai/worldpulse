"""Application ports for installed Plugin SDK implementations."""

from __future__ import annotations

from typing import Protocol

from .contracts import PluginInputEnvelope, PluginManifest, PluginOutputEnvelope


class DataConnectorPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...
