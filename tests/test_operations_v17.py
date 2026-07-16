from __future__ import annotations

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.core.models import ResearchProjectCreate, RunJobCreateRequest
from app.core.operations_models import OrganizationQuotaUpdate
from app.core.organization_models import DataConnectorCreateRequest, IngestionJobCreateRequest, IngestionRecordInput
from app.main import app
from app.services import ingestion, operations, project_store
from app.services.auth import ensure_system_user, permission_for_request
from app.services.project_app.service import create_project
from app.services.run_lifecycle import repository


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "operations-v17.db")
    monkeypatch.delenv("WORLDPULSE_DATABASE_URL", raising=False)
    monkeypatch.delenv("WORLDPULSE_REQUIRE_WORKERS", raising=False)
    return ensure_system_user()


def _quota(**overrides) -> OrganizationQuotaUpdate:
    values = {
        "max_projects": 100,
        "max_active_runs": 10,
        "max_ingestion_jobs_per_day": 500,
        "max_evidence_snapshots": 100_000,
    }
    values.update(overrides)
    return OrganizationQuotaUpdate(**values)


def test_worker_registry_heartbeat_drain_and_stale_projection(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    worker = operations.register_worker("worker-v17", "lifecycle", metadata={"pool": "primary"})
    assert worker.status == "ready" and worker.fresh
    busy = operations.heartbeat_worker("worker-v17", status="busy", current_job_id="job-1")
    assert busy.current_job_id == "job-1"
    draining = operations.request_worker_drain("worker-v17")
    assert draining.status == "draining"
    assert operations.worker_should_drain("worker-v17") is True
    stopped = operations.stop_worker("worker-v17")
    assert stopped.status == "stopped"

    operations.register_worker("worker-stale", "ingestion")
    with project_store.connect() as conn:
        conn.execute("UPDATE worker_nodes SET lease_expires_at = '2000-01-01T00:00:00.000' WHERE worker_id = 'worker-stale'")
    assert operations.get_worker("worker-stale").status == "stale"


def test_organization_quota_is_enforced_and_changes_are_append_only(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    operations.update_quota("org_default", _quota(max_projects=1, max_active_runs=1), actor)
    project = create_project(ResearchProjectCreate(title="Quota one", question="First", mode="war_room"))
    with pytest.raises(HTTPException) as project_limit:
        create_project(ResearchProjectCreate(title="Quota two", question="Second", mode="war_room"))
    assert project_limit.value.status_code == 429

    first = repository.create_job(project.project_id, RunJobCreateRequest(seed=1701), idempotency_key="quota-run")
    same = repository.create_job(project.project_id, RunJobCreateRequest(seed=1701), idempotency_key="quota-run")
    assert same.run_id == first.run_id
    with pytest.raises(HTTPException) as run_limit:
        repository.create_job(project.project_id, RunJobCreateRequest(seed=1702))
    assert run_limit.value.status_code == 429

    operations.update_quota("org_default", _quota(max_projects=2, max_active_runs=2), actor)
    with project_store.connect() as conn:
        events = conn.execute(
            "SELECT previous_json, current_json FROM organization_quota_events WHERE organization_id = 'org_default' ORDER BY created_at"
        ).fetchall()
    assert len(events) == 2
    assert '"max_projects": 1' in events[-1]["previous_json"]
    assert '"max_projects": 2' in events[-1]["current_json"]


def test_readiness_distinguishes_database_health_from_worker_capacity(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    degraded = operations.platform_readiness()
    assert degraded.schema_ok and degraded.rule_pack_ok
    assert degraded.status == "degraded"

    operations.register_worker("lifecycle-ready", "lifecycle")
    operations.register_worker("ingestion-ready", "ingestion")
    ready = operations.platform_readiness()
    assert ready.status == "ready"
    assert ready.worker_requirement_met

    operations.stop_worker("ingestion-ready")
    monkeypatch.setenv("WORLDPULSE_REQUIRE_WORKERS", "1")
    unavailable = operations.platform_readiness()
    assert unavailable.status == "not_ready"
    assert "required_workers_unavailable" in unavailable.reasons


def test_v6_operations_contract_and_public_readiness(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    with TestClient(app) as client:
        assert client.get("/api/health").status_code == 200
        readiness = client.get("/api/ready")
        assert readiness.status_code == 200
        assert readiness.json()["database_backend"] == "sqlite"
        summary = client.get("/api/v6/organizations/org_default/operations")
        assert summary.status_code == 200
        assert summary.json()["quota"]["max_projects"] == 100
        updated = client.put("/api/v6/organizations/org_default/quota", json=_quota(max_projects=7).model_dump())
        assert updated.status_code == 200
        assert updated.json()["max_projects"] == 7

    assert permission_for_request("POST", "/api/v6/workers/x/drain") == "operations"
    assert permission_for_request("PUT", "/api/v6/organizations/org_default/quota") == "organization_admin"


def test_ingestion_reserves_snapshot_capacity_without_breaking_idempotency(monkeypatch, tmp_path):
    actor = _setup(monkeypatch, tmp_path)
    operations.update_quota("org_default", _quota(max_evidence_snapshots=1), actor)
    connector = ingestion.create_connector("org_default", DataConnectorCreateRequest(
        name="Quota feed", source_locator="manual://quota-feed",
        config={"publisher": "WorldPulse tests", "license": "internal"},
    ), actor)
    record = IngestionRecordInput(
        external_ref="reserved-1", title="Reserved snapshot", category="energy",
        content={"pressure": 0.7}, observed_at="2026-07-01", cutoff_at="2026-07-16",
    )
    payload = IngestionJobCreateRequest(connector_id=connector.connector_id, records=[record], idempotency_key="reserved-batch")
    first = ingestion.create_job("org_default", payload, actor)
    assert ingestion.create_job("org_default", payload, actor).job_id == first.job_id
    with pytest.raises(HTTPException) as reserved:
        ingestion.create_job("org_default", IngestionJobCreateRequest(
            connector_id=connector.connector_id,
            records=[record.model_copy(update={"external_ref": "reserved-2"})],
        ), actor)
    assert reserved.value.status_code == 429
    assert ingestion.execute_job("org_default", first.job_id, actor).status == "completed"
