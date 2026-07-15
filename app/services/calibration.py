from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from app.core.models import RunJobStatus, WarRoomScenarioRequest
from app.core.trust_models import CalibrationCase, CalibrationRunStatus, UserIdentity
from app.services.agent_contract import build_mock_agent_batch
from app.services.consistency.actions import evaluate_action_proposals
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads
from app.services.rule_packs import get_rule_pack
from app.services.run_lifecycle import repository, steps
from app.services.war_room.data import SUPPLY_CHAINS
from app.services.war_room_engine import run_war_room


CALIBRATION_PHASES = (
    ("case_prepare", 20, "SNAPSHOT", "Calibration cases frozen"),
    ("deterministic_replay", 58, "ENGINE", "Deterministic historical replay completed"),
    ("metric_compare", 82, "CONSISTENCY", "Calibration metrics compared"),
    ("review_package", 100, "SNAPSHOT", "Calibration review package ready"),
)
CORPUS_PATH = Path(__file__).resolve().parents[2] / "tests" / "calibration_cases" / "v1_cases.json"
SUPPORTED = {
    "war_room_rule_version": "war-room-rules.v1.1",
    "consistency_rule_version": "worldpulse-consistency.v1.2",
    "action_adapter_version": "deterministic-action-modifier.v1",
    "scoring_weights_version": "war-room-scoring.v1",
    "evidence_policy_version": "evidence-policy.v1",
}


def ensure_calibration_cases() -> None:
    init_db()
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM calibration_cases").fetchone()[0] >= 30:
            return
    records = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    if len(records) != 30:
        raise RuntimeError("Calibration corpus v1 must contain exactly 30 cases")
    for record in records:
        expected_hash = stable_hash({
            key: record[key] for key in (
                "case_id", "version", "category", "input_snapshot", "labels", "evidence",
                "cutoff_date", "observation_window_days", "label_confidence",
            )
        })
        if expected_hash != record["case_hash"]:
            raise RuntimeError(f"Calibration case hash mismatch: {record['case_id']}")
        with connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO calibration_cases
                (case_id, version, category, title, cutoff_date, observation_window_days, input_snapshot,
                 labels_json, evidence_json, label_confidence, case_hash, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["case_id"], record["version"], record["category"], record["title"],
                    record["cutoff_date"], record["observation_window_days"], dumps(record["input_snapshot"]),
                    dumps(record["labels"]), dumps(record["evidence"]), record["label_confidence"],
                    record["case_hash"], int(record.get("is_active", True)), _now(),
                ),
            )


def list_calibration_cases() -> list[CalibrationCase]:
    ensure_calibration_cases()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM calibration_cases WHERE is_active = 1 ORDER BY category, case_id").fetchall()
    return [_case_from_row(row) for row in rows]


def create_calibration_run(rule_pack_id: str, case_ids: list[str], actor: UserIdentity) -> CalibrationRunStatus:
    pack = get_rule_pack(rule_pack_id)
    ensure_calibration_cases()
    available = {case.case_id for case in list_calibration_cases()}
    selected = case_ids or sorted(available)
    unknown = sorted(set(selected) - available)
    if unknown:
        raise HTTPException(status_code=404, detail=f"Unknown calibration cases: {unknown}")
    if len(selected) < 30:
        raise HTTPException(status_code=422, detail="Promotion calibration requires at least 30 versioned cases")
    project_id = _ensure_calibration_project()
    lifecycle_run_id = f"job_{uuid4().hex[:12]}"
    calibration_run_id = f"cal_{uuid4().hex[:16]}"
    now = _now()
    scenario = {"rule_pack_id": rule_pack_id, "case_ids": selected, "corpus_version": "calibration-corpus.v1"}
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            """
            INSERT INTO run_jobs
            (run_id, project_id, engine_mode, status, current_phase, progress, scenario_json, created_at, updated_at,
             max_attempts, request_hash, job_kind, rule_pack_id, rule_pack_hash)
            VALUES (?, ?, 'deterministic', 'queued', 'case_prepare', 0, ?, ?, ?, 3, ?, 'calibration', ?, ?)
            """,
            (lifecycle_run_id, project_id, dumps(scenario), now, now, stable_hash(scenario), rule_pack_id, pack.manifest_hash),
        )
        conn.execute("INSERT INTO run_event_counters(run_id, next_seq) VALUES (?, 1)", (lifecycle_run_id,))
        conn.execute(
            """
            INSERT INTO calibration_runs
            (calibration_run_id, rule_pack_id, lifecycle_run_id, status, metrics_json, gate_status, created_by_user_id, created_at)
            VALUES (?, ?, ?, 'queued', '{}', 'pending', ?, ?)
            """,
            (calibration_run_id, rule_pack_id, lifecycle_run_id, actor.user_id, now),
        )
    repository.append_event(lifecycle_run_id, "WORKER", "case_prepare", "Calibration job queued", "30-case frozen corpus queued for deterministic replay.", payload={"calibration_run_id": calibration_run_id, "case_count": len(selected)})
    return get_calibration_run(calibration_run_id)


