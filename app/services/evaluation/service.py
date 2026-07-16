from __future__ import annotations

from datetime import datetime, timedelta
import os
from uuid import uuid4
from fastapi import HTTPException

from app.core.evaluation_models import EvaluationBatchCreateRequest, EvaluationBatch, EvaluationCase, EvaluationMember, EvaluationMetric, EvaluationReport, EvaluationRuntimeProfile, EvaluationSuiteManifest, HistoricalBenchmarkReport, HistoricalEvaluationCreateRequest
from app.core.models import RunJobCreateRequest, WarRoomScenarioRequest
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads
from app.db.postgres import is_postgres_url
from app.services.rule_packs import active_rule_pack
from app.services.run_lifecycle import repository as lifecycle_repository
from app.services.war_room.data import SUPPLY_CHAINS
from .corpus import suite_manifest
from .gates import ensure_gate_manifest, list_verification_results, verify_member
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
        return [self._case(row) for row in rows]

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
        return self._batch(row)

    def list_batches(self, organization_id: str) -> list[EvaluationBatch]:
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_batches WHERE organization_id = ? ORDER BY created_at DESC", (organization_id,)).fetchall()
        return [self._batch(row) for row in rows]

    def list_members(self, batch_id: str, organization_id: str | None = None) -> list[EvaluationMember]:
        self.get_batch(batch_id, organization_id)
        with connect() as conn: rows = conn.execute("SELECT * FROM evaluation_members WHERE batch_id = ? ORDER BY created_at, member_id", (batch_id,)).fetchall()
        return [self._member(row) for row in rows]

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

    def reconcile(self, *, worker_id: str | None = None) -> int:
        """Schedule pending members and harvest terminal real v2 child runs."""
        changed = 0
        worker_id = worker_id or f"evaluation_{uuid4().hex[:12]}"
        now = datetime.now().isoformat(timespec="milliseconds")
        lease = (datetime.now() + timedelta(seconds=60)).isoformat(timespec="milliseconds")
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            lock_clause = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
            batch_row = conn.execute(
                f"""SELECT * FROM evaluation_batches
                    WHERE status IN ('queued','running','pausing','cancelling')
                      AND (coordinator_lease_expires_at IS NULL OR coordinator_lease_expires_at < ? OR coordinator_worker_id = ?)
                    ORDER BY created_at LIMIT 1{lock_clause}""",
                (now, worker_id),
            ).fetchone()
            if batch_row is not None:
                conn.execute(
                    """UPDATE evaluation_batches
                       SET coordinator_worker_id=?, coordinator_lease_expires_at=?,
                           coordinator_attempt_count=coordinator_attempt_count+1
                       WHERE batch_id=?""",
                    (worker_id, lease, batch_row["batch_id"]),
                )
        batches = [batch_row] if batch_row is not None else []
        for batch_row in batches:
            batch = self._batch(batch_row)
            if batch.status in {"queued", "running"}:
                project_id = self._ensure_system_project(batch.organization_id)
                with connect() as conn:
                    inflight = int(conn.execute("SELECT COUNT(*) FROM evaluation_members WHERE batch_id = ? AND status IN ('queued','running')", (batch.batch_id,)).fetchone()[0])
                    capacity = max(1, min(8, int(os.getenv("WORLDPULSE_EVALUATION_MAX_IN_FLIGHT", "2")))) - inflight
                    pending = conn.execute("SELECT m.*, c.input_json FROM evaluation_members m JOIN evaluation_cases c ON c.case_id = m.case_id WHERE m.batch_id = ? AND m.status = 'pending' ORDER BY m.created_at LIMIT ?", (batch.batch_id, min(1, max(0, capacity)))).fetchall()
                for member in pending:
                    scenario = WarRoomScenarioRequest(**{**loads(member["input_json"], {}), "seed": int(member["seed"])})
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
                if job.status not in TERMINAL:
                    mapped = "paused" if job.status in {"paused", "pausing"} else "running" if job.status in {"preparing", "running", "cancelling"} else "queued"
                    if mapped != member.status:
                        with connect() as conn:
                            conn.execute("UPDATE evaluation_members SET status = ?, updated_at = ? WHERE member_id = ?", (mapped, datetime.now().isoformat(timespec="milliseconds"), member.member_id))
                        changed += 1
                    continue
                artifact_type = "hybrid_war_room_result" if member.engine_mode == "hybrid" else "negotiation_final_result" if member.engine_mode == "negotiation" else "war_room_result"
                result = lifecycle_repository.get_latest_artifact_content(member.run_id, artifact_type) or {}
                result_hash = stable_hash(result) if result else None
                status = "completed" if job.status == "completed" else job.status
                with connect() as conn:
                    conn.execute("UPDATE evaluation_members SET status = ?, result_hash = ?, artifact_refs_json = ?, metrics_json = ?, error_code = ?, error_message = ?, updated_at = ?, completed_at = CASE WHEN ? IN ('completed','failed','cancelled') THEN ? ELSE completed_at END WHERE member_id = ?", (status, result_hash, dumps([artifact_type]), dumps({"provider_calls": 0 if batch.runtime_profile.get("provider") == "mock" else None, "artifact_integrity": lifecycle_repository.verify_artifacts(member.run_id)}), job.error_code, job.error_message, datetime.now().isoformat(timespec="milliseconds"), status, datetime.now().isoformat(timespec="milliseconds"), member.member_id))
                changed += 1
            current = self.get_batch(batch.batch_id)
            members = self.list_members(batch.batch_id)
            completed_now = sum(item.status == "completed" for item in members)
            failed_now = sum(item.status in {"failed", "cancelled"} for item in members)
            with connect() as conn:
                conn.execute(
                    "UPDATE evaluation_batches SET completed_members=?, failed_members=?, updated_at=? WHERE batch_id=?",
                    (completed_now, failed_now, datetime.now().isoformat(timespec="milliseconds"), batch.batch_id),
                )
            if current.status == "pausing" and all(item.status in {"pending", "paused", *TERMINAL} for item in members):
                with connect() as conn:
                    conn.execute("UPDATE evaluation_batches SET status = 'paused', updated_at = ? WHERE batch_id = ?", (datetime.now().isoformat(timespec="milliseconds"), batch.batch_id))
            elif current.status == "cancelling" and all(item.status in TERMINAL for item in members):
                now = datetime.now().isoformat(timespec="milliseconds")
                with connect() as conn:
                    conn.execute("UPDATE evaluation_batches SET status = 'cancelled', failed_members = ?, updated_at = ?, completed_at = ? WHERE batch_id = ?", (len(members), now, now, batch.batch_id))
                    conn.execute("UPDATE evaluation_batches SET coordinator_worker_id=NULL, coordinator_lease_expires_at=NULL WHERE batch_id=? AND coordinator_worker_id=?", (batch.batch_id, worker_id))
                continue
            self._finalize_if_ready(batch.batch_id)
            with connect() as conn:
                conn.execute(
                    "UPDATE evaluation_batches SET coordinator_worker_id=NULL, coordinator_lease_expires_at=NULL WHERE batch_id=? AND coordinator_worker_id=?",
                    (batch.batch_id, worker_id),
                )
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
        batch = self._batch(row)
        members = self.list_members(batch_id)
        deterministic = {item.case_id: item.result_hash for item in members if item.engine_mode == "deterministic" and item.status == "completed"}
        for member in members:
            if member.status == "completed":
                verify_member(batch, member, expected_baseline_hash=deterministic.get(member.case_id))
        verification = list_verification_results(batch_id)
        by_key: dict[str, list] = {}
        for item in verification:
            by_key.setdefault(item.check_key, []).append(item)
        safety_pass = failed == 0 and len(verification) == completed * 10 and all(item.status in {"passed", "not_applicable"} for item in verification)
        critical_items = by_key.get("critical_violation_recall", [])
        critical_total = sum(int(item.observed.get("critical", 0)) for item in critical_items)
        critical_caught = sum(int(item.observed.get("caught", 0)) for item in critical_items)
        metrics = {
            "member_count": total,
            "completed": completed,
            "failed": failed,
            "numeric_authority_accepted": sum(int(item.observed.get("accepted", 0)) for item in by_key.get("numeric_authority_accepted", [])),
            "critical_false_accept": sum(int(item.observed.get("false_accepts", 0)) for item in by_key.get("critical_false_accept", [])),
            "critical_violation_recall": 1.0 if critical_total == 0 else critical_caught / critical_total,
            "illegal_projection": sum(int(item.observed.get("illegal_projections", 0)) for item in by_key.get("illegal_projection", [])),
            "deterministic_baseline_match": int(all(item.status != "failed" for item in by_key.get("baseline_hash_match", []))),
            "audit_chain_complete": int(all(item.status != "failed" for item in by_key.get("runtime_lineage", []))),
            "artifact_replay_integrity": int(all(item.status != "failed" for key in ("artifact_lineage_integrity", "offline_replay") for item in by_key.get(key, []))),
            "replay_provider_calls": sum(int(item.observed.get("provider_calls", 0)) for item in by_key.get("offline_replay", [])),
            "organization_scope_violations": sum(int(item.observed.get("violations", 0)) for item in by_key.get("organization_scope", [])),
            "verification_result_count": len(verification),
        }
        if batch.evaluation_track == "historical_blind":
            try:
                historical_metrics = self._historical_observation_metrics(batch, members)
                metrics["historical_observation"] = historical_metrics
            except Exception as exc:
                safety_pass = False
                metrics["historical_observation"] = {"status": "failed", "error": type(exc).__name__, "blind_labels_redacted": True}
                from app.services.reviews import create_review_case
                create_review_case("historical_label_integrity", "evaluation_batch", batch_id, "Historical label comparison failed closed", severity="critical", payload={"error": type(exc).__name__})
        report_hash = stable_hash({"batch_id": batch_id, "metrics": metrics})
        now = datetime.now().isoformat(timespec="milliseconds")
        with connect() as conn:
            conn.execute("UPDATE evaluation_batches SET status = ?, completed_members = ?, failed_members = ?, safety_status = ?, quality_status = ?, metrics_json = ?, report_hash = ?, updated_at = ?, completed_at = ? WHERE batch_id = ?", ("completed" if failed == 0 else "failed", completed, failed, "passed" if safety_pass else "failed", "observed", dumps(metrics), report_hash, now, now, batch_id))
            for key in ("numeric_authority_accepted", "critical_false_accept", "critical_violation_recall", "illegal_projection", "deterministic_baseline_match", "audit_chain_complete", "artifact_replay_integrity", "replay_provider_calls", "organization_scope_violations"):
                value = metrics[key]
                passed = (value == 0 if key in {"numeric_authority_accepted", "critical_false_accept", "illegal_projection", "replay_provider_calls", "organization_scope_violations"} else value == 1 or value == 1.0)
                conn.execute("INSERT INTO evaluation_metrics(metric_id,batch_id,scope,metric_key,value_json,passed,metric_hash,created_at) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(metric_hash) DO NOTHING", (f"metric_{uuid4().hex[:16]}", batch_id, "safety", key, dumps(value), 1 if passed and safety_pass else 0, stable_hash({"batch_id": batch_id, "metric": key, "value": value}), now))
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
        for member in members:
            if member.engine_mode != "deterministic" or not member.case_id.startswith("hist_") or member.case_id.startswith("hist_blind_"):
                continue
            historical_id = member.case_id.removeprefix("hist_")
            case = cases.get(historical_id)
            if case is None or not member.run_id:
                raise ValueError("Historical case lineage is invalid")
            labels = case.labels if case.split == "development" else blind_labels.get(historical_id)
            if not isinstance(labels, dict):
                raise ValueError("Historical labels are incomplete")
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
        return EvaluationCase(case_id=row["case_id"], suite_id=row["suite_id"], version=row["version"], domain=row["domain"], title=row["title"], input=loads(row["input_json"], {}), qualitative_expectations=loads(row["qualitative_expectations_json"], {}), safety_probes=loads(row["safety_probes_json"], {}), evidence=loads(row["evidence_json"], []), case_hash=row["case_hash"], is_active=bool(row["is_active"]))

    def _batch(self, row) -> EvaluationBatch:
        return EvaluationBatch(batch_id=row["batch_id"], organization_id=row["organization_id"], project_id=row["project_id"], scenario_draft_id=row["scenario_draft_id"], scenario_draft_hash=row["scenario_draft_hash"], evidence_pack_hash=row["evidence_pack_hash"], suite_id=row["suite_id"], suite_hash=row["suite_hash"], rule_pack_id=row["rule_pack_id"], rule_pack_hash=row["rule_pack_hash"], runtime_profile=loads(row["runtime_profile_json"], {}), runtime_profile_hash=row["runtime_profile_hash"], provider_mode=row["provider_mode"], source_type=row["source_type"], status=row["status"], parent_batch_id=row["parent_batch_id"], total_members=row["total_members"], completed_members=row["completed_members"], failed_members=row["failed_members"], safety_status=row["safety_status"], quality_status=row["quality_status"], metrics=loads(row["metrics_json"], {}), report_hash=row["report_hash"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], updated_at=row["updated_at"], completed_at=row["completed_at"], evaluation_track=row["evaluation_track"], benchmark_suite_id=row["benchmark_suite_id"], benchmark_suite_hash=row["benchmark_suite_hash"], label_pack_id=row["label_pack_id"], label_pack_hash=row["label_pack_hash"], gate_manifest_hash=row["gate_manifest_hash"], root_batch_id=row["root_batch_id"], coordinator_worker_id=row["coordinator_worker_id"], coordinator_lease_expires_at=row["coordinator_lease_expires_at"])

    def _member(self, row) -> EvaluationMember:
        return EvaluationMember(member_id=row["member_id"], batch_id=row["batch_id"], case_id=row["case_id"], engine_mode=row["engine_mode"], seed=row["seed"], run_id=row["run_id"], status=row["status"], baseline_result_hash=row["baseline_result_hash"], result_hash=row["result_hash"], metrics=loads(row["metrics_json"], {}), artifact_refs=loads(row["artifact_refs_json"], []), error_code=row["error_code"], error_message=row["error_message"], created_at=row["created_at"], updated_at=row["updated_at"], completed_at=row["completed_at"], input_hash=row["input_hash"], expected_baseline_hash=row["expected_baseline_hash"], verification_status=row["verification_status"], verification_hash=row["verification_hash"])


