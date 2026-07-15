from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.models import ResearchProjectCreate
from app.services import project_store
from app.services.auth import create_user
from app.services.calibration import create_calibration_run
from app.services.projects import create_project
from app.services.reviews import create_review_case, decide_review, ensure_artifact_integrity_reviews, get_review, list_reviews, review_decisions
from app.services.rule_packs import active_rule_pack
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle.repository import add_artifact, create_job
from app.services.trust_center import project_trust_summary
from app.core.models import RunJobCreateRequest


def test_review_decisions_are_append_only_and_cannot_override_actions(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "review.db")
    reviewer = create_user("reviewer", "reviewer secret phrase", "Reviewer", "reviewer")
    review = create_review_case("agent_action_admission", "agent_action", "job:proposal", "Action rejected", severity="high", payload={"outcome": "rejected"})
    with pytest.raises(HTTPException) as blocked:
        decide_review(review.review_id, "approve_promotion", "override", reviewer)
    assert blocked.value.status_code == 409
    decision = decide_review(review.review_id, "confirmed", "rule finding confirmed", reviewer)
    assert decision.decision == "confirmed"
    assert get_review(review.review_id).status == "closed"
    assert review_decisions(review.review_id) == [decision]
    with pytest.raises(HTTPException) as duplicate:
        decide_review(review.review_id, "request_revision", "second decision", reviewer)
    assert duplicate.value.status_code == 409


def test_trust_summary_requires_calibrated_active_pack(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "trust.db")
    analyst = create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    project = create_project(ResearchProjectCreate(title="Trust", question="Can report?", mode="war_room"))
    before = project_trust_summary(project.project_id)
    assert before.calibration_status == "not_calibrated"
    assert before.report_allowed is False
    calibration = create_calibration_run(active_rule_pack().rule_pack_id, [], analyst)
    completed = process_one_queued_job(worker_id="trust_calibration")
    assert completed and completed.run_id == calibration.lifecycle_run_id
    after = project_trust_summary(project.project_id)
    assert after.calibration_status == "passed"
    assert after.report_allowed is True
    assert after.golden_gate["scenario_count"] == 11
    assert after.data_coverage == 1


def test_artifact_tamper_creates_critical_review(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "integrity.db")
    project = create_project(ResearchProjectCreate(title="Integrity", question="Artifact?", mode="war_room"))
    job = create_job(project.project_id, RunJobCreateRequest())
    artifact = add_artifact(job.run_id, "test", "test.v1", {"safe": True})
    with project_store.connect() as conn:
        conn.execute("UPDATE run_artifacts SET content_json = '{\"safe\": false}' WHERE artifact_id = ?", (artifact.artifact_id,))
    ensure_artifact_integrity_reviews()
    reviews = list_reviews(status="open")
    match = next(item for item in reviews if item.resource_id == artifact.artifact_id)
    assert match.review_type == "artifact_integrity"
    assert match.severity == "critical"