def get_calibration_run(calibration_run_id: str) -> CalibrationRunStatus:
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.*, j.status AS lifecycle_status FROM calibration_runs c
            LEFT JOIN run_jobs j ON j.run_id = c.lifecycle_run_id WHERE c.calibration_run_id = ?
            """,
            (calibration_run_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown calibration run: {calibration_run_id}")
    return CalibrationRunStatus(
        calibration_run_id=row["calibration_run_id"], rule_pack_id=row["rule_pack_id"], lifecycle_run_id=row["lifecycle_run_id"],
        status=row["status"], metrics=loads(row["metrics_json"], {}), gate_status=row["gate_status"],
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], completed_at=row["completed_at"],
        lifecycle_status=row["lifecycle_status"],
    )


def process_calibration_job(run_id: str) -> RunJobStatus:
    job = repository.get_job(run_id)
    if not job.current_attempt_id:
        raise RuntimeError("Calibration job has no active attempt")
    config = job.scenario
    with connect() as conn:
        conn.execute("UPDATE calibration_runs SET status = 'running' WHERE lifecycle_run_id = ? AND status = 'queued'", (run_id,))
    pack = get_rule_pack(job.rule_pack_id or config["rule_pack_id"])
    cases = {case.case_id: case for case in list_calibration_cases() if case.case_id in set(config["case_ids"])}
    outputs = repository.get_latest_artifact_content(run_id, "calibration_case_outputs") or {}
    metrics = repository.get_latest_artifact_content(run_id, "calibration_metrics") or {}
    for phase, progress, event_type, title in CALIBRATION_PHASES:
        controlled = _boundary_control(job)
        if controlled:
            return controlled
        step = steps.begin_step(run_id, phase, job.current_attempt_id, {"rule_pack_hash": job.rule_pack_hash, "case_hashes": sorted(case.case_hash for case in cases.values()), "phase": phase})
        repository.mark_phase(run_id, phase, progress, event_type, title, title, payload={"job_kind": "calibration", "case_count": len(cases)})
        refs = []
        if phase == "case_prepare":
            artifact = repository.add_artifact(run_id, "calibration_case_manifest", "calibration-case-manifest.v1", {"corpus_version": config["corpus_version"], "cases": [{"case_id": case.case_id, "case_hash": case.case_hash, "cutoff_date": case.cutoff_date} for case in cases.values()]})
            refs.append(artifact.artifact_id)
        elif phase == "deterministic_replay":
            outputs = {case_id: _evaluate_case(case) for case_id, case in sorted(cases.items())}
            artifact = repository.add_artifact(run_id, "calibration_case_outputs", "calibration-case-outputs.v1", outputs)
            refs.append(artifact.artifact_id)
        elif phase == "metric_compare":
            metrics = _aggregate_metrics(pack.model_dump(mode="json"), outputs)
            artifact = repository.add_artifact(run_id, "calibration_metrics", "calibration-metrics.v1", metrics)
            refs.append(artifact.artifact_id)
            _persist_case_results(run_id, outputs)
        elif phase == "review_package":
            artifact = repository.add_artifact(run_id, "calibration_review_package", "calibration-review-package.v1", {"rule_pack_id": pack.rule_pack_id, "rule_pack_hash": pack.manifest_hash, "gate_status": metrics.get("gate_status"), "metrics": metrics, "case_count": len(cases)})
            refs.append(artifact.artifact_id)
        steps.complete_step(step.step_id, {"phase": phase, "artifact_refs": refs, "gate_status": metrics.get("gate_status")}, refs)
        job = repository.get_job(run_id)
    calibration_run_id = _calibration_id_for_job(run_id)
    gate_status = metrics.get("gate_status", "failed")
    with connect() as conn:
        conn.execute("UPDATE calibration_runs SET status = 'completed', metrics_json = ?, gate_status = ?, completed_at = ? WHERE calibration_run_id = ?", (dumps(metrics), gate_status, _now(), calibration_run_id))
        if gate_status != "passed":
            conn.execute(
                "INSERT INTO review_cases(review_id, review_type, resource_type, resource_id, severity, status, reason, payload_json, created_at) VALUES (?, 'calibration_failure', 'calibration_run', ?, 'critical', 'open', 'Calibration promotion gates were not met', ?, ?)",
                (f"rev_{uuid4().hex[:16]}", calibration_run_id, dumps(metrics), _now()),
            )
    return repository.update_job_status(run_id, status="completed", phase="review_package", progress=100, terminal_reason=f"calibration_{gate_status}", completed=True)


def _evaluate_case(case: CalibrationCase) -> dict:
    result = run_war_room(WarRoomScenarioRequest(**case.input_snapshot))
    ranking = [item.code for item in sorted(result.country_agents, key=lambda item: item.risk_score, reverse=True)]
    top3 = ranking[:3]
    expected = case.labels
    batch = build_mock_agent_batch(result, run_id=f"calibration_{case.case_id}", seed=case.input_snapshot.get("seed"))
    decisions = evaluate_action_proposals(batch.proposals, batch.constraint_context)
    probe = batch.proposals[0].model_copy(update={"proposal_id": f"probe_{case.case_id}_invalid", "target_ids": ["UNKNOWN_ENTITY"]})
    probe_decision = evaluate_action_proposals([probe], batch.constraint_context)[0]
    expected_turns = expected.get("turning_points", [])
    actual_turns = [item.day for item in result.timeline if item.turning_point]
    return {
        "case_id": case.case_id,
        "result_hash_match": stable_hash(result.model_dump(mode="json")) == expected.get("result_hash"),
        "risk_spearman": _spearman(ranking, expected.get("risk_ranking", [])),
        "top3_overlap": len(set(top3) & set(expected.get("top3_countries", []))) / 3,
        "supply_chain_direction_accuracy": _mapping_accuracy(_chain_directions(result), expected.get("supply_chain_directions", {})),
        "turning_point_error_days": _turning_error(actual_turns, expected_turns),
        "critical_detected": probe_decision.outcome == "rejected",
        "critical_false_accept": int(probe_decision.outcome == "accepted"),
        "agent_outcome_agreement": _mapping_accuracy(_outcome_counts(decisions), expected.get("agent_outcomes", {})),
        "data_coverage": 1.0 if case.evidence and case.case_hash and case.cutoff_date else 0.0,
        "output_hash": stable_hash(result.model_dump(mode="json")),
    }


def _aggregate_metrics(pack: dict, outputs: dict[str, dict]) -> dict:
    rows = list(outputs.values())
    count = max(1, len(rows))
    avg = lambda key: sum(float(row[key]) for row in rows) / count
    implementation_available = all(pack.get(key) == value for key, value in SUPPORTED.items())
    metrics = {
        "case_count": len(rows),
        "deterministic_regression": sum(bool(row["result_hash_match"]) for row in rows) / count,
        "risk_spearman": avg("risk_spearman"),
        "top3_overlap": avg("top3_overlap"),
        "supply_chain_direction_accuracy": avg("supply_chain_direction_accuracy"),
        "turning_point_error_days": avg("turning_point_error_days"),
        "critical_violation_recall": sum(bool(row["critical_detected"]) for row in rows) / count,
        "critical_false_accept": sum(int(row["critical_false_accept"]) for row in rows),
        "agent_outcome_agreement": avg("agent_outcome_agreement"),
        "data_coverage": avg("data_coverage"),
        "implementation_available": implementation_available,
    }
    baseline = _active_baseline_metrics(pack.get("rule_pack_id"))
    regressions = []
    if baseline:
        for key in ("supply_chain_direction_accuracy", "top3_overlap", "agent_outcome_agreement"):
            regressions.append(max(0.0, float(baseline.get(key, 0)) - float(metrics.get(key, 0))))
    metrics["max_regression_pp"] = round(max(regressions, default=0.0) * 100, 3)
    metrics["gates"] = {
        "deterministic_regression": metrics["deterministic_regression"] == 1,
        "critical_violation_recall": metrics["critical_violation_recall"] == 1,
        "critical_false_accept": metrics["critical_false_accept"] == 0,
        "historical_direction_accuracy": metrics["supply_chain_direction_accuracy"] >= 0.70,
        "top3_overlap": metrics["top3_overlap"] >= 0.60,
        "implementation_available": implementation_available,
        "no_material_regression": metrics["max_regression_pp"] <= 5,
    }
    metrics["gate_status"] = "passed" if len(rows) >= 30 and all(metrics["gates"].values()) else "failed"
    return metrics


def _active_baseline_metrics(candidate_rule_pack_id: str | None) -> dict:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT c.metrics_json FROM calibration_runs c JOIN rule_packs r ON r.rule_pack_id = c.rule_pack_id
            WHERE r.status = 'active' AND c.status = 'completed' AND c.gate_status = 'passed'
              AND c.rule_pack_id != ? ORDER BY c.completed_at DESC LIMIT 1
            """,
            (candidate_rule_pack_id or "",),
        ).fetchone()
    return loads(row["metrics_json"], {}) if row else {}