def _historical_case_metrics(result: dict, expected: dict, label_confidence: float, evidence_count: int) -> dict:
    countries = sorted(result.get("country_agents", []), key=lambda item: float(item.get("risk_score", 0)), reverse=True)
    ranking = [item.get("code") for item in countries if item.get("code")]
    expected_ranking = list(expected.get("risk_ranking", []))
    expected_top3 = list(expected.get("top3_countries", []))
    baseline_pressure = {item.key: float(item.pressure_score) for item in SUPPLY_CHAINS}
    chain_actual = {}
    for item in result.get("supply_chains", []):
        key = item.get("key")
        if not key:
            continue
        direction = item.get("direction")
        if direction not in {"up", "down", "flat"}:
            pressure = item.get("pressure_score")
            if pressure is None or key not in baseline_pressure:
                direction = None
            else:
                delta = float(pressure) - baseline_pressure[key]
                direction = "up" if delta >= 2.0 else "down" if delta <= -2.0 else "flat"
        chain_actual[key] = direction
    chain_expected = expected.get("supply_chain_directions", {})
    actual_turns = [int(item.get("day", 0)) for item in result.get("timeline", []) if item.get("turning_point")]
    expected_turns = [int(item) for item in expected.get("turning_points", [])]
    ranked_country_coverage = len(set(expected_ranking) & set(ranking)) / 10
    chain_coverage = len(set(chain_expected) & set(chain_actual)) / 5
    return {
        "risk_spearman": _spearman(ranking, expected_ranking),
        "top3_overlap": len(set(ranking[:3]) & set(expected_top3)) / 3 if expected_top3 else 1.0,
        "supply_chain_direction_accuracy": _mapping_accuracy(chain_actual, chain_expected),
        "turning_point_error_days": _turning_error(actual_turns, expected_turns),
        "agent_outcome_agreement": None,
        "data_coverage": round(min(1.0, 0.7 * ranked_country_coverage + 0.3 * chain_coverage) if evidence_count >= 2 else 0.0, 6),
        "label_confidence": float(label_confidence),
    }


