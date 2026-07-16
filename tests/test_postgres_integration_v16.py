from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os

import pytest

from app.core.models import ResearchProjectCreate, RunJobCreateRequest, WarRoomScenarioRequest
from app.db.postgres import apply_postgres_migrations, is_postgres_url, verify_postgres_schema
from app.services.project_app.service import create_project, war_room_replay_pack, war_room_workspace
from app.services.run_lifecycle import process_one_queued_job, repository
from app.services import operations
from app.services.auth import ensure_system_user
from app.core.operations_models import OrganizationQuotaUpdate


pytestmark = [
    pytest.mark.postgres_live,
    pytest.mark.skipif(
        not is_postgres_url(os.getenv("WORLDPULSE_TEST_POSTGRES_URL")),
        reason="WORLDPULSE_TEST_POSTGRES_URL is required for live PostgreSQL integration tests",
    ),
]


@pytest.fixture(autouse=True)
def _postgres_runtime(monkeypatch):
    url = os.environ["WORLDPULSE_TEST_POSTGRES_URL"]
    monkeypatch.setenv("WORLDPULSE_DATABASE_URL", url)
    monkeypatch.setenv("WORLDPULSE_AUTO_MIGRATE", "1")
    apply_postgres_migrations(url)


def _project():
    return create_project(ResearchProjectCreate(
        title="PostgreSQL V1.6 integration",
        question="Can the deterministic lifecycle complete under PostgreSQL?",
        mode="war_room",
    ))


def _request(seed: int) -> RunJobCreateRequest:
    return RunJobCreateRequest(
        seed=seed,
        scenario=WarRoomScenarioRequest(
            scenario_key="energy_export_cut", duration_days=30, intensity=0.7, propagation=0.45,
        ),
    )


def test_postgres_schema_claiming_and_event_sequence_are_concurrency_safe():
    assert verify_postgres_schema()["tables"] >= 40
    project = _project()
    jobs = [repository.create_job(project.project_id, _request(seed)) for seed in (1601, 1602)]

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(lambda worker: repository.claim_next_job(worker), ("pg-worker-a", "pg-worker-b")))
    assert {item.run_id for item in claimed if item} == {item.run_id for item in jobs}

    run_id = jobs[0].run_id
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(
            lambda index: repository.append_event(
                run_id, "WORKER", "scenario_compile", f"Concurrent event {index}", "PostgreSQL sequence audit",
            ),
            range(8),
        ))
    sequences = [item.seq for item in repository.get_events(run_id)]
    assert sequences == list(range(1, len(sequences) + 1))


def test_postgres_worker_completes_and_projects_legacy_artifacts():
    project = _project()
    job = repository.create_job(project.project_id, _request(1699))
    completed = process_one_queued_job(worker_id="pg-integration-worker")
    assert completed is not None
    assert completed.run_id == job.run_id
    assert completed.status == "completed"
    assert completed.result_run_id

    workspace = war_room_workspace(project.project_id, completed.result_run_id)
    replay = war_room_replay_pack(project.project_id, completed.result_run_id)
    assert workspace.run_id == completed.result_run_id
    assert replay.run_id == completed.result_run_id
    assert replay.manifest["trust_manifest"]["rule_pack_hash"] == completed.rule_pack_hash


def test_postgres_v17_worker_registry_readiness_and_quota_audit():
    actor = ensure_system_user()
    lifecycle = operations.register_worker("pg-v17-lifecycle", "lifecycle")
    ingestion = operations.register_worker("pg-v17-ingestion", "ingestion")
    assert lifecycle.fresh and ingestion.fresh
    assert operations.platform_readiness().status == "ready"

    updated = operations.update_quota("org_default", OrganizationQuotaUpdate(
        max_projects=500, max_active_runs=50,
        max_ingestion_jobs_per_day=5000, max_evidence_snapshots=500_000,
    ), actor)
    assert updated.max_active_runs == 50
    drained = operations.request_worker_drain("pg-v17-ingestion")
    assert drained.status == "draining"

    usage = operations.organization_usage("org_default")
    operations.update_quota("org_default", OrganizationQuotaUpdate(
        max_projects=usage.projects + 1, max_active_runs=50,
        max_ingestion_jobs_per_day=5000, max_evidence_snapshots=500_000,
    ), actor)

    def attempt_project(index: int):
        try:
            return create_project(ResearchProjectCreate(
                title=f"PostgreSQL quota race {index}", question="Exactly one should fit", mode="war_room",
            )).project_id
        except Exception as exc:
            return getattr(exc, "status_code", None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt_project, (1, 2)))
    assert sum(isinstance(item, str) for item in results) == 1
    assert results.count(429) == 1
    operations.update_quota("org_default", OrganizationQuotaUpdate(
        max_projects=500, max_active_runs=50,
        max_ingestion_jobs_per_day=5000, max_evidence_snapshots=500_000,
    ), actor)
