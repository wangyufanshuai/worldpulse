from __future__ import annotations

from datetime import datetime, timedelta
import os
from uuid import uuid4
from fastapi import HTTPException

from app.core.evaluation_models import EvaluationBatchCreateRequest, EvaluationBatch, EvaluationCase, EvaluationMember, EvaluationMetric, EvaluationReport, EvaluationRuntimeProfile, EvaluationSuiteManifest, HistoricalBenchmarkReport, HistoricalEvaluationCreateRequest
from app.core.evaluation_models import EvaluationVerificationResult
from app.core.models import RunJobCreateRequest, WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads
from app.db.postgres import is_postgres_url
from app.services.rule_packs import active_rule_pack
from app.services.run_lifecycle import repository as lifecycle_repository
from .corpus import suite_manifest
from .gates import ensure_gate_manifest, list_verification_results, verify_member
from .metrics import (
    average as _average,
    average_optional as _average_optional,
    historical_case_metrics as _historical_case_metrics,
)
from .observation import (
    aggregate_agent_observations as _aggregate_agent_observations,
    agent_outcome_observation as _agent_outcome_observation,
)
from .mappers import batch_from_row, case_from_row, member_from_row
from .coordinator import finalize_evaluation_batch, reconcile_evaluation
from . import benchmark

TERMINAL = {"completed", "cancelled", "failed"}

