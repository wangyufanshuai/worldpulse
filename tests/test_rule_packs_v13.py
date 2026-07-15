from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.models import ResearchProjectCreate, RunJobCreateRequest
from app.core.trust_models import RulePackCreateRequest
from app.services import project_store
from app.services.auth import create_user
from app.services.calibration import create_calibration_run
from app.services.projects import create_project
from app.services.rule_packs import (
    active_rule_pack,
    activate_rule_pack,
    approve_rule_pack,
    create_rule_pack,
    get_rule_pack,
    submit_rule_pack,
)
from app.services.run_lifecycle.repository import create_job, get_job
from app.services.run_lifecycle import process_one_queued_job


def _draft(actor, suffix: str = "candidate"):
    return create_rule_pack(
        RulePackCreateRequest(
            name="V1.3 candidate",
            version=f"1.3.0-{suffix}",
            war_room_rule_version="war-room-rules.v1.1",
            consistency_rule_version="worldpulse-consistency.v1.2",
            action_adapter_version="deterministic-action-modifier.v1",
            scoring_weights_version="war-room-scoring.v1",
            evidence_policy_version="evidence-policy.v1",
            supersedes_rule_pack_id="rp_v12_active",
        ),
        actor,
    )


def _pass_calibration(rule_pack_id: str, actor):
    calibration = create_calibration_run(rule_pack_id, [], actor)
    for _ in range(5):
        completed = process_one_queued_job(worker_id="rule_pack_calibration")
        if completed and completed.run_id == calibration.lifecycle_run_id:
            assert completed.status == "completed"
            return
    raise AssertionError("calibration lifecycle job was not processed")


def test_v12_pack_is_seeded_active_and_immutable(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "rules.db")
    pack = active_rule_pack()
    assert pack.rule_pack_id == "rp_v12_active"
    assert pack.status == "active"
    assert len(pack.manifest_hash) == 64
    with project_store.connect() as conn:
        original = conn.execute("SELECT manifest_json FROM rule_packs WHERE rule_pack_id = ?", (pack.rule_pack_id,)).fetchone()[0]
    assert original
    assert get_rule_pack(pack.rule_pack_id).manifest == pack.manifest


def test_two_person_approval_calibration_gate_and_activation(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "promotion.db")
    creator = create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    reviewer = create_user("reviewer", "reviewer secret phrase", "Reviewer", "reviewer")
    admin = create_user("admin", "administrator secret", "Admin", "admin")
    draft = _draft(creator)
    submitted = submit_rule_pack(draft.rule_pack_id, creator)
    with pytest.raises(HTTPException) as own:
        approve_rule_pack(draft.rule_pack_id, creator)
    assert own.value.status_code == 403
    with pytest.raises(HTTPException) as gate:
        approve_rule_pack(draft.rule_pack_id, reviewer)
    assert gate.value.status_code == 422
    _pass_calibration(draft.rule_pack_id, creator)
    candidate = approve_rule_pack(draft.rule_pack_id, reviewer, "calibration reviewed")
    assert candidate.status == "candidate"
    activated = activate_rule_pack(draft.rule_pack_id, admin)
    assert activated.status == "active"
    assert get_rule_pack("rp_v12_active").status == "retired"


def test_lifecycle_job_pins_rule_pack_hash(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "pin.db")
    creator = create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    reviewer = create_user("reviewer", "reviewer secret phrase", "Reviewer", "reviewer")
    admin = create_user("admin", "administrator secret", "Admin", "admin")
    project = create_project(ResearchProjectCreate(title="Pinned rules", question="Which rules?", mode="war_room"))
    old = active_rule_pack()
    old_job = create_job(project.project_id, RunJobCreateRequest())
    draft = submit_rule_pack(_draft(creator, "pin").rule_pack_id, creator)
    _pass_calibration(draft.rule_pack_id, creator)
    approve_rule_pack(draft.rule_pack_id, reviewer)
    new_pack = activate_rule_pack(draft.rule_pack_id, admin)
    new_job = create_job(project.project_id, RunJobCreateRequest())
    assert get_job(old_job.run_id).rule_pack_hash == old.manifest_hash
    assert new_job.rule_pack_hash == new_pack.manifest_hash
    assert new_job.rule_pack_id == new_pack.rule_pack_id
