from __future__ import annotations

from app.api import v8
from app.services.scenario_compiler import (
    ScenarioCompilerApplicationPort,
    ScenarioCompilerApplicationService,
    scenario_compiler_service,
)


def test_v8_api_uses_the_scenario_compiler_application_port():
    service: ScenarioCompilerApplicationPort = v8.service
    assert service is scenario_compiler_service
    for method in (
        "upload_document",
        "create_extraction_job",
        "list_candidates",
        "create_draft",
        "review_draft",
        "create_run_from_draft",
    ):
        assert callable(getattr(service, method))


def test_scenario_compiler_application_adapter_delegates_without_storage_access():
    captured = {}

    class Delegate:
        def list_documents(self, organization_id, project_id, actor):
            captured.update({"organization_id": organization_id, "project_id": project_id, "actor": actor})
            return []

    service = ScenarioCompilerApplicationService(Delegate())
    assert service.list_documents("org_1", "project_1", "actor_1") == []
    assert captured == {"organization_id": "org_1", "project_id": "project_1", "actor": "actor_1"}
