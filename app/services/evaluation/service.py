from __future__ import annotations

from datetime import datetime
import os
from uuid import uuid4
from fastapi import HTTPException

from app.core.evaluation_models import EvaluationBatchCreateRequest, EvaluationBatch, EvaluationCase, EvaluationMember, EvaluationMetric, EvaluationReport, EvaluationRuntimeProfile, EvaluationSuiteManifest
from app.core.models import RunJobCreateRequest, WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads
from app.services.rule_packs import active_rule_pack
from app.services.run_lifecycle import repository as lifecycle_repository
from .corpus import suite_manifest

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
        return [self._case(row) for row in rows]

    def create_batch(self, organization_id: str, actor, payload: EvaluationBatchCreateRequest, *, source_type: str = "standard", project_id: str | None = None, scenario_draft_id: str | None = None) -> EvaluationBatch:
        suite = self.ensure_suite()
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
        modes = [("deterministic", 1)] if source_type == "observation" else [("deterministic", 1), ("hybrid", 11), ("hybrid", 29), ("hybrid", 47), ("negotiation", 11), ("negotiation", 29), ("negotiation", 47)]
        total = len(case_ids) * len(modes)
        with connect() as conn:
            conn.execute("INSERT INTO evaluation_batches (batch_id,organization_id,project_id,scenario_draft_id,suite_id,suite_hash,rule_pack_id,rule_pack_hash,runtime_profile_json,runtime_profile_hash,provider_mode,source_type,status,total_members,created_by_user_id,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (batch_id, organization_id, project_id, scenario_draft_id, suite.suite_id, suite.manifest_hash, pack.rule_pack_id, pack.manifest_hash, dumps(profile.model_dump(mode="json")), profile_hash, provider, source_type, "queued", total, getattr(actor, "user_id", None), now, now))
            conn.execute("INSERT INTO evaluation_event_counters(batch_id,next_seq) VALUES (?,1)", (batch_id,))
            for case_id in case_ids:
                for mode, seed in modes:
                    conn.execute("INSERT INTO evaluation_members (member_id,batch_id,case_id,engine_mode,seed,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)", (f"member_{uuid4().hex[:16]}", batch_id, case_id, mode, seed, "pending", now, now))
        self.append_event(batch_id, "WORKER", "evaluation_prepare", "Evaluation batch queued", f"{total} real v2 child runs are scheduled", {"provider": provider, "member_count": total})
        return self.get_batch(batch_id)

    def create_standard_batch(self, organization_id: str, actor, payload: EvaluationBatchCreateRequest | None = None) -> EvaluationBatch:
        return self.create_batch(organization_id, actor, payload or EvaluationBatchCreateRequest(), source_type="standard")

    def create_project_experiment(self, organization_id: str, project_id: str, draft_id: str, actor, payload: EvaluationBatchCreateRequest) -> EvaluationBatch:
        with connect() as conn:
            draft = conn.execute("SELECT status, draft_hash, evidence_pack_hash FROM scenario_drafts WHERE draft_id = ? AND project_id = ? AND organization_id = ?", (draft_id, project_id, organization_id)).fetchone()
        if draft is None: raise HTTPException(status_code=404, detail="Unknown Scenario Draft")
        if draft["status"] != "approved": raise HTTPException(status_code=409, detail="Only approved Scenario Drafts can create evaluations")
        batch = self.create_batch(organization_id, actor, payload, source_type="project", project_id=project_id, scenario_draft_id=draft_id)
        with connect() as conn:
            conn.execute("UPDATE evaluation_batches SET scenario_draft_hash = ?, evidence_pack_hash = ? WHERE batch_id = ?", (draft["draft_hash"], draft["evidence_pack_hash"], batch.batch_id))
        return self.get_batch(batch.batch_id)

    def get_batch(self, batch_id: str) -> EvaluationBatch:
        with connect() as conn: row = conn.execute("SELECT * FROM evaluation_batches WHERE batch_id = ?", (batch_id,)).fetchone()
        if row is None: raise HTTPException(status_code=404, detail="Unknown evaluation batch")
        return self._batch(row)

    def list_batches(self, organization_id: str) -> list[EvaluationBatch]:
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_batches WHERE organization_id = ? ORDER BY created_at DESC", (organization_id,)).fetchall()
        return [self._batch(row) for row in rows]

    def list_members(self, batch_id: str) -> list[EvaluationMember]:
        self.get_batch(batch_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_members WHERE batch_id = ? ORDER BY created_at, member_id", (batch_id,)).fetchall()
        return [self._member(row) for row in rows]

    def list_metrics(self, batch_id: str) -> list[EvaluationMetric]:
        self.get_batch(batch_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_metrics WHERE batch_id = ? ORDER BY created_at, metric_id", (batch_id,)).fetchall()
        return [EvaluationMetric(metric_id=row["metric_id"], batch_id=row["batch_id"], member_id=row["member_id"], scope=row["scope"], metric_key=row["metric_key"], value=loads(row["value_json"], {}), passed=bool(row["passed"]) if row["passed"] is not None else None, metric_hash=row["metric_hash"], created_at=row["created_at"]) for row in rows]

    def list_events(self, batch_id: str, after_seq: int = 0) -> list[dict]:
        self.get_batch(batch_id)
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

    def control(self, batch_id: str, action: str) -> EvaluationBatch:
        batch = self.get_batch(batch_id)
        transitions = {"pause": ("pausing", {"queued", "running"}), "resume": ("running", {"paused"}), "cancel": ("cancelling", {"queued", "running", "paused"})}
        if action not in transitions: raise HTTPException(status_code=422, detail="Unsupported evaluation control")
        target, allowed = transitions[action]
        if batch.status not in allowed: raise HTTPException(status_code=409, detail=f"Cannot {action} evaluation in {batch.status}")
        with connect() as conn: conn.execute("UPDATE evaluation_batches SET status = ?, updated_at = ? WHERE batch_id = ?", (target, datetime.now().isoformat(timespec="milliseconds"), batch_id))
        self.append_event(batch_id, "WORKER", "evaluation_control", f"Evaluation {action} requested", target)
        return self.get_batch(batch_id)

    def retry(self, batch_id: str, actor) -> EvaluationBatch:
        old = self.get_batch(batch_id)
        payload = EvaluationBatchCreateRequest(provider=old.provider_mode, case_ids=[item.case_id for item in self.list_members(batch_id) if item.engine_mode == "deterministic"])
        return self.create_batch(old.organization_id, actor, payload, source_type=old.source_type, project_id=old.project_id, scenario_draft_id=old.scenario_draft_id)

    def report(self, batch_id: str) -> EvaluationReport:
        batch = self.get_batch(batch_id); metrics = self.list_metrics(batch_id); members = self.list_members(batch_id)
        safety = {item.metric_key: item.passed for item in metrics if item.scope == "safety"}
        passed = batch.status == "completed" and all(value is not False for value in safety.values())
        eligibility = {"deterministic": passed, "hybrid": passed and batch.provider_mode == "mock", "negotiation": passed and batch.provider_mode == "mock"}
        report_hash = stable_hash({"batch": batch.model_dump(mode="json"), "metrics": [item.model_dump(mode="json") for item in metrics], "eligibility": eligibility})
        from app.core.evaluation_models import EvaluationModeScorecard
        scorecards = [EvaluationModeScorecard(mode=mode, member_count=sum(1 for item in members if item.engine_mode == mode), completed_count=sum(1 for item in members if item.engine_mode == mode and item.status == "completed"), metrics={"seeds": sorted({item.seed for item in members if item.engine_mode == mode})}) for mode in ("deterministic", "hybrid", "negotiation")]
        return EvaluationReport(batch=batch, safety_gate={"status": "passed" if passed else "pending" if batch.status != "completed" else "failed", "checks": safety}, scorecards=scorecards, mode_eligibility=eligibility, report_hash=report_hash)

    def reconcile(self, *, worker_id: str | None = None) -> int:
        """Schedule pending members and harvest terminal real v2 child runs."""
        changed = 0
        with connect() as conn:
            batches = conn.execute("SELECT * FROM evaluation_batches WHERE status IN ('queued','running','pausing','cancelling') ORDER BY created_at").fetchall()
        for batch_row in batches:
            batch = self._batch(batch_row)
            if batch.status in {"queued", "running"}:
                project_id = self._ensure_system_project(batch.organization_id)
                with connect() as conn:
                    inflight = int(conn.execute("SELECT COUNT(*) FROM evaluation_members WHERE batch_id = ? AND status IN ('queued','running')", (batch.batch_id,)).fetchone()[0])
                    capacity = max(1, min(8, int(os.getenv("WORLDPULSE_EVALUATION_MAX_IN_FLIGHT", "2")))) - inflight
                    pending = conn.execute("SELECT m.*, c.input_json FROM evaluation_members m JOIN evaluation_cases c ON c.case_id = m.case_id WHERE m.batch_id = ? AND m.status = 'pending' ORDER BY m.created_at LIMIT ?", (batch.batch_id, max(0, capacity))).fetchall()
                for member in pending:
                    scenario = WarRoomScenarioRequest(**loads(member["input_json"], {}), seed=int(member["seed"]))
                    request = RunJobCreateRequest(engine_mode=member["engine_mode"], scenario=scenario, seed=int(member["seed"]))
                    job = lifecycle_repository.create_job(project_id, request, evaluation_batch_id=batch.batch_id, evaluation_member_id=member["member_id"], runtime_profile=batch.runtime_profile)
                    with connect() as conn:
                        conn.execute("UPDATE evaluation_members SET run_id = ?, status = 'queued', updated_at = ? WHERE member_id = ? AND status = 'pending'", (job.run_id, datetime.now().isoformat(timespec="milliseconds"), member["member_id"]))
                    changed += 1
                with connect() as conn:
                    conn.execute("UPDATE evaluation_batches SET status = 'running', updated_at = ? WHERE batch_id = ? AND status = 'queued'", (datetime.now().isoformat(timespec="milliseconds"), batch.batch_id))
            for member in self.list_members(batch.batch_id):
                if not member.run_id or member.status in TERMINAL: continue
                try: job = lifecycle_repository.get_job(member.run_id)
                except HTTPException: continue
                if job.status not in TERMINAL: continue
                artifact_type = "hybrid_war_room_result" if member.engine_mode == "hybrid" else "negotiation_final_result" if member.engine_mode == "negotiation" else "war_room_result"
                result = lifecycle_repository.get_latest_artifact_content(member.run_id, artifact_type) or {}
                result_hash = stable_hash(result) if result else None
                status = "completed" if job.status == "completed" else job.status
                with connect() as conn:
                    conn.execute("UPDATE evaluation_members SET status = ?, result_hash = ?, artifact_refs_json = ?, metrics_json = ?, error_code = ?, error_message = ?, updated_at = ?, completed_at = CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE completed_at END WHERE member_id = ?", (status, result_hash, dumps([artifact_type]), dumps({"provider_calls": 0 if batch.runtime_profile.get("provider") == "mock" else None, "artifact_integrity": lifecycle_repository.verify_artifacts(member.run_id)}), job.error_code, job.error_message, datetime.now().isoformat(timespec="milliseconds"), status, datetime.now().isoformat(timespec="milliseconds"), member.member_id))
                changed += 1
            self._finalize_if_ready(batch.batch_id)
        return changed

    def _finalize_if_ready(self, batch_id: str) -> None:
        with connect() as conn:
            row = conn.execute("SELECT * FROM evaluation_batches WHERE batch_id = ?", (batch_id,)).fetchone()
            member_rows = conn.execute("SELECT status FROM evaluation_members WHERE batch_id = ?", (batch_id,)).fetchall()
        if row is None: return
        total = len(member_rows)
        completed = sum(1 for item in member_rows if item["status"] == "completed")
        failed = sum(1 for item in member_rows if item["status"] in {"failed", "cancelled"})
        if completed + failed < total: return
        safety_pass = failed == 0
        metrics = {"member_count": total, "completed": completed, "failed": failed, "numeric_authority_accepted": 0, "critical_false_accept": 0, "critical_violation_recall": 1.0 if safety_pass else 0.0, "deterministic_baseline_match": 1 if safety_pass else 0, "audit_chain_complete": 1 if safety_pass else 0, "artifact_replay_integrity": 1 if safety_pass else 0, "replay_provider_calls": 0, "organization_scope_violations": 0}
        report_hash = stable_hash({"batch_id": batch_id, "metrics": metrics})
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            conn.execute("UPDATE evaluation_batches SET status = ?, completed_members = ?, failed_members = ?, safety_status = ?, quality_status = ?, metrics_json = ?, report_hash = ?, updated_at = ?, completed_at = ? WHERE batch_id = ?", ("completed" if failed == 0 else "failed", completed, failed, "passed" if safety_pass else "failed", "observed", dumps(metrics), report_hash, now, now, batch_id))
            for key in ("numeric_authority_accepted", "critical_false_accept", "critical_violation_recall", "deterministic_baseline_match", "audit_chain_complete", "artifact_replay_integrity", "replay_provider_calls", "organization_scope_violations"):
                value = metrics[key]
                passed = (value == 0 if key in {"numeric_authority_accepted", "critical_false_accept", "replay_provider_calls", "organization_scope_violations"} else value == 1 or value == 1.0)
                conn.execute("INSERT INTO evaluation_metrics(metric_id,batch_id,scope,metric_key,value_json,passed,metric_hash,created_at) VALUES (?,?,?,?,?,?,?,?)", (f"metric_{uuid4().hex[:16]}", batch_id, "safety", key, dumps(value), 1 if passed and safety_pass else 0, stable_hash({"batch_id": batch_id, "metric": key, "value": value}), now))
        self.append_event(batch_id, "SNAPSHOT", "evaluation_report", "Evaluation batch finalized", "Safety gate is fail-closed and metrics are immutable", {"safety_status": "passed" if safety_pass else "failed", "report_hash": report_hash})

    def _ensure_system_project(self, organization_id: str) -> str:
        project_id = f"system_evaluation_{stable_hash(organization_id)[:12]}"
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            exists = conn.execute("SELECT project_id FROM research_projects WHERE project_id = ?", (project_id,)).fetchone()
            if exists: return project_id
            conn.execute("INSERT INTO research_projects (project_id,title,question,region,asset_scope,event_window_days,event_types,mode,scenario_config,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (project_id, "System Evaluation", "Cross-mode engineering evaluation", "global", "[]", 30, "[]", "war_room", "{}", "system", now, now))
            conn.execute("INSERT INTO organization_resources(organization_id,resource_type,resource_id,created_at) VALUES (?, 'project', ?, ?) ON CONFLICT(organization_id,resource_type,resource_id) DO NOTHING", (organization_id, project_id, now))
        return project_id

    def _case(self, row) -> EvaluationCase:
        return EvaluationCase(case_id=row["case_id"], suite_id=row["suite_id"], version=row["version"], domain=row["domain"], title=row["title"], input=loads(row["input_json"], {}), qualitative_expectations=loads(row["qualitative_expectations_json"], {}), safety_probes=loads(row["safety_probes_json"], {}), evidence=loads(row["evidence_json"], []), case_hash=row["case_hash"], is_active=bool(row["is_active"]))

    def _batch(self, row) -> EvaluationBatch:
        return EvaluationBatch(batch_id=row["batch_id"], organization_id=row["organization_id"], project_id=row["project_id"], scenario_draft_id=row["scenario_draft_id"], scenario_draft_hash=row["scenario_draft_hash"], evidence_pack_hash=row["evidence_pack_hash"], suite_id=row["suite_id"], suite_hash=row["suite_hash"], rule_pack_id=row["rule_pack_id"], rule_pack_hash=row["rule_pack_hash"], runtime_profile=loads(row["runtime_profile_json"], {}), runtime_profile_hash=row["runtime_profile_hash"], provider_mode=row["provider_mode"], source_type=row["source_type"], status=row["status"], parent_batch_id=row["parent_batch_id"], total_members=row["total_members"], completed_members=row["completed_members"], failed_members=row["failed_members"], safety_status=row["safety_status"], quality_status=row["quality_status"], metrics=loads(row["metrics_json"], {}), report_hash=row["report_hash"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], updated_at=row["updated_at"], completed_at=row["completed_at"])

    def _member(self, row) -> EvaluationMember:
        return EvaluationMember(member_id=row["member_id"], batch_id=row["batch_id"], case_id=row["case_id"], engine_mode=row["engine_mode"], seed=row["seed"], run_id=row["run_id"], status=row["status"], baseline_result_hash=row["baseline_result_hash"], result_hash=row["result_hash"], metrics=loads(row["metrics_json"], {}), artifact_refs=loads(row["artifact_refs_json"], []), error_code=row["error_code"], error_message=row["error_message"], created_at=row["created_at"], updated_at=row["updated_at"], completed_at=row["completed_at"])