def _average(rows: list[dict], key: str) -> float:
    return round(sum(float(item[key]) for item in rows) / max(1, len(rows)), 6)


def _average_optional(rows: list[dict], key: str) -> float | None:
    values = [float(item[key]) for item in rows if item.get(key) is not None]
    return round(sum(values) / len(values), 6) if values else None


def _mapping_accuracy(actual: dict, expected: dict) -> float:
    keys = set(expected)
    return sum(actual.get(key) == expected.get(key) for key in keys) / len(keys) if keys else 0.0


def _spearman(actual: list[str], expected: list[str]) -> float:
    common = [item for item in expected if item in actual]
    if len(common) < 2:
        return 0.0
    actual_rank = {item: actual.index(item) for item in common}
    expected_rank = {item: expected.index(item) for item in common}
    n = len(common)
    d2 = sum((actual_rank[item] - expected_rank[item]) ** 2 for item in common)
    return max(-1.0, min(1.0, 1 - (6 * d2) / (n * (n * n - 1))))


def _turning_error(actual: list[int], expected: list[int]) -> float:
    if not expected:
        return 0.0 if not actual else float(max(actual))
    if not actual:
        return float(max(expected))
    return sum(abs(value - actual[min(index, len(actual) - 1)]) for index, value in enumerate(expected)) / len(expected)
