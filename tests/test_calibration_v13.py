from __future__ import annotations

import hashlib

from app.core.trust_models import RulePackCreateRequest
from app.services import project_store
from app.services.auth import create_user
from app.services.calibration import create_calibration_run, get_calibration_run, list_calibration_cases
from app.services.rule_packs import active_rule_pack, approve_rule_pack, create_rule_pack, submit_rule_pack
from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle.repository import get_artifacts, get_job, pause_job, resume_job


def test_versioned_corpus_has_thirty_hashed_cases_without_future_data(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "cases.db")
    cases = list_calibration_cases()
    assert len(cases) == 30
    assert {case.category for case in cases} == {"strait", "energy", "food", "sanctions", "trade", "finance"}
    assert len({case.case_hash for case in cases}) == 30
    assert all(case.cutoff_date < "2026-01-01" for case in cases)
    assert all(case.evidence and all(item.get("future_data") is not True for item in case.evidence) for case in cases)


def test_calibration_uses_worker_and_passes_fixed_gates(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "worker.db")
    analyst = create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    pack = active_rule_pack()
    calibration = create_calibration_run(pack.rule_pack_id, [], analyst)
    queued = get_job(calibration.lifecycle_run_id)
    assert queued.job_kind == "calibration"
    completed = process_one_queued_job(worker_id="calibration_test")
    assert completed and completed.status == "completed"
    status = get_calibration_run(calibration.calibration_run_id)
    assert status.gate_status == "passed"
    assert status.metrics["case_count"] == 30
    assert status.metrics["deterministic_regression"] == 1
    assert status.metrics["critical_violation_recall"] == 1
    assert status.metrics["critical_false_accept"] == 0
    assert status.metrics["top3_overlap"] >= 0.60
    assert status.metrics["supply_chain_direction_accuracy"] >= 0.70
    assert {item.artifact_type for item in get_artifacts(calibration.lifecycle_run_id)} >= {
        "calibration_case_manifest", "calibration_case_outputs", "calibration_metrics", "calibration_review_package"
    }


def test_calibration_pause_resume_and_tamper_fail_closed(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "control.db")
    analyst = create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    reviewer = create_user("reviewer", "reviewer secret phrase", "Reviewer", "reviewer")
    draft = create_rule_pack(
        RulePackCreateRequest(
            name="Calibration candidate", version="1.3.0-calibration", war_room_rule_version="war-room-rules.v1.1",
            consistency_rule_version="worldpulse-consistency.v1.2", action_adapter_version="deterministic-action-modifier.v1",
            scoring_weights_version="war-room-scoring.v1", evidence_policy_version="evidence-policy.v1",
        ), analyst,
    )
    submit_rule_pack(draft.rule_pack_id, analyst)
    calibration = create_calibration_run(draft.rule_pack_id, [], analyst)
    assert pause_job(calibration.lifecycle_run_id).status == "paused"
    assert resume_job(calibration.lifecycle_run_id).status == "queued"
    assert process_one_queued_job(worker_id="resume_test").status == "completed"
    assert approve_rule_pack(draft.rule_pack_id, reviewer).status == "candidate"

    with project_store.connect() as conn:
        row = conn.execute("SELECT artifact_id, content_json FROM run_artifacts WHERE run_id = ? AND artifact_type = 'calibration_metrics'", (calibration.lifecycle_run_id,)).fetchone()
        conn.execute("UPDATE run_artifacts SET content_json = ? WHERE artifact_id = ?", (row["content_json"] + " ", row["artifact_id"]))
        conn.execute("UPDATE rule_packs SET status = 'draft' WHERE rule_pack_id = ?", (draft.rule_pack_id,))
        conn.execute("DELETE FROM rule_pack_reviews WHERE rule_pack_id = ?", (draft.rule_pack_id,))
    try:
        approve_rule_pack(draft.rule_pack_id, reviewer)
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 422
    else:
        raise AssertionError("tampered calibration artifact must fail closed")
