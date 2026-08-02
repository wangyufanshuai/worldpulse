"""Persistence-to-domain mapping for the Evaluation bounded context.

These functions accept SQLite rows and PostgreSQL-compatible mapping rows but
do not open connections or make policy decisions. Keeping row shape here lets
the application coordinator move away from storage details incrementally.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.core.evaluation_models import EvaluationBatch, EvaluationCase, EvaluationMember
from app.services.project_store import loads


def case_from_row(row: Mapping[str, Any]) -> EvaluationCase:
    return EvaluationCase(
        case_id=row["case_id"],
        suite_id=row["suite_id"],
        version=row["version"],
        domain=row["domain"],
        title=row["title"],
        input=loads(row["input_json"], {}),
        qualitative_expectations=loads(row["qualitative_expectations_json"], {}),
        safety_probes=loads(row["safety_probes_json"], {}),
        evidence=loads(row["evidence_json"], []),
        case_hash=row["case_hash"],
        is_active=bool(row["is_active"]),
    )


def batch_from_row(row: Mapping[str, Any]) -> EvaluationBatch:
    return EvaluationBatch(
        batch_id=row["batch_id"],
        organization_id=row["organization_id"],
        project_id=row["project_id"],
        scenario_draft_id=row["scenario_draft_id"],
        scenario_draft_hash=row["scenario_draft_hash"],
        evidence_pack_hash=row["evidence_pack_hash"],
        suite_id=row["suite_id"],
        suite_hash=row["suite_hash"],
        rule_pack_id=row["rule_pack_id"],
        rule_pack_hash=row["rule_pack_hash"],
        runtime_profile=loads(row["runtime_profile_json"], {}),
        runtime_profile_hash=row["runtime_profile_hash"],
        provider_mode=row["provider_mode"],
        source_type=row["source_type"],
        status=row["status"],
        parent_batch_id=row["parent_batch_id"],
        total_members=row["total_members"],
        completed_members=row["completed_members"],
        failed_members=row["failed_members"],
        safety_status=row["safety_status"],
        quality_status=row["quality_status"],
        metrics=loads(row["metrics_json"], {}),
        report_hash=row["report_hash"],
        created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        evaluation_track=row["evaluation_track"],
        benchmark_suite_id=row["benchmark_suite_id"],
        benchmark_suite_hash=row["benchmark_suite_hash"],
        label_pack_id=row["label_pack_id"],
        label_pack_hash=row["label_pack_hash"],
        gate_manifest_hash=row["gate_manifest_hash"],
        root_batch_id=row["root_batch_id"],
        coordinator_worker_id=row["coordinator_worker_id"],
        coordinator_lease_expires_at=row["coordinator_lease_expires_at"],
    )


def member_from_row(row: Mapping[str, Any]) -> EvaluationMember:
    return EvaluationMember(
        member_id=row["member_id"],
        batch_id=row["batch_id"],
        case_id=row["case_id"],
        engine_mode=row["engine_mode"],
        seed=row["seed"],
        run_id=row["run_id"],
        status=row["status"],
        baseline_result_hash=row["baseline_result_hash"],
        result_hash=row["result_hash"],
        metrics=loads(row["metrics_json"], {}),
        artifact_refs=loads(row["artifact_refs_json"], []),
        error_code=row["error_code"],
        error_message=row["error_message"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        completed_at=row["completed_at"],
        input_hash=row["input_hash"],
        expected_baseline_hash=row["expected_baseline_hash"],
        verification_status=row["verification_status"],
        verification_hash=row["verification_hash"],
    )
