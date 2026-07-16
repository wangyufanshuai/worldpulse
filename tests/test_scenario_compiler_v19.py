from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient
import pytest
from pypdf import PdfWriter

from app.core.organization_models import OrganizationMemberAddRequest
from app.core.scenario_compiler_models import ScenarioCandidateDecisionRequest, ScenarioDraftReviewRequest, ScenarioDraftRunRequest
from app.main import app
from app.services import organizations, project_store
from app.services.auth import create_user, ensure_system_user, permission_for_request
from app.services.scenario_compiler import ScenarioCompilerService
from app.services.scenario_compiler.extraction import _validate_llm_candidate, deterministic_candidates, extract_chunks
from app.workers.ingestion_worker import process_once


ORG = "org_default"


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v19.db")
    monkeypatch.setenv("WORLDPULSE_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCENARIO_EXTRACTION_PROVIDER", "disabled")
    client = TestClient(app)
    project = client.post("/api/projects", json={
        "title": "V1.9 Scenario Compiler", "question": "Compile governed evidence", "mode": "war_room",
    })
    assert project.status_code == 200
    return client, project.json()["project_id"]


def _upload(client, project_id, filename="brief.md", content=None, content_type="text/markdown"):
    content = content or (
        "# 30-day Strait Blockade\n"
        "United States and China discuss sanctions as shipping and chips supply chains face disruption.\n"
        "美国、中国、海运、芯片与制裁均需要进入证据驱动场景。"
    )
    return client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/documents",
        files={"file": (filename, content.encode("utf-8"), content_type)},
        data={
            "title": "Governed scenario brief", "category": "conflict", "publisher": "Internal Research",
            "license_name": "Internal Use", "license_url": "", "observed_at": "2025-01-01T00:00:00Z",
            "cutoff_at": "2025-01-02T00:00:00Z",
        },
    )


def test_v19_migration_creates_compiler_tables_and_lineage_columns(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "schema.db")
    project_store.init_db()
    with project_store.connect() as conn:
        tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(run_jobs)")}
        quota_columns = {row["name"] for row in conn.execute("PRAGMA table_info(organization_quotas)")}
    assert {
        "source_documents", "document_extraction_jobs", "document_extractions", "scenario_candidates",
        "scenario_candidate_decisions", "scenario_drafts", "scenario_draft_reviews",
    } <= tables
    assert {"scenario_draft_id", "scenario_draft_hash", "scenario_evidence_pack_hash"} <= run_columns
    assert {"max_source_documents", "max_document_bytes"} <= quota_columns
    assert permission_for_request("POST", "/api/v8/organizations/org/projects/p/scenario-drafts/d/review") == "review"
    assert permission_for_request("POST", "/api/v8/organizations/org/projects/p/scenario-drafts/d/runs") == "run"


