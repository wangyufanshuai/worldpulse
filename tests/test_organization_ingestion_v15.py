from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from app.core.organization_models import DataConnectorCreateRequest, IngestionJobCreateRequest, IngestionRecordInput, OrganizationCreateRequest
from app.main import app
from app.services import ingestion, organizations, project_store
from app.services.auth import create_user, ensure_system_user, permission_for_request
from app.workers.ingestion_worker import process_once


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v15.db")
    actor = ensure_system_user()
    with project_store.connect() as conn:
        conn.execute(
            """
            INSERT INTO research_projects
            (project_id, title, question, region, asset_scope, event_window_days, event_types,
             mode, scenario_config, status, created_at, updated_at)
            VALUES ('project_ingestion', 'Ingestion project', 'What changed?', 'global', '[]', 30,
                    '[]', 'war_room', '{}', 'ready', '2026-07-01', '2026-07-01')
            """
        )
    organizations.scope_resource("org_default", "project", "project_ingestion")
    return actor


def _connector(actor):
    return ingestion.create_connector("org_default", DataConnectorCreateRequest(
        name="Licensed manual feed", source_locator="manual://licensed-feed",
        config={"publisher": "WorldPulse QA", "license": "internal-test-v1"},
    ), actor)


def _record(ref="energy-2026-06", observed="2026-06-01", cutoff="2026-06-30"):
    return IngestionRecordInput(
        external_ref=ref, title="Energy pressure", category="energy", content={"pressure": 72.5},
        content_text="Energy pressure 72.5", observed_at=observed, cutoff_at=cutoff,
    )


