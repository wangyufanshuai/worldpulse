"""Internal project application services.

The public compatibility surface remains :mod:`app.services.projects`.
"""

from .application import ResearchWorkspaceApplicationService, research_workspace_service
from .ports import ResearchWorkspaceApplicationPort

__all__ = [
    "ResearchWorkspaceApplicationPort",
    "ResearchWorkspaceApplicationService",
    "research_workspace_service",
]