class EvaluationService:
    def __init__(self):
        init_db()

    def ensure_suite(self) -> EvaluationSuiteManifest:
        manifest = suite_manifest()
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_suites WHERE suite_id = ?", (manifest["suite_id"],)).fetchone()
            if row is None:
                conn.execute("INSERT INTO evaluation_suites (suite_id,schema_version,version,status,manifest_json,manifest_hash,created_at) VALUES (?,?,?,?,?,?,?)", (manifest["suite_id"], manifest["schema_version"], manifest["version"], "active", dumps({k: v for k,v in manifest.items() if k != "cases"}), manifest["manifest_hash"], now))
                for item in manifest["cases"]:
                    conn.execute("INSERT INTO evaluation_cases (case_id,suite_id,version,domain,title,input_json,qualitative_expectations_json,safety_probes_json,evidence_json,case_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (item["case_id"], item["suite_id"], item["version"], item["domain"], item["title"], dumps(item["input"]), dumps(item["qualitative_expectations"]), dumps(item["safety_probes"]), dumps(item["evidence"]), item["case_hash"], now))
            elif row["manifest_hash"] != manifest["manifest_hash"]:
                raise HTTPException(status_code=409, detail="Evaluation suite manifest hash mismatch")
        return self.get_suite(manifest["suite_id"])

    def get_suite(self, suite_id: str) -> EvaluationSuiteManifest:
        with connect() as conn:
            row = conn.execute("SELECT s.*, COUNT(c.case_id) AS case_count FROM evaluation_suites s LEFT JOIN evaluation_cases c ON c.suite_id = s.suite_id WHERE s.suite_id = ? GROUP BY s.suite_id", (suite_id,)).fetchone()
        if row is None: raise HTTPException(status_code=404, detail="Unknown evaluation suite")
        return EvaluationSuiteManifest(suite_id=row["suite_id"], schema_version=row["schema_version"], version=row["version"], status=row["status"], manifest=loads(row["manifest_json"], {}), manifest_hash=row["manifest_hash"], case_count=int(row["case_count"] or 0), created_at=row["created_at"])

    def list_suites(self) -> list[EvaluationSuiteManifest]:
        self.ensure_suite()
        with connect() as conn: ids = [row["suite_id"] for row in conn.execute("SELECT suite_id FROM evaluation_suites ORDER BY created_at")]
        return [self.get_suite(item) for item in ids]

    def list_cases(self, suite_id: str | None = None) -> list[EvaluationCase]:
        self.ensure_suite()
        with connect() as conn:
            rows = conn.execute("SELECT * FROM evaluation_cases WHERE is_active = 1" + (" AND suite_id = ?" if suite_id else "") + " ORDER BY case_id", ((suite_id,) if suite_id else ())).fetchall()
        return [case_from_row(row) for row in rows]

    def create_batch(self, organization_id: str, actor, payload: EvaluationBatchCreateRequest, *, source_type: str = "standard", project_id: str | None = None, scenario_draft_id: str | None = None, suite_id: str | None = None) -> EvaluationBatch:
        suite = self.get_suite(suite_id) if suite_id else self.ensure_suite()
        gate = ensure_gate_manifest()
        provider = payload.provider
        if source_type == "standard" and provider != "mock": raise HTTPException(status_code=422, detail="Standard safety batches require mock provider")
        if source_type == "observation" and provider == "mock": raise HTTPException(status_code=422, detail="Observation batch requires an explicit live provider")
        if provider != "mock" and getattr(actor, "role", "viewer") != "admin": raise HTTPException(status_code=403, detail="Only admin can create live observation batches")
        case_ids = payload.case_ids or [item.case_id for item in self.list_cases(suite.suite_id)]
        if source_type == "observation" and len(case_ids) > 3: raise HTTPException(status_code=422, detail="Observation batches may contain at most 3 cases")
        available = {item.case_id: item for item in self.list_cases(suite.suite_id)}
        if any(case_id not in available for case_id in case_ids): raise HTTPException(status_code=422, detail="Unknown evaluation case")
        profile = EvaluationRuntimeProfile(provider=provider, model=("mock-deterministic-v1" if provider == "mock" else "configured-provider-default"))
        profile_hash = stable_hash(profile.model_dump(mode="json"))
        pack = active_rule_pack()
        batch_id = f"eval_{uuid4().hex[:16]}"; now = datetime.now().isoformat(timespec="milliseconds")
        evaluation_track = {"standard": "engineering_standard", "observation": "live_observation", "project": "project_experiment"}[source_type]
        modes = [("deterministic", 1)] if source_type == "observation" else [("deterministic", 1), ("hybrid", 11), ("hybrid", 29), ("hybrid", 47), ("negotiation", 11), ("negotiation", 29), ("negotiation", 47)]
        total = len(case_ids) * len(modes)
        with connect() as conn:
            conn.execute("INSERT INTO evaluation_batches (batch_id,organization_id,project_id,scenario_draft_id,suite_id,suite_hash,rule_pack_id,rule_pack_hash,runtime_profile_json,runtime_profile_hash,provider_mode,source_type,status,total_members,created_by_user_id,created_at,updated_at,evaluation_track,gate_manifest_hash,root_batch_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (batch_id, organization_id, project_id, scenario_draft_id, suite.suite_id, suite.manifest_hash, pack.rule_pack_id, pack.manifest_hash, dumps(profile.model_dump(mode="json")), profile_hash, provider, source_type, "queued", total, getattr(actor, "user_id", None), now, now, evaluation_track, gate.manifest_hash, batch_id))
            conn.execute("INSERT INTO evaluation_event_counters(batch_id,next_seq) VALUES (?,1)", (batch_id,))
            for case_id in case_ids:
                for mode, seed in modes:
                    scenario = WarRoomScenarioRequest(**{**available[case_id].input, "seed": seed}).model_dump(mode="json")
                    conn.execute("INSERT INTO evaluation_members (member_id,batch_id,case_id,engine_mode,seed,status,input_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (f"member_{uuid4().hex[:16]}", batch_id, case_id, mode, seed, "pending", stable_hash(scenario), now, now))
        self.append_event(batch_id, "WORKER", "evaluation_prepare", "Evaluation batch queued", f"{total} real v2 child runs are scheduled", {"provider": provider, "member_count": total})
        return self.get_batch(batch_id)

    def create_standard_batch(self, organization_id: str, actor, payload: EvaluationBatchCreateRequest | None = None) -> EvaluationBatch:
        return self.create_batch(organization_id, actor, payload or EvaluationBatchCreateRequest(), source_type="standard")

    def create_historical_batch(self, organization_id: str, actor, payload: HistoricalEvaluationCreateRequest) -> EvaluationBatch:
        suite = benchmark.get_suite(payload.suite_id)
        if suite.status != "active":
            raise HTTPException(status_code=409, detail="Historical benchmark suite is not active")
        label_pack = benchmark.get_label_pack(organization_id, payload.label_pack_id)
        if label_pack.status != "active" or label_pack.suite_id != suite.suite_id:
            raise HTTPException(status_code=409, detail="An active matching sealed label pack is required")
        cases = benchmark.list_cases(suite.suite_id)
        if len(cases) != 120 or sum(item.split == "blind" for item in cases) != 30:
            raise HTTPException(status_code=409, detail="Historical benchmark suite is incomplete")
        gate = ensure_gate_manifest()
        pack = active_rule_pack()
        profile = EvaluationRuntimeProfile(provider="mock", model="mock-deterministic-v1")
        profile_hash = stable_hash(profile.model_dump(mode="json"))
        execution_suite_id = f"historical-execution.{suite.version}"
        execution_manifest = {"suite_id": execution_suite_id, "benchmark_suite_hash": suite.manifest_hash, "matrix": "120 deterministic + 30x7 blind"}
        execution_hash = stable_hash(execution_manifest)
        batch_id = f"eval_{uuid4().hex[:16]}"; now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            existing_suite = conn.execute("SELECT manifest_hash FROM evaluation_suites WHERE suite_id = ?", (execution_suite_id,)).fetchone()
            if existing_suite is None:
                conn.execute("INSERT INTO evaluation_suites (suite_id,schema_version,version,status,manifest_json,manifest_hash,created_at) VALUES (?,?,?,?,?,?,?)", (execution_suite_id, "evaluation-suite.v1", suite.version, "active", dumps(execution_manifest), execution_hash, now))
            elif existing_suite["manifest_hash"] != execution_hash:
                raise HTTPException(status_code=409, detail="Historical execution suite hash mismatch")
            member_specs: list[tuple[str, str, int, dict]] = []
            for item in cases:
                case_id = f"hist_{item.case_id}"
                self._ensure_evaluation_case(conn, case_id, execution_suite_id, item, item.scenario, now)
                member_specs.append((case_id, "deterministic", 1, item.scenario))
                if item.split == "blind":
                    sealed_case_id = f"hist_blind_{item.case_id}"
                    self._ensure_evaluation_case(conn, sealed_case_id, execution_suite_id, item, item.scenario, now)
                    member_specs.extend((sealed_case_id, mode, seed, item.scenario) for mode, seed in (("deterministic", 1), ("hybrid", 11), ("hybrid", 29), ("hybrid", 47), ("negotiation", 11), ("negotiation", 29), ("negotiation", 47)))
            if len(member_specs) != 330:
                raise HTTPException(status_code=409, detail="Historical execution matrix must contain exactly 330 members")
            conn.execute("""INSERT INTO evaluation_batches
                (batch_id,organization_id,suite_id,suite_hash,rule_pack_id,rule_pack_hash,runtime_profile_json,runtime_profile_hash,provider_mode,source_type,status,total_members,created_by_user_id,created_at,updated_at,evaluation_track,benchmark_suite_id,benchmark_suite_hash,label_pack_id,label_pack_hash,gate_manifest_hash,root_batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (batch_id, organization_id, execution_suite_id, execution_hash, pack.rule_pack_id, pack.manifest_hash, dumps(profile.model_dump(mode="json")), profile_hash, "mock", "standard", "queued", 330, getattr(actor, "user_id", None), now, now, "historical_blind", suite.suite_id, suite.manifest_hash, label_pack.label_pack_id, label_pack.manifest_hash, gate.manifest_hash, batch_id))
            conn.execute("INSERT INTO evaluation_event_counters(batch_id,next_seq) VALUES (?,1)", (batch_id,))
            for case_id, mode, seed, raw_scenario in member_specs:
                scenario = WarRoomScenarioRequest(**{**raw_scenario, "seed": seed}).model_dump(mode="json")
                conn.execute("INSERT INTO evaluation_members (member_id,batch_id,case_id,engine_mode,seed,status,input_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)", (f"member_{uuid4().hex[:16]}", batch_id, case_id, mode, seed, "pending", stable_hash(scenario), now, now))
        self.append_event(batch_id, "WORKER", "historical_prepare", "Historical release evaluation queued", "330 real Mock child runs are scheduled; blind labels remain sealed", {"member_count": 330, "benchmark_suite_hash": suite.manifest_hash})
        return self.get_batch(batch_id)

    def create_project_experiment(self, organization_id: str, project_id: str, draft_id: str, actor, payload: EvaluationBatchCreateRequest) -> EvaluationBatch:
        with connect() as conn:
            draft = conn.execute("SELECT status, draft_hash, evidence_pack_hash, scenario_json FROM scenario_drafts WHERE draft_id = ? AND project_id = ? AND organization_id = ?", (draft_id, project_id, organization_id)).fetchone()
        if draft is None: raise HTTPException(status_code=404, detail="Unknown Scenario Draft")
        if draft["status"] != "approved": raise HTTPException(status_code=409, detail="Only approved Scenario Drafts can create evaluations")
        scenario = WarRoomScenarioRequest(**loads(draft["scenario_json"], {})).model_dump(mode="json")
        scenario_hash = stable_hash(scenario)
        suite_id = "project-experiment.v1"
        suite_manifest_payload = {
            "suite_id": suite_id,
            "schema_version": "evaluation-suite.v1",
            "version": "1",
            "purpose": "approved Scenario Draft seven-member experiment",
        }
        suite_hash = stable_hash(suite_manifest_payload)
        case_id = f"project_case_{draft['draft_hash'][:20]}"
        case_payload = {
            "case_id": case_id,
            "suite_id": suite_id,
            "version": "1",
            "domain": "project",
            "title": f"Approved draft {draft_id}",
            "input": scenario,
            "qualitative_expectations": {"draft_hash": draft["draft_hash"], "evidence_pack_hash": draft["evidence_pack_hash"]},
            "safety_probes": {},
            "evidence": [{"draft_id": draft_id, "evidence_pack_hash": draft["evidence_pack_hash"]}],
        }
        case_hash = stable_hash(case_payload)
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            suite_row = conn.execute("SELECT manifest_hash FROM evaluation_suites WHERE suite_id = ?", (suite_id,)).fetchone()
            if suite_row is None:
                conn.execute("INSERT INTO evaluation_suites (suite_id,schema_version,version,status,manifest_json,manifest_hash,created_at) VALUES (?,?,?,?,?,?,?)", (suite_id, "evaluation-suite.v1", "1", "active", dumps(suite_manifest_payload), suite_hash, now))
            elif suite_row["manifest_hash"] != suite_hash:
                raise HTTPException(status_code=409, detail="Project evaluation suite hash mismatch")
            case_row = conn.execute("SELECT case_hash FROM evaluation_cases WHERE case_id = ?", (case_id,)).fetchone()
            if case_row is None:
                conn.execute("INSERT INTO evaluation_cases (case_id,suite_id,version,domain,title,input_json,qualitative_expectations_json,safety_probes_json,evidence_json,case_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (case_id, suite_id, "1", "project", case_payload["title"], dumps(scenario), dumps(case_payload["qualitative_expectations"]), "{}", dumps(case_payload["evidence"]), case_hash, now))
            elif case_row["case_hash"] != case_hash:
                raise HTTPException(status_code=409, detail="Project evaluation case hash mismatch")
        payload = payload.model_copy(update={"case_ids": [case_id]})
        batch = self.create_batch(organization_id, actor, payload, source_type="project", project_id=project_id, scenario_draft_id=draft_id, suite_id=suite_id)
        with connect() as conn:
            conn.execute("UPDATE evaluation_batches SET scenario_draft_hash = ?, evidence_pack_hash = ? WHERE batch_id = ?", (draft["draft_hash"], draft["evidence_pack_hash"], batch.batch_id))
        return self.get_batch(batch.batch_id)

    def get_batch(self, batch_id: str, organization_id: str | None = None) -> EvaluationBatch:
        with connect() as conn: row = conn.execute("SELECT * FROM evaluation_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None or (organization_id is not None and row["organization_id"] != organization_id): raise HTTPException(status_code=404, detail="Unknown evaluation batch")
        return batch_from_row(row)

    def list_batches(self, organization_id: str) -> list[EvaluationBatch]:
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_batches WHERE organization_id = ? ORDER BY created_at DESC", (organization_id,)).fetchall()
        return [batch_from_row(row) for row in rows]

    def list_members(self, batch_id: str, organization_id: str | None = None) -> list[EvaluationMember]:
        self.get_batch(batch_id, organization_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_members WHERE batch_id = ? ORDER BY created_at, member_id", (batch_id,)).fetchall()
        return [member_from_row(row) for row in rows]

    def list_metrics(self, batch_id: str, organization_id: str | None = None) -> list[EvaluationMetric]:
        self.get_batch(batch_id, organization_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_metrics WHERE batch_id = ? ORDER BY created_at, metric_id", (batch_id,)).fetchall()
        return [EvaluationMetric(metric_id=row["metric_id"], batch_id=row["batch_id"], member_id=row["member_id"], scope=row["scope"], metric_key=row["metric_key"], value=loads(row["value_json"], {}), passed=bool(row["passed"]) if row["passed"] is not None else None, metric_hash=row["metric_hash"], created_at=row["created_at"]) for row in rows]

    def list_events(self, batch_id: str, after_seq: int = 0, organization_id: str | None = None) -> list[dict]:
        self.get_batch(batch_id, organization_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_events WHERE batch_id = ? AND seq > ? ORDER BY seq", (batch_id, after_seq)).fetchall()
        return [{"batch_id": row["batch_id"], "seq": row["seq"], "event_type": row["event_type"], "phase": row["phase"], "title": row["title"], "detail": row["detail"], "payload": loads(row["payload_json"], {}), "created_at": row["created_at"]} for row in rows]

    def append_event(self, batch_id: str, event_type: str, phase: str, title: str, detail: str, payload: dict | None = None) -> dict:
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            row = conn.execute("SELECT next_seq FROM evaluation_event_counters WHERE batch_id = ?", (batch_id,)).fetchone()
            if row is None: raise HTTPException(status_code=404, detail="Unknown evaluation batch")
            seq = int(row["next_seq"]); conn.execute("UPDATE evaluation_event_counters SET next_seq = ? WHERE batch_id = ?", (seq + 1, batch_id))
            conn.execute("INSERT INTO evaluation_events(batch_id,seq,event_type,phase,title,detail,payload_json,created_at) VALUES (?,?,?,?,?,?,?,?)", (batch_id, seq, event_type, phase, title, detail, dumps(payload or {}), now))
        return {"batch_id": batch_id, "seq": seq, "event_type": event_type, "phase": phase, "title": title, "detail": detail, "payload": payload or {}, "created_at": now}

    def control(self, batch_id: str, action: str, organization_id: str | None = None) -> EvaluationBatch:
        batch = self.get_batch(batch_id, organization_id)
        transitions = {"pause": ("pausing", {"queued", "running"}), "resume": ("running", {"paused"}), "cancel": ("cancelling", {"queued", "running", "paused"})}
        if action not in transitions: raise HTTPException(status_code=422, detail="Unsupported evaluation control")
        target, allowed = transitions[action]
        if batch.status not in allowed: raise HTTPException(status_code=409, detail=f"Cannot {action} evaluation in {batch.status}")
        now = datetime.now().isoformat(timespec="milliseconds")
        members = self.list_members(batch_id)
        with connect() as conn:
            conn.execute("UPDATE evaluation_batches SET status = ?, updated_at = ? WHERE batch_id = ?", (target, now, batch_id))
            if action == "cancel":
                conn.execute("UPDATE evaluation_members SET status = 'cancelled', completed_at = ?, updated_at = ? WHERE batch_id = ? AND status = 'pending'", (now, now, batch_id))
                if batch.status == "queued" or (batch.status == "paused" and not any(item.run_id for item in members)):
                    conn.execute("UPDATE evaluation_batches SET status = 'cancelled', completed_at = ? WHERE batch_id = ?", (now, batch_id))
            elif action == "pause" and batch.status == "queued":
                conn.execute("UPDATE evaluation_batches SET status = 'paused' WHERE batch_id = ?", (batch_id,))
        for member in members:
            if not member.run_id or member.status in TERMINAL:
                continue
            try:
                if action == "pause": lifecycle_repository.pause_job(member.run_id)
                elif action == "resume": lifecycle_repository.resume_job(member.run_id)
                else: lifecycle_repository.cancel_job(member.run_id)
            except HTTPException as exc:
                if exc.status_code != 409: raise
        self.append_event(batch_id, "WORKER", "evaluation_control", f"Evaluation {action} requested", target)
        return self.get_batch(batch_id)

    def retry(self, batch_id: str, actor, organization_id: str | None = None) -> EvaluationBatch:
        old = self.get_batch(batch_id, organization_id)
        if old.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail=f"Cannot retry evaluation in {old.status}")
        old_members = self.list_members(batch_id)
        retry_id = f"eval_{uuid4().hex[:16]}"
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            conn.execute("""INSERT INTO evaluation_batches
                (batch_id,organization_id,project_id,scenario_draft_id,scenario_draft_hash,evidence_pack_hash,
                 suite_id,suite_hash,rule_pack_id,rule_pack_hash,runtime_profile_json,runtime_profile_hash,
                 provider_mode,source_type,status,parent_batch_id,total_members,created_by_user_id,created_at,updated_at,
                 evaluation_track,benchmark_suite_id,benchmark_suite_hash,label_pack_id,label_pack_hash,gate_manifest_hash,root_batch_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (retry_id, old.organization_id, old.project_id, old.scenario_draft_id, old.scenario_draft_hash, old.evidence_pack_hash,
                 old.suite_id, old.suite_hash, old.rule_pack_id, old.rule_pack_hash, dumps(old.runtime_profile), old.runtime_profile_hash,
                 old.provider_mode, old.source_type, "queued", old.batch_id, len(old_members), getattr(actor, "user_id", None), now, now,
                 old.evaluation_track, old.benchmark_suite_id, old.benchmark_suite_hash, old.label_pack_id, old.label_pack_hash,
                 old.gate_manifest_hash, old.root_batch_id or old.batch_id))
            conn.execute("INSERT INTO evaluation_event_counters(batch_id,next_seq) VALUES (?,1)", (retry_id,))
            for item in old_members:
                conn.execute("""INSERT INTO evaluation_members
                    (member_id,batch_id,case_id,engine_mode,seed,status,input_hash,expected_baseline_hash,created_at,updated_at)
                    VALUES (?,?,?,?,?,'pending',?,?,?,?)""",
                    (f"member_{uuid4().hex[:16]}", retry_id, item.case_id, item.engine_mode, item.seed,
                     item.input_hash, item.expected_baseline_hash, now, now))
        self.append_event(retry_id, "WORKER", "evaluation_retry", "Evaluation retry queued", "A complete new member matrix was created; no prior metrics or child runs were reused", {"parent_batch_id": old.batch_id, "root_batch_id": old.root_batch_id or old.batch_id})
        return self.get_batch(retry_id)

    def report(self, batch_id: str, organization_id: str | None = None) -> EvaluationReport:
        batch = self.get_batch(batch_id, organization_id); metrics = self.list_metrics(batch_id); members = self.list_members(batch_id)
        safety = {item.metric_key: item.passed for item in metrics if item.scope == "safety"}
        passed = batch.status == "completed" and all(value is not False for value in safety.values())
        eligibility = {"deterministic": passed, "hybrid": passed and batch.provider_mode == "mock", "negotiation": passed and batch.provider_mode == "mock"}
        report_hash = stable_hash({"batch": batch.model_dump(mode="json"), "metrics": [item.model_dump(mode="json") for item in metrics], "eligibility": eligibility})
        from app.core.evaluation_models import EvaluationModeScorecard
        scorecards = [EvaluationModeScorecard(mode=mode, member_count=sum(1 for item in members if item.engine_mode == mode), completed_count=sum(1 for item in members if item.engine_mode == mode and item.status == "completed"), metrics={"seeds": sorted({item.seed for item in members if item.engine_mode == mode})}) for mode in ("deterministic", "hybrid", "negotiation")]
        return EvaluationReport(batch=batch, safety_gate={"status": "passed" if passed else "pending" if batch.status != "completed" else "failed", "checks": safety}, scorecards=scorecards, mode_eligibility=eligibility, report_hash=report_hash)

    def historical_report(self, batch_id: str, organization_id: str) -> HistoricalBenchmarkReport:
        batch = self.get_batch(batch_id, organization_id)
        if batch.evaluation_track != "historical_blind" or not batch.benchmark_suite_id:
            raise HTTPException(status_code=409, detail="Evaluation batch is not a historical release batch")
        suite = benchmark.get_suite(batch.benchmark_suite_id)
        verification = list_verification_results(batch_id)
        aggregate = dict(batch.metrics.get("historical_observation") or {})
        report_hash = stable_hash({
            "batch_id": batch.batch_id,
            "benchmark_suite_hash": suite.manifest_hash,
            "verification_hashes": [item.verification_hash for item in verification],
            "aggregate_metrics": aggregate,
            "blind_labels_redacted": True,
        })
        return HistoricalBenchmarkReport(
            batch=batch,
            suite=suite,
            verification=verification,
            aggregate_metrics=aggregate,
            blind_labels_redacted=True,
            report_hash=report_hash,
        )

    def list_verification_results(self, batch_id: str) -> list[EvaluationVerificationResult]:
        return list_verification_results(batch_id)

    def reconcile(self, *, worker_id: str | None = None) -> int:
        return reconcile_evaluation(self, worker_id=worker_id)

    def _finalize_if_ready(self, batch_id: str) -> None:
        finalize_evaluation_batch(self, batch_id)

    def _ensure_system_project(self, organization_id: str) -> str:
        project_id = f"system_evaluation_{stable_hash(organization_id)[:12]}"
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            exists = conn.execute("SELECT project_id FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
            if exists: return project_id
            conn.execute("INSERT INTO research_projects (project_id,title,question,region,asset_scope,event_window_days,event_types,mode,scenario_config,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (project_id, "System Evaluation", "Cross-mode engineering evaluation", "global", "[]", 30, "[]", "war_room", "{}", "system", now, now))
            conn.execute("INSERT INTO organization_resources(organization_id,resource_type,resource_id,created_at) VALUES (?, 'project', ?, ?) ON CONFLICT(organization_id,resource_type,resource_id) DO NOTHING", (organization_id, project_id, now))
        return project_id

    def _ensure_evaluation_case(self, conn, case_id: str, suite_id: str, historical_case, scenario: dict, now: str) -> None:
        payload = {
            "case_id": case_id,
            "suite_id": suite_id,
            "version": historical_case.version,
            "domain": historical_case.domain,
            "title": historical_case.title,
            "input": WarRoomScenarioRequest(**scenario).model_dump(mode="json"),
            "qualitative_expectations": {"historical_case_hash": historical_case.case_hash, "split": historical_case.split},
            "safety_probes": {},
            "evidence": [{"evidence_hash": item.evidence_hash, "role": item.evidence_role} for item in historical_case.evidence],
        }
        case_hash = stable_hash(payload)
        row = conn.execute("SELECT case_hash FROM evaluation_cases WHERE case_id = ?", (case_id,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO evaluation_cases (case_id,suite_id,version,domain,title,input_json,qualitative_expectations_json,safety_probes_json,evidence_json,case_hash,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)", (case_id, suite_id, historical_case.version, historical_case.domain, historical_case.title, dumps(payload["input"]), dumps(payload["qualitative_expectations"]), "{}", dumps(payload["evidence"]), case_hash, now))
        elif row["case_hash"] != case_hash:
            raise HTTPException(status_code=409, detail=f"Historical evaluation case hash mismatch: {case_id}")

    def _historical_observation_metrics(self, batch: EvaluationBatch, members: list[EvaluationMember]) -> dict:
        if not batch.benchmark_suite_id or not batch.label_pack_id:
            raise ValueError("Historical batch lineage is incomplete")
        label_pack = benchmark.get_label_pack(batch.organization_id, batch.label_pack_id)
        root_id = batch.root_batch_id or batch.batch_id
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            current = conn.execute("SELECT status,bound_root_batch_id FROM historical_label_packs WHERE label_pack_id = ?", (label_pack.label_pack_id,)).fetchone()
            if current is None or current["status"] not in {"active", "consuming"} or current["bound_root_batch_id"] not in {None, root_id}:
                raise ValueError("Sealed label pack is unavailable or bound to another release root")
            conn.execute("UPDATE historical_label_packs SET status='consuming', bound_root_batch_id=?, comparison_started_at=COALESCE(comparison_started_at,?) WHERE label_pack_id=?", (root_id, now, label_pack.label_pack_id))
        labels_payload = benchmark.decrypt_labels(benchmark.get_label_pack(batch.organization_id, batch.label_pack_id))
        blind_labels = labels_payload.get("labels", labels_payload)
        if not isinstance(blind_labels, dict):
            raise ValueError("Blind label payload is invalid")
        cases = {item.case_id: item for item in benchmark.list_cases(batch.benchmark_suite_id)}
        rows: list[dict] = []
        agent_rows: list[dict] = []
        for member in members:
            if not member.case_id.startswith("hist_"):
                continue
            historical_id = member.case_id.removeprefix("hist_blind_") if member.case_id.startswith("hist_blind_") else member.case_id.removeprefix("hist_")
            case = cases.get(historical_id)
            if case is None or not member.run_id:
                raise ValueError("Historical case lineage is invalid")
            labels = case.labels if case.split == "development" else blind_labels.get(historical_id)
            if not isinstance(labels, dict):
                raise ValueError("Historical labels are incomplete")
            if member.case_id.startswith("hist_blind_") and member.engine_mode in {"hybrid", "negotiation"}:
                observation = _agent_outcome_observation(member.run_id, member.engine_mode, labels)
                agent_rows.append({
                    "case_id": historical_id,
                    "mode": member.engine_mode,
                    "seed": member.seed,
                    **observation,
                })
                continue
            if member.engine_mode != "deterministic" or member.case_id.startswith("hist_blind_"):
                continue
            result = lifecycle_repository.get_latest_artifact_content(member.run_id, "war_room_result") or {}
            rows.append(_historical_case_metrics(result, labels, case.label_confidence, len(case.evidence)))
        if len(rows) != 120:
            raise ValueError("Historical comparison requires exactly 120 deterministic results")
        aggregate = {
            "status": "observed",
            "case_count": 120,
            "risk_spearman": _average(rows, "risk_spearman"),
            "top3_overlap": _average(rows, "top3_overlap"),
            "supply_chain_direction_accuracy": _average(rows, "supply_chain_direction_accuracy"),
            "turning_point_error_days": _average(rows, "turning_point_error_days"),
            "agent_outcome_agreement": _average_optional(rows, "agent_outcome_agreement"),
            "agent_outcome_denominator": sum(item.get("agent_outcome_agreement") is not None for item in rows),
            "agent_outcome_not_applicable": sum(item.get("agent_outcome_agreement") is None for item in rows),
            "agent_outcome_observation": _aggregate_agent_observations(agent_rows),
            "data_coverage": _average(rows, "data_coverage"),
            "label_confidence": _average(rows, "label_confidence"),
            "metric_verifier_version": "historical-observation.v2",
            "promotion_effect": "observation_only",
            "real_world_accuracy_claim": False,
            "blind_labels_redacted": True,
        }
        with connect() as conn:
            conn.execute("UPDATE historical_label_packs SET status='consumed', consumed_at=? WHERE label_pack_id=? AND bound_root_batch_id=?", (now, label_pack.label_pack_id, root_id))
        return aggregate

    def _case(self, row) -> EvaluationCase:
        return case_from_row(row)

    def _batch(self, row) -> EvaluationBatch:
        return batch_from_row(row)

    def _member(self, row) -> EvaluationMember:
        return member_from_row(row)
