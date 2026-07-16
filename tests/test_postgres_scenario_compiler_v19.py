from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import os

import pytest
from starlette.datastructures import Headers, UploadFile

from app.core.models import ResearchProjectCreate
from app.db.postgres import apply_postgres_migrations, is_postgres_url
from app.services.auth import ensure_system_user
from app.services.project_app.service import create_project
from app.services.project_store import connect
from app.services.scenario_compiler import ScenarioCompilerService


pytestmark = [
    pytest.mark.postgres_live,
    pytest.mark.skipif(
        not is_postgres_url(os.getenv("WORLDPULSE_TEST_POSTGRES_URL")),
        reason="WORLDPULSE_TEST_POSTGRES_URL is required for live PostgreSQL integration tests",
    ),
]


@pytest.fixture(autouse=True)
def _postgres_runtime(monkeypatch, tmp_path):
    url = os.environ["WORLDPULSE_TEST_POSTGRES_URL"]
    monkeypatch.setenv("WORLDPULSE_DATABASE_URL", url)
    monkeypatch.setenv("WORLDPULSE_AUTO_MIGRATE", "1")
    monkeypatch.setenv("WORLDPULSE_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCENARIO_EXTRACTION_PROVIDER", "disabled")
    apply_postgres_migrations(url)


def _upload(service, project_id, actor, filename, content):
    upload = UploadFile(
        BytesIO(content.encode("utf-8")), filename=filename,
        headers=Headers({"content-type": "text/markdown"}),
    )
    return asyncio.run(service.upload_document(
        "org_default", project_id, upload, actor,
        title=filename, category="conflict", publisher="PostgreSQL integration",
        license_name="Internal Use", license_url="", observed_at="2025-01-01T00:00:00Z",
        cutoff_at="2025-01-02T00:00:00Z",
    )).document


def test_postgres_v19_migration_concurrent_claim_and_extraction_commit():
    actor = ensure_system_user()
    project = create_project(ResearchProjectCreate(
        title="PostgreSQL V1.9 compiler", question="Can document extraction claim concurrently?", mode="war_room",
    ))
    service = ScenarioCompilerService()
    documents = [
        _upload(service, project.project_id, actor, "brief-a.md", "# 30-day Strait Blockade\nChina chips shipping sanctions"),
        _upload(service, project.project_id, actor, "brief-b.md", "# Energy Export Cut\nUnited States energy trade reroute"),
    ]
    jobs = [service.create_extraction_job("org_default", project.project_id, item.document_id, actor) for item in documents]

    with ThreadPoolExecutor(max_workers=2) as pool:
        claimed = list(pool.map(service.claim_next_extraction_job, ("v19-pg-a", "v19-pg-b")))
    assert {item[2] for item in claimed if item} == {item.job_id for item in jobs}

    worker_by_job = {item[2]: worker for item, worker in zip(claimed, ("v19-pg-a", "v19-pg-b"), strict=True)}
    with ThreadPoolExecutor(max_workers=2) as pool:
        completed = list(pool.map(
            lambda item: service.execute_claimed_extraction(item[0], item[1], item[2], worker_by_job[item[2]]),
            claimed,
        ))
    assert all(item.status == "completed" for item in completed)
    for item in jobs:
        events = service.list_extraction_events("org_default", project.project_id, item.job_id, actor)
        assert [event.seq for event in events] == list(range(1, len(events) + 1))

    with connect() as conn:
        column = conn.execute(
            "SELECT data_type FROM information_schema.columns WHERE table_name = 'organization_quotas' AND column_name = 'max_document_bytes'"
        ).fetchone()
    assert column["data_type"] == "bigint"
    assert service.verify_blobs()["status"] == "ok"
