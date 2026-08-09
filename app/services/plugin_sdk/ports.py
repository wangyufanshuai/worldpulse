"""Application ports for installed Plugin SDK implementations."""

from __future__ import annotations

from typing import Protocol

from .contracts import PluginInputEnvelope, PluginManifest, PluginOutputEnvelope


class DataConnectorPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...


class AgentProviderPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...


class RulePackPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...


class EvaluatorPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...


class ReportRendererPluginPort(Protocol):
    @property
    def manifest(self) -> PluginManifest: ...

    def execute(self, envelope: PluginInputEnvelope) -> PluginOutputEnvelope: ...