def test_markdown_to_approved_scenario_and_negotiation_run(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    uploaded = _upload(client, project_id)
    assert uploaded.status_code == 200, uploaded.text
    document = uploaded.json()["document"]
    duplicate = _upload(client, project_id)
    assert duplicate.status_code == 200 and duplicate.json()["deduplicated"] is True
    assert duplicate.json()["document"]["document_id"] == document["document_id"]

    job_response = client.post(f"/api/v8/organizations/{ORG}/projects/{project_id}/documents/{document['document_id']}/extract")
    assert job_response.status_code == 200
    assert process_once("v19-test-worker") is True
    job_id = job_response.json()["job_id"]
    completed = client.get(f"/api/v8/organizations/{ORG}/projects/{project_id}/extraction-jobs/{job_id}").json()
    assert completed["status"] == "completed"
    candidates = client.get(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-candidates").json()
    assert {item["candidate_type"] for item in candidates} >= {"scenario_preset", "country", "supply_chain", "policy_action"}

    selected = []
    seen_types = set()
    for candidate in candidates:
        if candidate["candidate_type"] == "scenario_preset" and "scenario_preset" in seen_types:
            continue
        if candidate["candidate_type"] in {"scenario_preset", "country", "supply_chain", "policy_action"}:
            response = client.post(
                f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-candidates/{candidate['candidate_id']}/decision",
                json={"decision": "accepted", "comment": "Analyst confirmed source locator"},
            )
            assert response.status_code == 200, response.text
            selected.append(candidate["candidate_id"])
            seen_types.add(candidate["candidate_type"])

    draft_response = client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts",
        json={"name": "Approved evidence scenario", "candidate_ids": selected},
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()
    assert draft["scenario"]["country_overrides"] == {}
    assert draft["scenario"]["chain_overrides"] == {}
    submitted = client.post(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts/{draft['draft_id']}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["evidence_pack_hash"]

    owner = ensure_system_user()
    reviewer = create_user("v19-reviewer", "reviewer secure password", "V1.9 Reviewer", "reviewer")
    organizations.add_member(ORG, OrganizationMemberAddRequest(user_id=reviewer.user_id, role="reviewer"), owner)
    service = ScenarioCompilerService()
    approved = service.review_draft(
        ORG, project_id, draft["draft_id"], ScenarioDraftReviewRequest(decision="approve", comment="Evidence and assumptions verified"), reviewer,
    )
    assert approved.status == "approved"
    cloned = service.clone_draft(ORG, project_id, draft["draft_id"], owner)
    assert cloned.parent_draft_id == draft["draft_id"]
    assert cloned.draft_hash != approved.draft_hash
    # Later append-only candidate decisions must not mutate the frozen Draft lineage.
    service.decide_candidate(ORG, project_id, selected[0], ScenarioCandidateDecisionRequest(decision="rejected", comment="future draft only"), owner)
    job = service.create_run_from_draft(ORG, project_id, draft["draft_id"], ScenarioDraftRunRequest(engine_mode="negotiation", seed=19), owner)
    assert job.engine_mode == "negotiation"
    assert job.scenario_draft_id == draft["draft_id"]
    assert job.scenario_draft_hash == approved.draft_hash
    assert job.scenario_evidence_pack_hash == approved.evidence_pack_hash


def test_draft_self_review_and_unreasoned_numeric_change_fail(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    document_id = _upload(client, project_id).json()["document"]["document_id"]
    client.post(f"/api/v8/organizations/{ORG}/projects/{project_id}/documents/{document_id}/extract")
    process_once("v19-self-review-worker")
    candidates = client.get(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-candidates").json()
    selected = []
    for candidate in candidates:
        if candidate["candidate_type"] == "scenario_preset" and any(item for item in selected if item[0] == "scenario_preset"):
            continue
        if candidate["candidate_type"] in {"scenario_preset", "country"}:
            client.post(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-candidates/{candidate['candidate_id']}/decision", json={"decision": "accepted"})
            selected.append((candidate["candidate_type"], candidate["candidate_id"]))
    invalid = client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts",
        json={"name": "Unsafe silent numeric change", "candidate_ids": [item[1] for item in selected], "intensity": 0.99},
    )
    assert invalid.status_code == 422
    valid = client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts",
        json={"name": "Reviewed manual assumption", "candidate_ids": [item[1] for item in selected], "intensity": 0.99, "assumption_reason": "Stress-test assumption"},
    ).json()
    client.post(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts/{valid['draft_id']}/submit")
    self_review = client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-drafts/{valid['draft_id']}/review",
        json={"decision": "approve", "comment": "must fail"},
    )
    assert self_review.status_code == 403


def test_upload_security_and_blob_tamper_fail_closed(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    bad_name = _upload(client, project_id, filename="../brief.md")
    assert bad_name.status_code == 422
    mismatched = _upload(client, project_id, filename="brief.pdf", content="not a pdf", content_type="application/pdf")
    assert mismatched.status_code == 415
    uploaded = _upload(client, project_id)
    document = uploaded.json()["document"]
    blob = tmp_path / "uploads" / "sha256" / document["content_hash"][:2] / document["content_hash"]
    blob.write_bytes(b"tampered")
    download = client.get(f"/api/v8/organizations/{ORG}/projects/{project_id}/documents/{document['document_id']}/download")
    assert download.status_code == 409


def test_future_cutoff_and_unknown_candidate_normalization_are_rejected(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)
    future = (datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1)).isoformat()
    response = client.post(
        f"/api/v8/organizations/{ORG}/projects/{project_id}/documents",
        files={"file": ("brief.txt", b"China energy", "text/plain")},
        data={"title": "future", "category": "energy", "publisher": "test", "license_name": "internal", "observed_at": "2025-01-01T00:00:00Z", "cutoff_at": future},
    )
    assert response.status_code == 422


def test_text_and_csv_extraction_preserve_content_and_candidate_hashes(tmp_path):
    text_path = tmp_path / "long.txt"
    text = "China chips " + ("x" * 45_000) + "\nUnited States shipping sanctions"
    text_path.write_text(text, encoding="utf-8")
    chunks = extract_chunks(text_path, "text/plain")
    assert "".join(item["text"] for item in chunks) == text
    ids = [f"snapshot-{index}" for index in range(len(chunks))]
    first = deterministic_candidates(chunks, ids)
    second = deterministic_candidates(chunks, ids)
    assert [item["candidate_hash"] for item in first] == [item["candidate_hash"] for item in second]

    csv_path = tmp_path / "scenario.csv"
    csv_text = "country,chain,policy\nChina,chips,sanctions\nUnited States,shipping,trade reroute\n"
    csv_path.write_text(csv_text, encoding="utf-8")
    csv_chunks = extract_chunks(csv_path, "text/csv")
    assert "".join(item["text"] for item in csv_chunks) == csv_text
    assert csv_chunks[0]["locator"] == {"kind": "csv_rows", "start_row": 1, "end_row": 3}


def test_pdf_fail_closed_and_llm_numeric_authority_is_invalid(tmp_path):
    scanned = tmp_path / "scanned.pdf"
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100)
    with scanned.open("wb") as handle: writer.write(handle)
    with pytest.raises(Exception, match="no extractable text"):
        extract_chunks(scanned, "application/pdf")

    encrypted = tmp_path / "encrypted.pdf"
    writer = PdfWriter(); writer.add_blank_page(width=100, height=100); writer.encrypt("secret")
    with encrypted.open("wb") as handle: writer.write(handle)
    with pytest.raises(Exception, match="Encrypted PDF"):
        extract_chunks(encrypted, "application/pdf")

    chunk = {"text": "China faces a shipping disruption.", "locator": {"kind": "line_range", "start_line": 1, "end_line": 1}}
    candidate = _validate_llm_candidate({
        "candidate_type": "country", "canonical_value": "CHN", "display_value": "China",
        "excerpt": "China", "confidence": 0.9, "risk_score": 99,
    }, chunk, "snapshot-1")
    assert candidate["validation_status"] == "invalid"
    assert candidate["validation_reason"] == "forbidden_fields:risk_score"
