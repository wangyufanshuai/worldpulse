"""Compatibility façade for project services.

API routes, tests, and workers import this module.  The implementation lives
under ``app.services.project_app`` so future refactors can split repositories,
workspace projection, replay, diff, and chat without changing callers.
"""

from app.services.project_app import service as _service
from app.services.project_app.service import *  # noqa: F401,F403


_PATCHABLE_DEPENDENCIES = (
    "analyze_current_risk",
    "build_causal_chain",
    "build_causal_events",
    "build_risk_overview",
    "request_structured_analysis",
    "run_causal_backtest",
    "run_simulation",
)


def _sync_service_overrides() -> None:
    for name in _PATCHABLE_DEPENDENCIES:
        if name in globals():
            setattr(_service, name, globals()[name])


def run_project(project_id: str, mode: str = "fast"):
    _sync_service_overrides()
    return _service.run_project(project_id, mode)


def chat_with_project(project_id: str, payload):
    _sync_service_overrides()
    return _service.chat_with_project(project_id, payload)
