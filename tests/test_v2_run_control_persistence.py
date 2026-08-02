from __future__ import annotations

import json

from app.services.run_lifecycle import artifacts, repository
from app.services.run_lifecycle.integrity import artifact_digest
from app.services.run_lifecycle.mappers import artifact_from_row, attempt_from_row, event_from_row, job_from_row
from app.services.run_lifecycle import read_models


def test_run_control_job_and_event_mappers_preserve_lineage_fields():
    job = job_from_row({
        "run_id": "job_1",
        "project_id": "project_1",
        "engine_mode": "hybrid",
        "status": "running",
        "current_phase": "consistency_audit",
        "progress": 74,
        "seed": 11,
        "parent_run_id": "job_0",
        "result_run_id": None,
        "scenario_json": json.dumps({"scenario_key": "energy_export_cut"}),
        "error_code": None,
        "error_message": None,
        "created_at": "2026-08-02T00:00:00.000",
        "started_at": "2026-08-02T00:00:01.000",
        "updated_at": "2026-08-02T00:00:02.000",
        "completed_at": None,
        "cancel_requested_at": None,
        "pause_requested_at": None,
        "worker_id": "worker_1",
        "lease_expires_at": "2026-08-02T00:05:00.000",
        "attempt_count": 2,
        "current_attempt_id": "attempt_2",
        "max_attempts": 3,
        "next_attempt_at": None,
        "terminal_reason": None,
        "job_kind": "war_room",
        "agent_pack_id": "agents_1",
        "agent_pack_hash": "a" * 64,
        "scenario_draft_id": "draft_1",
        "scenario_draft_hash": "b" * 64,
        "scenario_evidence_pack_hash": "c" * 64,
        "rule_pack_id": "rules_1",
        "rule_pack_hash": "d" * 64,
        "evaluation_batch_id": "eval_1",
        "evaluation_member_id": "member_1",
        "runtime_profile_json": json.dumps({"provider": "mock"}),
        "runtime_profile_hash": "e" * 64,
    })
    event = event_from_row({
        "run_id": "job_1",
        "seq": 4,
        "event_type": "CONSISTENCY",
        "phase": "consistency_audit",
        "tick": 3,
        "title": "Audit complete",
        "detail": "Numeric authority preserved",
        "payload": json.dumps({"audit_hash": "f" * 64}),
        "created_at": "2026-08-02T00:00:02.000",
    })

    assert job.current_attempt_id == "attempt_2"
    assert job.scenario_draft_hash == "b" * 64
    assert job.runtime_profile == {"provider": "mock"}
    assert event.payload["audit_hash"] == "f" * 64


def test_run_control_artifact_and_attempt_mappers_fail_closed_on_tampering():
    body = json.dumps({"result_hash": "a" * 64})
    row = {
        "artifact_id": "artifact_1",
        "run_id": "job_1",
        "artifact_type": "hybrid_replay_record",
        "schema_version": "hybrid-replay-record.v1",
        "content_json": body,
        "sha256": artifact_digest(body),
        "created_at": "2026-08-02T00:00:03.000",
        "attempt_id": "attempt_1",
        "step_id": "step_1",
        "artifact_version": 2,
        "supersedes_artifact_id": "artifact_0",
    }
    verified = artifact_from_row(row)
    tampered = artifact_from_row({**row, "content_json": json.dumps({"result_hash": "changed"})})
    attempt = attempt_from_row({
        "attempt_id": "attempt_1",
        "run_id": "job_1",
        "worker_id": "worker_1",
        "attempt_number": 1,
        "status": "completed",
        "resume_from_step": "deterministic_run",
        "started_at": "2026-08-02T00:00:01.000",
        "completed_at": "2026-08-02T00:00:03.000",
        "error_code": None,
        "error_message": None,
    })

    assert verified.integrity_status == "verified"
    assert verified.supersedes_artifact_id == "artifact_0"
    assert tampered.integrity_status == "failed"
    assert attempt.resume_from_step == "deterministic_run"


def test_legacy_lifecycle_repository_reexports_artifact_store_contract():
    assert repository.add_artifact is artifacts.add_artifact
    assert repository.get_artifacts is artifacts.get_artifacts
    assert repository.get_latest_artifact_content is artifacts.get_latest_artifact_content
    assert repository.verify_artifacts is artifacts.verify_artifacts


def test_legacy_lifecycle_repository_reexports_projection_and_audit_read_models():
    assert repository.get_audit is read_models.audit_view
    assert repository.get_projected_result_run_id is read_models.projected_result_run_id