def test_default_organization_and_manual_ingestion_close_the_evidence_loop(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    organization = organizations.current_organization(actor)
    assert organization.organization_id == "org_default"
    assert organization.member_role == "owner"
    connector = _connector(actor)
    job = ingestion.create_job("org_default", IngestionJobCreateRequest(
        connector_id=connector.connector_id, project_id="project_ingestion", records=[_record()],
        idempotency_key="batch-2026-06",
    ), actor)
    completed = ingestion.execute_job("org_default", job.job_id, actor)
    assert completed.status == "completed"
    assert completed.accepted_count == 1
    assert completed.manifest_hash
    assert completed.manifest["policy_hash"]
    assert [event.seq for event in ingestion.list_events("org_default", job.job_id, actor)] == [1, 2, 3]
    with project_store.connect() as conn:
        snapshot = conn.execute("SELECT content_hash FROM evidence_snapshots WHERE project_id = 'project_ingestion'").fetchone()
        scoped = conn.execute("SELECT 1 FROM organization_resources WHERE resource_type = 'evidence_snapshot'").fetchone()
    assert snapshot and scoped


def test_ingestion_is_idempotent_and_worker_can_process_once(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    connector = _connector(actor)
    payload = IngestionJobCreateRequest(
        connector_id=connector.connector_id, project_id="project_ingestion", records=[_record()],
        idempotency_key="stable-batch",
    )
    first = ingestion.create_job("org_default", payload, actor)
    second = ingestion.create_job("org_default", payload, actor)
    assert second.job_id == first.job_id
    assert process_once("pytest-ingestion-worker") is True
    assert ingestion.get_job("org_default", first.job_id, actor).status == "completed"
    assert process_once("pytest-ingestion-worker") is False


def test_policy_rejects_future_data_secrets_and_unlicensed_connectors(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    with pytest.raises(Exception) as secret_error:
        ingestion.create_connector("org_default", DataConnectorCreateRequest(
            name="Secret feed", source_locator="manual://secret",
            config={"publisher": "x", "license": "x", "api_key": "must-not-store"},
        ), actor)
    assert getattr(secret_error.value, "status_code", None) == 422
    with pytest.raises(Exception) as license_error:
        ingestion.create_connector("org_default", DataConnectorCreateRequest(
            name="Unlicensed", source_locator="manual://unlicensed", config={"publisher": "x"},
        ), actor)
    assert getattr(license_error.value, "status_code", None) == 422
    connector = _connector(actor)
    with pytest.raises(Exception) as future_error:
        ingestion.create_job("org_default", IngestionJobCreateRequest(
            connector_id=connector.connector_id, records=[_record(observed="2026-07-02", cutoff="2026-07-01")],
        ), actor)
    assert getattr(future_error.value, "status_code", None) == 422


def test_cancel_and_retry_preserve_parent_lineage(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    connector = _connector(actor)
    job = ingestion.create_job("org_default", IngestionJobCreateRequest(connector_id=connector.connector_id, records=[_record()]), actor)
    cancelled = ingestion.cancel_job("org_default", job.job_id, actor)
    assert cancelled.status == "cancelled"
    retried = ingestion.retry_job("org_default", cancelled.job_id, actor)
    assert retried.parent_job_id == cancelled.job_id
    assert retried.status == "queued"


def test_organization_membership_isolates_ingestion_resources(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    second = organizations.create_organization(OrganizationCreateRequest(name="Second Organization", slug="second-org"), actor)
    connector = ingestion.create_connector(second.organization_id, DataConnectorCreateRequest(
        name="Second feed", source_locator="manual://second",
        config={"publisher": "Second", "license": "internal"},
    ), actor)
    assert connector.organization_id == second.organization_id
    viewer = create_user("isolated-viewer", "isolated viewer phrase", "Isolated Viewer", "viewer")
    with pytest.raises(Exception) as denied:
        ingestion.list_connectors(second.organization_id, viewer)
    assert getattr(denied.value, "status_code", None) == 403


def test_v5_api_rbac_and_bounded_execute(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        organization = client.get("/api/v5/organizations/current")
        assert organization.status_code == 200
        org_id = organization.json()["organization_id"]
        connector = client.post(f"/api/v5/organizations/{org_id}/ingestion/connectors", json={
            "name": "API manual feed", "connector_type": "manual_json", "source_locator": "manual://api-feed",
            "config": {"publisher": "WorldPulse API", "license": "internal-test"},
        })
        assert connector.status_code == 200
        job = client.post(f"/api/v5/organizations/{org_id}/ingestion/jobs", json={
            "connector_id": connector.json()["connector_id"], "project_id": "project_ingestion",
            "records": [_record().model_dump(mode="json")],
        })
        assert job.status_code == 200
        completed = client.post(f"/api/v5/organizations/{org_id}/ingestion/jobs/{job.json()['job_id']}/execute")
        assert completed.status_code == 200
        assert completed.json()["status"] == "completed"
        assert client.get(f"/api/v5/organizations/{org_id}/ingestion/summary").json()["accepted_records"] == 1


def test_v5_organization_projects_are_scoped_without_changing_v1_models(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        created_org = client.post("/api/v5/organizations", json={"name": "Scoped Decisions", "slug": "scoped-decisions"})
        assert created_org.status_code == 200
        org_id = created_org.json()["organization_id"]
        created = client.post(f"/api/v5/organizations/{org_id}/projects", json={
            "title": "Scoped project", "question": "Is this isolated?", "mode": "war_room", "event_types": ["trade"],
        })
        assert created.status_code == 200
        project_id = created.json()["project_id"]
        scoped = client.get(f"/api/v5/organizations/{org_id}/projects")
        assert [item["project_id"] for item in scoped.json()] == [project_id]
        default_projects = client.get("/api/v5/organizations/org_default/projects")
        assert project_id not in [item["project_id"] for item in default_projects.json()]
        with pytest.raises(Exception):
            organizations.require_resource_scope("org_default", "project", project_id)


def test_v5_global_permission_router_defers_project_and_ingestion_detail_to_org_rbac():
    assert permission_for_request("POST", "/api/v5/organizations/org_default/projects") == "project_write"
    assert permission_for_request("POST", "/api/v5/organizations/org_default/ingestion/jobs") == "ingestion_write"
    assert permission_for_request("POST", "/api/v5/organizations/org_default/members") == "organization_admin"
