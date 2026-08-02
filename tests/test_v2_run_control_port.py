from __future__ import annotations

from app.api import routes
from app.services.run_lifecycle import RunControlApplicationPort, RunControlApplicationService, run_control_service


def test_lifecycle_api_uses_run_control_application_port():
    service: RunControlApplicationPort = routes.run_lifecycle
    assert service is run_control_service
    for method in ("create_job", "get_job", "get_events", "pause_job", "retry_job", "get_audit", "get_health_summary"):
        assert callable(getattr(service, method))


def test_run_control_adapter_delegates_repository_operations(monkeypatch):
    captured = {}

    class RepositoryDouble:
        def get_health_summary(self):
            captured["called"] = True
            return "health"

    monkeypatch.setattr("app.services.run_lifecycle.ports._repository", lambda: RepositoryDouble())
    assert RunControlApplicationService().get_health_summary() == "health"
    assert captured == {"called": True}
