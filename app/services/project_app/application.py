"""Application adapter for the Research Workspace bounded context."""

from .ports import ResearchWorkspaceApplicationService, research_workspace_service

__all__ = ["ResearchWorkspaceApplicationService", "research_workspace_service"]