def _persist_case_results(run_id: str, outputs: dict[str, dict]) -> None:
    calibration_run_id = _calibration_id_for_job(run_id)
    with connect() as conn:
        for case_id, output in outputs.items():
            conn.execute(
                "INSERT OR REPLACE INTO calibration_results(result_id, calibration_run_id, case_id, metrics_json, passed, result_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (f"cr_{stable_hash({'run': calibration_run_id, 'case': case_id})[:16]}", calibration_run_id, case_id, dumps(output), int(bool(output["result_hash_match"])), stable_hash(output), _now()),
            )


def _calibration_id_for_job(run_id: str) -> str:
    with connect() as conn:
        row = conn.execute("SELECT calibration_run_id FROM calibration_runs WHERE lifecycle_run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise RuntimeError("Calibration lifecycle record is missing")
    return row[0]


def _boundary_control(job: RunJobStatus) -> RunJobStatus | None:
    current = repository.get_job(job.run_id)
    if current.status == "cancelling":
        return repository.update_job_status(job.run_id, status="cancelled", progress=current.progress, terminal_reason="user_cancelled", completed=True)
    if current.status == "pausing":
        return repository.update_job_status(job.run_id, status="paused", progress=current.progress)
    return current if current.status in {"cancelled", "paused", "failed", "completed"} else None


def _ensure_calibration_project() -> str:
    project_id = "project_system_calibration"
    now = _now()
    with connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO research_projects
            (project_id, title, question, region, asset_scope, event_window_days, event_types, mode, scenario_config, status, created_at, updated_at)
            VALUES (?, 'System calibration', 'Rule Pack historical calibration', 'global', 'internal', 30, '[]', 'calibration', '{}', 'ready', ?, ?)
            """,
            (project_id, now, now),
        )
    return project_id


def _case_from_row(row) -> CalibrationCase:
    return CalibrationCase(
        case_id=row["case_id"], version=row["version"], category=row["category"], title=row["title"],
        cutoff_date=row["cutoff_date"], observation_window_days=int(row["observation_window_days"]),
        input_snapshot=loads(row["input_snapshot"], {}), labels=loads(row["labels_json"], {}),
        evidence=loads(row["evidence_json"], []), label_confidence=float(row["label_confidence"]),
        case_hash=row["case_hash"], is_active=bool(row["is_active"]),
    )


def _chain_directions(result) -> dict[str, str]:
    baseline = {item.key: item.pressure_score for item in SUPPLY_CHAINS}
    return {item.key: ("up" if item.pressure_score >= baseline.get(item.key, 0) else "down") for item in result.supply_chains}


def _outcome_counts(decisions) -> dict[str, int]:
    counts = {"accepted": 0, "rejected": 0, "constrained": 0, "expired": 0}
    for decision in decisions:
        counts[decision.outcome] = counts.get(decision.outcome, 0) + 1
    return counts


def _mapping_accuracy(actual: dict, expected: dict) -> float:
    keys = set(expected)
    return sum(actual.get(key) == expected.get(key) for key in keys) / len(keys) if keys else 1.0


def _spearman(actual: list[str], expected: list[str]) -> float:
    common = [item for item in expected if item in actual]
    if len(common) < 2:
        return 0.0
    ar = {item: actual.index(item) for item in common}
    er = {item: expected.index(item) for item in common}
    d2 = sum((ar[item] - er[item]) ** 2 for item in common)
    n = len(common)
    return max(-1.0, min(1.0, 1 - (6 * d2) / (n * (n * n - 1))))


def _turning_error(actual: list[int], expected: list[int]) -> float:
    if not expected:
        return 0.0 if not actual else float(max(actual))
    if not actual:
        return float(max(expected))
    return sum(abs(value - actual[min(index, len(actual) - 1)]) for index, value in enumerate(expected)) / len(expected)


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
