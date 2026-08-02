from __future__ import annotations

import json

from app.services.evaluation.mappers import batch_from_row, case_from_row, member_from_row


def _json(value):
    return json.dumps(value)


def test_evaluation_case_mapping_is_storage_agnostic():
    mapped = case_from_row({
        "case_id": "case_1",
        "suite_id": "suite_1",
        "version": "1",
        "domain": "energy",
        "title": "Energy pressure",
        "input_json": _json({"event": "shock"}),
        "qualitative_expectations_json": _json({"direction": "up"}),
        "safety_probes_json": _json({"forbidden": ["numeric_override"]}),
        "evidence_json": _json([{"evidence_id": "e1"}]),
        "case_hash": "a" * 64,
        "is_active": 1,
    })

    assert mapped.case_id == "case_1"
    assert mapped.input == {"event": "shock"}
    assert mapped.is_active is True


def test_batch_and_member_mapping_preserve_lineage_and_artifact_fields():
    batch = batch_from_row({
        "batch_id": "batch_1",
        "organization_id": "org_1",
        "project_id": "project_1",
        "scenario_draft_id": "draft_1",
        "scenario_draft_hash": "b" * 64,
        "evidence_pack_hash": "c" * 64,
        "suite_id": "suite_1",
        "suite_hash": "d" * 64,
        "rule_pack_id": "rule_1",
        "rule_pack_hash": "e" * 64,
        "runtime_profile_json": _json({"provider": "mock"}),
        "runtime_profile_hash": "f" * 64,
        "provider_mode": "mock",
        "source_type": "standard",
        "status": "queued",
        "parent_batch_id": None,
        "total_members": 7,
        "completed_members": 0,
        "failed_members": 0,
        "safety_status": "pending",
        "quality_status": "pending",
        "metrics_json": _json({}),
        "report_hash": None,
        "created_by_user_id": "user_1",
        "created_at": "2026-08-02T00:00:00",
        "updated_at": "2026-08-02T00:00:00",
        "completed_at": None,
        "evaluation_track": "engineering_standard",
        "benchmark_suite_id": None,
        "benchmark_suite_hash": None,
        "label_pack_id": None,
        "label_pack_hash": None,
        "gate_manifest_hash": "1" * 64,
        "root_batch_id": "batch_1",
        "coordinator_worker_id": None,
        "coordinator_lease_expires_at": None,
    })
    member = member_from_row({
        "member_id": "member_1",
        "batch_id": "batch_1",
        "case_id": "case_1",
        "engine_mode": "hybrid",
        "seed": 11,
        "run_id": "run_1",
        "status": "completed",
        "baseline_result_hash": "2" * 64,
        "result_hash": "3" * 64,
        "metrics_json": _json({"safety": 1}),
        "artifact_refs_json": _json(["artifact_1"]),
        "error_code": None,
        "error_message": None,
        "created_at": "2026-08-02T00:00:00",
        "updated_at": "2026-08-02T00:00:01",
        "completed_at": "2026-08-02T00:00:01",
        "input_hash": "4" * 64,
        "expected_baseline_hash": "5" * 64,
        "verification_status": "passed",
        "verification_hash": "6" * 64,
    })

    assert batch.scenario_draft_hash == "b" * 64
    assert batch.runtime_profile == {"provider": "mock"}
    assert member.engine_mode == "hybrid"
    assert member.artifact_refs == ["artifact_1"]
    assert member.verification_status == "passed"
