from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.evidence_models import EvidenceClaimCreate, EvidencePackCreate, EvidenceSnapshotCreate, EvidenceSourceCreate
from app.core.models import RunJobCreateRequest, RunJobStatus, WarRoomScenarioRequest
from app.core.scenario_compiler_models import (
    DocumentExtraction, DocumentExtractionEvent, DocumentExtractionJob, DocumentUploadResult,
    ScenarioCandidate, ScenarioCandidateDecision, ScenarioCandidateDecisionRequest,
    ScenarioDraft, ScenarioDraftCreateRequest, ScenarioDraftReview, ScenarioDraftReviewRequest,
    ScenarioDraftRunRequest, SourceDocument,
)
from app.core.trust_models import UserIdentity
from app.db.postgres import is_postgres_url
from app.services import evidence_registry
from app.services.consistency.hashing import stable_hash
from app.services.organizations import ORG_WRITE_ROLES, require_organization_role, require_resource_scope, scope_resource
from app.services.project_store import connect, dumps, init_db, loads
from app.services.reviews import create_review_case
from app.services.run_lifecycle import repository as lifecycle_repository
from app.services.security import redact_secrets
from app.services.war_room.data import POLICY_ACTIONS, SCENARIOS, SUPPLY_CHAINS, COUNTRIES

from .blob_store import resolve_blob, store_upload, verify_blob
from .extraction import EXTRACTOR_VERSION, deterministic_candidates, extract_chunks, optional_llm_candidates


READ_ROLES = {"owner", "admin", "analyst", "reviewer", "viewer"}
REVIEW_ROLES = {"owner", "admin", "reviewer"}
COMPILER_VERSION = "scenario-compiler.v1"


class ScenarioCompilerService:
    async def upload_document(
        self, organization_id: str, project_id: str, upload: UploadFile, actor: UserIdentity, *,
        title: str, category: str, publisher: str, license_name: str, license_url: str,
        observed_at: str, cutoff_at: str,
    ) -> DocumentUploadResult:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        require_resource_scope(organization_id, "project", project_id)
        for label, value in (("title", title), ("category", category), ("publisher", publisher), ("license", license_name)):
            if not str(value).strip():
                raise HTTPException(status_code=422, detail=f"Document {label} is required")
        observed, cutoff = _parse_time(observed_at), _parse_time(cutoff_at)
        if observed > cutoff or cutoff > datetime.now(timezone.utc):
            raise HTTPException(status_code=422, detail="Document requires observed_at <= cutoff_at <= current time")
        content_hash, size, blob_key, media_type, _created = await store_upload(upload)
        init_db()
        with connect() as conn:
            existing = conn.execute(
                "SELECT * FROM source_documents WHERE organization_id = ? AND project_id = ? AND content_hash = ?",
                (organization_id, project_id, content_hash),
            ).fetchone()
        if existing:
            return DocumentUploadResult(document=_document(existing), deduplicated=True)

        from app.services.operations import enforce_quota
        document_id = f"doc_{uuid4().hex[:20]}"
        now = _now()
        try:
            with connect() as conn:
                if not is_postgres_url():
                    conn.execute("BEGIN IMMEDIATE")
                enforce_quota(organization_id, "source_document", connection=conn)
                enforce_quota(organization_id, "document_bytes", requested=size, connection=conn)
                conn.execute(
                    """
                    INSERT INTO source_documents
                    (document_id, organization_id, project_id, original_filename, media_type, size_bytes,
                     content_hash, blob_key, title, category, publisher, license_name, license_url,
                     observed_at, cutoff_at, status, created_by_user_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploaded', ?, ?)
                    """,
                    (document_id, organization_id, project_id, upload.filename or "document", media_type, size,
                     content_hash, blob_key, title.strip(), category.strip(), publisher.strip(), license_name.strip(),
                     license_url.strip(), _iso(observed), _iso(cutoff), actor.user_id, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                with connect() as conn:
                    row = conn.execute(
                        "SELECT * FROM source_documents WHERE organization_id = ? AND project_id = ? AND content_hash = ?",
                        (organization_id, project_id, content_hash),
                    ).fetchone()
                if row:
                    return DocumentUploadResult(document=_document(row), deduplicated=True)
            raise
        scope_resource(organization_id, "source_document", document_id)
        return DocumentUploadResult(document=self.get_document(organization_id, project_id, document_id, actor))

    def list_documents(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[SourceDocument]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM source_documents WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, document_id DESC",
                (organization_id, project_id),
            ).fetchall()
        return [_document(row) for row in rows]

    def get_document(self, organization_id: str, project_id: str, document_id: str, actor: UserIdentity) -> SourceDocument:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM source_documents WHERE organization_id = ? AND project_id = ? AND document_id = ?",
                (organization_id, project_id, document_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown source document: {document_id}")
        return _document(row)

    def document_download(self, organization_id: str, project_id: str, document_id: str, actor: UserIdentity) -> tuple[Path, SourceDocument]:
        document = self.get_document(organization_id, project_id, document_id, actor)
        with connect() as conn:
            row = conn.execute("SELECT blob_key FROM source_documents WHERE document_id = ?", (document_id,)).fetchone()
        path = resolve_blob(row["blob_key"])
        check = verify_blob(row["blob_key"], document.content_hash, document.size_bytes)
        if check["status"] != "verified":
            create_review_case("document_integrity", "source_document", document_id, "Source document blob integrity verification failed", severity="critical", payload=check)
            raise HTTPException(status_code=409, detail="Source document integrity verification failed")
        return path, document

    def create_extraction_job(self, organization_id: str, project_id: str, document_id: str, actor: UserIdentity) -> DocumentExtractionJob:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        document = self.get_document(organization_id, project_id, document_id, actor)
        provider = _provider_name()
        request_hash = stable_hash({"document_hash": document.content_hash, "extractor_version": EXTRACTOR_VERSION, "provider": provider})
        with connect() as conn:
            existing = conn.execute("SELECT * FROM document_extraction_jobs WHERE document_id = ? AND request_hash = ?", (document_id, request_hash)).fetchone()
        if existing:
            return _job(existing)
        job_id = f"dex_{uuid4().hex[:20]}"
        now = _now()
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO document_extraction_jobs
                (job_id, organization_id, project_id, document_id, status, request_hash, extractor_version,
                 provider, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)
                """,
                (job_id, organization_id, project_id, document_id, request_hash, EXTRACTOR_VERSION, provider, actor.user_id, now, now),
            )
        self.append_extraction_event(job_id, "WORKER", "Document extraction queued", "材料已固定内容 Hash，等待 ingestion worker 抽取。", {"document_id": document_id})
        return self.get_extraction_job(organization_id, project_id, job_id, actor)

    def get_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity) -> DocumentExtractionJob:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute("SELECT * FROM document_extraction_jobs WHERE organization_id = ? AND project_id = ? AND job_id = ?", (organization_id, project_id, job_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown document extraction job: {job_id}")
        return _job(row)

    def list_extraction_jobs(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[DocumentExtractionJob]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM document_extraction_jobs WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, job_id DESC",
                (organization_id, project_id),
            ).fetchall()
        return [_job(row) for row in rows]

    def list_extraction_events(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity, after_seq: int = 0) -> list[DocumentExtractionEvent]:
        self.get_extraction_job(organization_id, project_id, job_id, actor)
        with connect() as conn:
            rows = conn.execute("SELECT * FROM document_extraction_events WHERE job_id = ? AND seq > ? ORDER BY seq", (job_id, max(0, after_seq))).fetchall()
        return [_event(row) for row in rows]

    def cancel_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity) -> DocumentExtractionJob:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        job = self.get_extraction_job(organization_id, project_id, job_id, actor)
        if job.status not in {"queued", "running"}:
            raise HTTPException(status_code=409, detail=f"Cannot cancel extraction job from {job.status}")
        next_status = "cancelled" if job.status == "queued" else "cancelling"
        with connect() as conn:
            conn.execute(
                "UPDATE document_extraction_jobs SET status = ?, cancel_requested_at = ?, completed_at = CASE WHEN ? = 'cancelled' THEN ? ELSE completed_at END, updated_at = ? WHERE job_id = ?",
                (next_status, _now(), next_status, _now(), _now(), job_id),
            )
        self.append_extraction_event(job_id, "WORKER", "Extraction cancellation requested", "取消将在材料抽取阶段边界生效。", {"status": next_status})
        return self.get_extraction_job(organization_id, project_id, job_id, actor)

    def retry_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity) -> DocumentExtractionJob:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        previous = self.get_extraction_job(organization_id, project_id, job_id, actor)
        if previous.status not in {"failed", "cancelled"}:
            raise HTTPException(status_code=409, detail="Only failed or cancelled extraction jobs can be retried")
        request_hash = stable_hash({"parent": previous.request_hash, "retry": previous.attempt_count + 1, "provider": _provider_name()})
        new_id = f"dex_{uuid4().hex[:20]}"; now = _now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO document_extraction_jobs
                (job_id, organization_id, project_id, document_id, parent_job_id, status, request_hash,
                 extractor_version, provider, created_by_user_id, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)""",
                (new_id, organization_id, project_id, previous.document_id, job_id, request_hash,
                 EXTRACTOR_VERSION, _provider_name(), actor.user_id, now, now),
            )
        self.append_extraction_event(new_id, "WORKER", "Extraction retry queued", "重试保留父任务关系，不覆盖原失败记录。", {"parent_job_id": job_id})
        return self.get_extraction_job(organization_id, project_id, new_id, actor)

    def claim_next_extraction_job(self, worker_id: str) -> tuple[str, str, str] | None:
        init_db()
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            lock = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
            row = conn.execute(f"SELECT job_id, organization_id, project_id FROM document_extraction_jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1{lock}").fetchone()
            if row is None:
                return None
            updated = conn.execute(
                "UPDATE document_extraction_jobs SET status = 'running', worker_id = ?, attempt_count = attempt_count + 1, started_at = COALESCE(started_at, ?), updated_at = ? WHERE job_id = ? AND status = 'queued'",
                (worker_id, _now(), _now(), row["job_id"]),
            )
        return (row["organization_id"], row["project_id"], row["job_id"]) if updated.rowcount == 1 else None

    def execute_claimed_extraction(self, organization_id: str, project_id: str, job_id: str, worker_id: str) -> DocumentExtractionJob:
        with connect() as conn:
            row = conn.execute(
                """SELECT u.user_id, u.username, u.display_name, u.role, u.is_active
                FROM document_extraction_jobs j JOIN users u ON u.user_id = j.created_by_user_id
                WHERE j.job_id = ? AND j.organization_id = ? AND j.project_id = ?""",
                (job_id, organization_id, project_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=409, detail="Extraction job has no valid creator identity")
        actor = UserIdentity(user_id=row["user_id"], username=row["username"], display_name=row["display_name"], role=row["role"], is_active=bool(row["is_active"]))
        return self.execute_extraction(organization_id, project_id, job_id, actor, worker_id=worker_id)

    def execute_extraction(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity, *, worker_id: str = "api-bounded-executor") -> DocumentExtractionJob:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        job = self.get_extraction_job(organization_id, project_id, job_id, actor)
        if job.status == "completed":
            return job
        if job.status == "queued":
            with connect() as conn:
                changed = conn.execute(
                    "UPDATE document_extraction_jobs SET status = 'running', worker_id = ?, attempt_count = attempt_count + 1, started_at = COALESCE(started_at, ?), updated_at = ? WHERE job_id = ? AND status = 'queued'",
                    (worker_id, _now(), _now(), job_id),
                )
            if changed.rowcount != 1:
                raise HTTPException(status_code=409, detail="Extraction job was claimed concurrently")
        elif job.status != "running":
            raise HTTPException(status_code=409, detail=f"Extraction job cannot execute from {job.status}")
        self.append_extraction_event(job_id, "WORKER", "Document extraction started", "开始执行版本化文本抽取，材料内容始终按不可信输入处理。", {"worker_id": worker_id})
        try:
            document = self.get_document(organization_id, project_id, job.document_id, actor)
            with connect() as conn:
                row = conn.execute("SELECT blob_key FROM source_documents WHERE document_id = ?", (document.document_id,)).fetchone()
                conn.execute("UPDATE source_documents SET status = 'extracting' WHERE document_id = ?", (document.document_id,))
            blob_check = verify_blob(row["blob_key"], document.content_hash, document.size_bytes)
            if blob_check["status"] != "verified":
                raise HTTPException(status_code=409, detail="Document blob integrity verification failed")
            chunks = extract_chunks(resolve_blob(row["blob_key"]), document.media_type)
            self._cancel_boundary(job_id)
            from app.services.operations import enforce_quota
            enforce_quota(organization_id, "evidence_snapshot", requested=len(chunks))
            source = evidence_registry.create_source(EvidenceSourceCreate(
                source_type="uploaded_document", name=document.title,
                locator=f"worldpulse://organizations/{organization_id}/projects/{project_id}/documents/{document.document_id}",
                publisher=document.publisher, trust_tier="external_governed",
                metadata={"document_id": document.document_id, "content_hash": document.content_hash, "license": document.license_name, "license_url": document.license_url},
            ), actor, organization_id=organization_id)
            scope_resource(organization_id, "evidence_source", source.source_id)
            snapshots = []
            chunk_manifest = []
            for index, chunk in enumerate(chunks, start=1):
                snapshot = evidence_registry.create_snapshot(EvidenceSnapshotCreate(
                    source_id=source.source_id, project_id=project_id, external_ref=f"{document.document_id}:chunk:{index:04d}",
                    title=f"{document.title} · {index}", category=document.category,
                    content={"document_id": document.document_id, "content_hash": document.content_hash, "locator": chunk["locator"], "extractor_version": EXTRACTOR_VERSION},
                    content_text=chunk["text"], observed_at=document.observed_at, cutoff_at=document.cutoff_at,
                ), actor, organization_id=organization_id, quota_reserved=True)
                snapshots.append(snapshot)
                scope_resource(organization_id, "evidence_snapshot", snapshot.snapshot_id)
                chunk_manifest.append({"position": index, "snapshot_id": snapshot.snapshot_id, "content_hash": snapshot.content_hash, "locator": chunk["locator"], "chars": len(chunk["text"])})
            self._cancel_boundary(job_id)
            snapshot_ids = [item.snapshot_id for item in snapshots]
            candidates = deterministic_candidates(chunks, snapshot_ids)
            llm_candidates, provider_audit, warnings = optional_llm_candidates(chunks, snapshot_ids)
            candidates.extend(llm_candidates)
            extraction_core = {
                "schema_version": "document-extraction.v1", "document_hash": document.content_hash,
                "extractor_version": EXTRACTOR_VERSION, "chunks": chunk_manifest,
                "provider_audit": provider_audit,
            }
            extraction_hash = stable_hash(extraction_core)
            extraction_id = f"ext_{extraction_hash[:20]}"
            now = _now()
            with connect() as conn:
                conn.execute(
                    """INSERT INTO document_extractions
                    (extraction_id, job_id, document_id, extractor_version, chunk_manifest_json, snapshot_ids_json,
                     provider_audit_json, extraction_hash, total_chars, total_chunks, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(job_id) DO NOTHING""",
                    (extraction_id, job_id, document.document_id, EXTRACTOR_VERSION, dumps(chunk_manifest), dumps(snapshot_ids),
                     dumps(provider_audit), extraction_hash, sum(len(item["text"]) for item in chunks), len(chunks), now),
                )
                stored = conn.execute("SELECT extraction_id FROM document_extractions WHERE job_id = ?", (job_id,)).fetchone()
                extraction_id = stored["extraction_id"]
                for candidate in candidates:
                    candidate_id = f"cand_{candidate['candidate_hash'][:20]}"
                    conn.execute(
                        """INSERT INTO scenario_candidates
                        (candidate_id, extraction_id, organization_id, project_id, candidate_type, canonical_value,
                         display_value, relation_json, snapshot_id, locator_json, excerpt, confidence, extractor_source,
                         validation_status, validation_reason, candidate_hash, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(candidate_hash) DO NOTHING""",
                        (candidate_id, extraction_id, organization_id, project_id, candidate["candidate_type"], candidate["canonical_value"],
                         candidate["display_value"], dumps(candidate.get("relation", {})), candidate["snapshot_id"], dumps(candidate["locator"]),
                         candidate["excerpt"], candidate["confidence"], candidate["extractor_source"], candidate["validation_status"],
                         candidate.get("validation_reason"), candidate["candidate_hash"], now),
                    )
                conn.execute(
                    "UPDATE document_extraction_jobs SET status = 'completed', warning_json = ?, completed_at = ?, updated_at = ?, error_code = NULL, error_message = NULL WHERE job_id = ?",
                    (dumps(warnings), now, now, job_id),
                )
                conn.execute("UPDATE source_documents SET status = 'ready' WHERE document_id = ?", (document.document_id,))
            self.append_extraction_event(job_id, "SNAPSHOT", "Document extraction committed", "证据快照、候选与 Extraction Hash 已固化。", {"extraction_hash": extraction_hash, "candidate_count": len(candidates), "warning_count": len(warnings)})
        except _CancelledAtBoundary:
            with connect() as conn:
                conn.execute("UPDATE document_extraction_jobs SET status = 'cancelled', completed_at = ?, updated_at = ? WHERE job_id = ?", (_now(), _now(), job_id))
            self.append_extraction_event(job_id, "WORKER", "Document extraction cancelled", "任务已在抽取阶段边界取消。", {})
        except Exception as exc:
            safe = redact_secrets(str(exc), max_length=1000) or type(exc).__name__
            with connect() as conn:
                conn.execute("UPDATE document_extraction_jobs SET status = 'failed', error_code = ?, error_message = ?, completed_at = ?, updated_at = ? WHERE job_id = ?", (type(exc).__name__, safe, _now(), _now(), job_id))
                conn.execute("UPDATE source_documents SET status = 'failed' WHERE document_id = ?", (job.document_id,))
            self.append_extraction_event(job_id, "CONSISTENCY", "Document extraction failed closed", "材料未通过抽取或完整性门禁，未产生可编译场景。", {"error_code": type(exc).__name__})
            create_review_case("document_extraction_failure", "source_document", job.document_id, "Document extraction failed closed", severity="high", payload={"job_id": job_id, "error_code": type(exc).__name__})
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=422, detail=safe) from exc
        return self.get_extraction_job(organization_id, project_id, job_id, actor)

    def list_candidates(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[ScenarioCandidate]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute("SELECT * FROM scenario_candidates WHERE organization_id = ? AND project_id = ? ORDER BY created_at, candidate_id", (organization_id, project_id)).fetchall()
        return [self._candidate_with_decision(row) for row in rows]

    def decide_candidate(self, organization_id: str, project_id: str, candidate_id: str, payload: ScenarioCandidateDecisionRequest, actor: UserIdentity) -> ScenarioCandidateDecision:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        candidate = self._get_candidate(organization_id, project_id, candidate_id, actor)
        if payload.decision == "accepted" and candidate.validation_status != "valid":
            raise HTTPException(status_code=422, detail="Invalid extraction candidates cannot be accepted")
        normalized = (payload.normalized_value or candidate.canonical_value).strip() if payload.decision == "accepted" else None
        if payload.decision == "accepted":
            _validate_canonical(candidate.candidate_type, normalized)
        now = _now()
        core = {"candidate_hash": candidate.candidate_hash, "decision": payload.decision, "normalized_value": normalized, "comment": payload.comment, "actor": actor.user_id, "created_at": now}
        decision_hash = stable_hash(core); decision_id = f"cdec_{decision_hash[:20]}"
        with connect() as conn:
            conn.execute(
                """INSERT INTO scenario_candidate_decisions
                (decision_id, candidate_id, organization_id, project_id, decision, normalized_value, comment,
                 actor_user_id, decision_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (decision_id, candidate_id, organization_id, project_id, payload.decision, normalized, payload.comment, actor.user_id, decision_hash, now),
            )
        return self._get_decision(decision_id)

    def create_draft(self, organization_id: str, project_id: str, payload: ScenarioDraftCreateRequest, actor: UserIdentity) -> ScenarioDraft:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        require_resource_scope(organization_id, "project", project_id)
        candidates = [self._get_candidate(organization_id, project_id, item, actor) for item in dict.fromkeys(payload.candidate_ids)]
        decisions = []
        for candidate in candidates:
            if not candidate.latest_decision or candidate.latest_decision.decision != "accepted":
                raise HTTPException(status_code=422, detail=f"Candidate is not currently accepted: {candidate.candidate_id}")
            decisions.append(candidate.latest_decision)
        compile_items = [(candidate, decision.normalized_value or candidate.canonical_value) for candidate, decision in zip(candidates, decisions, strict=True) if candidate.candidate_type in {"scenario_preset", "country", "supply_chain", "policy_action"}]
        if not compile_items:
            raise HTTPException(status_code=422, detail="Draft requires accepted compile candidates")
        presets = sorted({value for candidate, value in compile_items if candidate.candidate_type == "scenario_preset"})
        if len(presets) != 1:
            raise HTTPException(status_code=422, detail="Draft requires exactly one accepted scenario preset")
        base = next(item for item in SCENARIOS if item.key == presets[0])
        duration = payload.duration_days if payload.duration_days is not None else base.duration_days
        intensity = payload.intensity if payload.intensity is not None else base.intensity
        propagation = payload.propagation if payload.propagation is not None else base.propagation
        changed = {key: {"default": default, "selected": selected} for key, default, selected in (
            ("duration_days", base.duration_days, duration), ("intensity", base.intensity, intensity), ("propagation", base.propagation, propagation),
        ) if selected != default}
        if changed and not payload.assumption_reason.strip():
            raise HTTPException(status_code=422, detail="Manual numeric assumptions require a reason")
        scenario = {
            "scenario_key": base.key, "duration_days": duration, "intensity": intensity, "propagation": propagation,
            "target_countries": sorted({value for candidate, value in compile_items if candidate.candidate_type == "country"}),
            "target_chains": sorted({value for candidate, value in compile_items if candidate.candidate_type == "supply_chain"}),
            "policy_actions": sorted({value for candidate, value in compile_items if candidate.candidate_type == "policy_action"}),
            "country_overrides": {}, "chain_overrides": {}, "seed": 42,
        }
        WarRoomScenarioRequest.model_validate(scenario)
        assumptions = {"changes": changed, "reason": payload.assumption_reason.strip(), "actor_user_id": actor.user_id}
        extraction_hashes = self._extraction_hashes(candidates)
        core = self._draft_core(project_id, payload.name, scenario, assumptions, candidates, decisions, extraction_hashes, None)
        draft_hash = stable_hash(core); draft_id = f"sdr_{uuid4().hex[:20]}"; now = _now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO scenario_drafts
                (draft_id, organization_id, project_id, version, status, name, scenario_json, manual_assumptions_json,
                 compiler_version, draft_hash, created_by_user_id, created_at)
                VALUES (?, ?, ?, 1, 'draft', ?, ?, ?, ?, ?, ?, ?)""",
                (draft_id, organization_id, project_id, payload.name, dumps(scenario), dumps(assumptions), COMPILER_VERSION, draft_hash, actor.user_id, now),
            )
            for position, (candidate, decision) in enumerate(zip(candidates, decisions, strict=True)):
                conn.execute(
                    """INSERT INTO scenario_draft_items
                    (draft_id, candidate_id, decision_id, position, candidate_hash, decision_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (draft_id, candidate.candidate_id, decision.decision_id, position, candidate.candidate_hash, decision.decision_hash, now),
                )
        scope_resource(organization_id, "scenario_draft", draft_id)
        return self.get_draft(organization_id, project_id, draft_id, actor)

    def list_drafts(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[ScenarioDraft]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute("SELECT draft_id FROM scenario_drafts WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, draft_id DESC", (organization_id, project_id)).fetchall()
        return [self.get_draft(organization_id, project_id, row["draft_id"], actor) for row in rows]

    def get_draft(self, organization_id: str, project_id: str, draft_id: str, actor: UserIdentity) -> ScenarioDraft:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute("SELECT * FROM scenario_drafts WHERE organization_id = ? AND project_id = ? AND draft_id = ?", (organization_id, project_id, draft_id)).fetchone()
            items = conn.execute("SELECT candidate_id FROM scenario_draft_items WHERE draft_id = ? ORDER BY position", (draft_id,)).fetchall() if row else []
            reviews = conn.execute("SELECT * FROM scenario_draft_reviews WHERE draft_id = ? ORDER BY created_at, review_id", (draft_id,)).fetchall() if row else []
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown scenario draft: {draft_id}")
        return _draft(row, [item["candidate_id"] for item in items], [_draft_review(item) for item in reviews])

    def submit_draft(self, organization_id: str, project_id: str, draft_id: str, actor: UserIdentity) -> ScenarioDraft:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        draft = self.get_draft(organization_id, project_id, draft_id, actor)
        if draft.status != "draft":
            raise HTTPException(status_code=409, detail="Only draft scenarios can be submitted")
        candidates, decisions = self._pinned_items(draft, actor)
        cutoff = max(self._candidate_cutoffs(candidates))
        claims = []
        for candidate in candidates:
            claims.append(evidence_registry.create_claim(EvidenceClaimCreate(
                project_id=project_id, statement=f"Scenario candidate {candidate.candidate_type}: {candidate.display_value}",
                claim_type="scenario_candidate", confidence=candidate.confidence, cutoff_at=cutoff,
                snapshot_ids=[candidate.snapshot_id], relation="supports",
            ), actor, organization_id=organization_id))
        pack = evidence_registry.create_pack(EvidencePackCreate(
            project_id=project_id, name=f"Scenario Draft {draft.name}", cutoff_at=cutoff,
            snapshot_ids=sorted({item.snapshot_id for item in candidates}), claim_ids=[item.claim_id for item in claims],
        ), actor, organization_id=organization_id)
        extraction_hashes = self._extraction_hashes(candidates)
        final_hash = stable_hash(self._draft_core(project_id, draft.name, draft.scenario, draft.manual_assumptions, candidates, decisions, extraction_hashes, pack.manifest_hash))
        review_case = create_review_case("scenario_draft_approval", "scenario_draft", draft_id, "Evidence-backed Scenario Draft requires independent approval", severity="high", payload={"project_id": project_id, "draft_hash": final_hash, "evidence_pack_hash": pack.manifest_hash})
        now = _now()
        with connect() as conn:
            changed = conn.execute(
                """UPDATE scenario_drafts SET status = 'submitted', submitted_by_user_id = ?, submitted_at = ?,
                evidence_pack_id = ?, evidence_pack_hash = ?, draft_hash = ?, review_case_id = ?
                WHERE draft_id = ? AND status = 'draft'""",
                (actor.user_id, now, pack.pack_id, pack.manifest_hash, final_hash, review_case.review_id, draft_id),
            )
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail="Scenario Draft state changed concurrently")
        return self.get_draft(organization_id, project_id, draft_id, actor)

    def review_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftReviewRequest, actor: UserIdentity) -> ScenarioDraft:
        require_organization_role(organization_id, actor, REVIEW_ROLES)
        draft = self.get_draft(organization_id, project_id, draft_id, actor)
        if draft.status != "submitted":
            raise HTTPException(status_code=409, detail="Only submitted Scenario Drafts can be reviewed")
        if draft.submitted_by_user_id == actor.user_id:
            raise HTTPException(status_code=403, detail="Scenario Draft submitter cannot approve or review their own submission")
        self._verify_draft_integrity(draft, actor)
        now = _now()
        review_core = {"draft_hash": draft.draft_hash, "decision": payload.decision, "comment": payload.comment, "reviewer": actor.user_id, "created_at": now}
        review_hash = stable_hash(review_core); review_id = f"srev_{review_hash[:20]}"
        next_status = {"approve": "approved", "request_revision": "revision_requested", "reject": "rejected"}[payload.decision]
        with connect() as conn:
            conn.execute(
                "INSERT INTO scenario_draft_reviews(review_id, draft_id, decision, comment, reviewer_user_id, review_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (review_id, draft_id, payload.decision, payload.comment, actor.user_id, review_hash, now),
            )
            changed = conn.execute(
                """UPDATE scenario_drafts SET status = ?, approved_by_user_id = CASE WHEN ? = 'approved' THEN ? ELSE NULL END,
                approved_at = CASE WHEN ? = 'approved' THEN ? ELSE NULL END, closed_at = CASE WHEN ? != 'approved' THEN ? ELSE NULL END
                WHERE draft_id = ? AND status = 'submitted'""",
                (next_status, next_status, actor.user_id, next_status, now, next_status, now, draft_id),
            )
            if draft.review_case_id:
                conn.execute("UPDATE review_cases SET status = 'closed', closed_at = ? WHERE review_id = ? AND status = 'open'", (now, draft.review_case_id))
        if changed.rowcount != 1:
            raise HTTPException(status_code=409, detail="Scenario Draft state changed concurrently")
        return self.get_draft(organization_id, project_id, draft_id, actor)

    def clone_draft(self, organization_id: str, project_id: str, draft_id: str, actor: UserIdentity) -> ScenarioDraft:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        parent = self.get_draft(organization_id, project_id, draft_id, actor)
        changes = parent.manual_assumptions.get("changes", {})
        payload = ScenarioDraftCreateRequest(
            name=f"{parent.name} · revision {parent.version + 1}", candidate_ids=parent.candidate_ids,
            duration_days=parent.scenario["duration_days"], intensity=parent.scenario["intensity"], propagation=parent.scenario["propagation"],
            assumption_reason=parent.manual_assumptions.get("reason", ""),
        )
        cloned = self.create_draft(organization_id, project_id, payload, actor)
        with connect() as conn:
            conn.execute("UPDATE scenario_drafts SET parent_draft_id = ?, version = ? WHERE draft_id = ?", (draft_id, parent.version + 1, cloned.draft_id))
            if parent.status in {"revision_requested", "rejected"}:
                conn.execute("UPDATE scenario_drafts SET status = 'superseded' WHERE draft_id = ?", (draft_id,))
        return self.get_draft(organization_id, project_id, cloned.draft_id, actor)

    def create_run_from_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftRunRequest, actor: UserIdentity) -> RunJobStatus:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        draft = self.get_draft(organization_id, project_id, draft_id, actor)
        if draft.status != "approved":
            raise HTTPException(status_code=409, detail="Only approved Scenario Drafts can create runs")
        self._verify_draft_integrity(draft, actor)
        scenario = WarRoomScenarioRequest.model_validate({**draft.scenario, "seed": payload.seed})
        job = lifecycle_repository.create_job(project_id, RunJobCreateRequest(engine_mode=payload.engine_mode, scenario=scenario, seed=payload.seed, max_attempts=payload.max_attempts))
        with connect() as conn:
            conn.execute(
                "UPDATE run_jobs SET scenario_draft_id = ?, scenario_draft_hash = ?, scenario_evidence_pack_hash = ? WHERE run_id = ?",
                (draft.draft_id, draft.draft_hash, draft.evidence_pack_hash, job.run_id),
            )
        lifecycle_repository.append_event(job.run_id, "SNAPSHOT", "scenario_compile", "Evidence-backed Scenario Draft pinned", "运行已固定经双人审批的 Draft 与 Evidence Pack Hash。", payload={"scenario_draft_id": draft.draft_id, "scenario_draft_hash": draft.draft_hash, "scenario_evidence_pack_hash": draft.evidence_pack_hash})
        return lifecycle_repository.get_job(job.run_id)

    def get_extraction(self, organization_id: str, project_id: str, job_id: str, actor: UserIdentity) -> DocumentExtraction | None:
        self.get_extraction_job(organization_id, project_id, job_id, actor)
        with connect() as conn:
            row = conn.execute("SELECT * FROM document_extractions WHERE job_id = ?", (job_id,)).fetchone()
        return _extraction(row) if row else None

    def append_extraction_event(self, job_id: str, event_type: str, title: str, detail: str, payload: dict) -> DocumentExtractionEvent:
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO document_extraction_event_counters(job_id, next_seq) VALUES (?, 1) ON CONFLICT(job_id) DO NOTHING", (job_id,))
            if is_postgres_url():
                counter = conn.execute("UPDATE document_extraction_event_counters SET next_seq = next_seq + 1 WHERE job_id = ? RETURNING next_seq - 1 AS seq", (job_id,)).fetchone(); seq = int(counter["seq"])
            else:
                counter = conn.execute("SELECT next_seq FROM document_extraction_event_counters WHERE job_id = ?", (job_id,)).fetchone(); seq = int(counter["next_seq"])
                conn.execute("UPDATE document_extraction_event_counters SET next_seq = ? WHERE job_id = ?", (seq + 1, job_id))
            now = _now()
            conn.execute("INSERT INTO document_extraction_events(job_id, seq, event_type, title, detail, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)", (job_id, seq, event_type, title, detail, dumps(payload), now))
        return DocumentExtractionEvent(job_id=job_id, seq=seq, event_type=event_type, title=title, detail=detail, payload=payload, created_at=now)

    def verify_blobs(self) -> dict:
        init_db()
        with connect() as conn:
            rows = conn.execute("SELECT document_id, blob_key, content_hash, size_bytes FROM source_documents ORDER BY document_id").fetchall()
        results = [{"document_id": row["document_id"], **verify_blob(row["blob_key"], row["content_hash"], int(row["size_bytes"]))} for row in rows]
        failures = [item for item in results if item["status"] != "verified"]
        return {"status": "ok" if not failures else "failed", "documents": len(results), "verified": len(results) - len(failures), "failures": failures}

    def _cancel_boundary(self, job_id: str) -> None:
        with connect() as conn:
            row = conn.execute("SELECT status FROM document_extraction_jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row and row["status"] in {"cancelling", "cancelled"}:
            raise _CancelledAtBoundary()

    def _project_access(self, organization_id: str, project_id: str, actor: UserIdentity) -> None:
        require_organization_role(organization_id, actor, READ_ROLES)
        require_resource_scope(organization_id, "project", project_id)

    def _get_candidate(self, organization_id: str, project_id: str, candidate_id: str, actor: UserIdentity) -> ScenarioCandidate:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute("SELECT * FROM scenario_candidates WHERE organization_id = ? AND project_id = ? AND candidate_id = ?", (organization_id, project_id, candidate_id)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown scenario candidate: {candidate_id}")
        return self._candidate_with_decision(row)

    def _candidate_with_decision(self, row) -> ScenarioCandidate:
        with connect() as conn:
            decision = conn.execute("SELECT * FROM scenario_candidate_decisions WHERE candidate_id = ? ORDER BY created_at DESC, decision_id DESC LIMIT 1", (row["candidate_id"],)).fetchone()
        return _candidate(row, _decision(decision) if decision else None)

    def _get_decision(self, decision_id: str) -> ScenarioCandidateDecision:
        with connect() as conn:
            row = conn.execute("SELECT * FROM scenario_candidate_decisions WHERE decision_id = ?", (decision_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown candidate decision: {decision_id}")
        return _decision(row)

    def _pinned_items(self, draft: ScenarioDraft, actor: UserIdentity):
        candidates, decisions = [], []
        with connect() as conn:
            rows = conn.execute("SELECT * FROM scenario_draft_items WHERE draft_id = ? ORDER BY position", (draft.draft_id,)).fetchall()
        for item in rows:
            candidate = self._get_candidate(draft.organization_id, draft.project_id, item["candidate_id"], actor)
            decision = self._get_decision(item["decision_id"])
            if candidate.candidate_hash != item["candidate_hash"] or decision.decision_hash != item["decision_hash"]:
                raise HTTPException(status_code=409, detail="Scenario Draft candidate integrity verification failed")
            if decision.candidate_id != candidate.candidate_id or decision.organization_id != draft.organization_id or decision.project_id != draft.project_id or decision.decision != "accepted":
                raise HTTPException(status_code=409, detail="Scenario Draft pinned candidate decision is invalid")
            candidates.append(candidate); decisions.append(decision)
        return candidates, decisions

    def _candidate_cutoffs(self, candidates: list[ScenarioCandidate]) -> list[str]:
        with connect() as conn:
            rows = [conn.execute("SELECT cutoff_at FROM evidence_snapshots WHERE snapshot_id = ?", (item.snapshot_id,)).fetchone() for item in candidates]
        return [row["cutoff_at"] for row in rows if row]

    def _extraction_hashes(self, candidates: list[ScenarioCandidate]) -> list[dict[str, str]]:
        extraction_ids = sorted({item.extraction_id for item in candidates})
        with connect() as conn:
            rows = [conn.execute("SELECT extraction_id, extraction_hash FROM document_extractions WHERE extraction_id = ?", (item,)).fetchone() for item in extraction_ids]
        return [{row["extraction_id"]: row["extraction_hash"]} for row in rows if row]

    def _draft_core(self, project_id, draft_name, scenario, assumptions, candidates, decisions, extraction_hashes, evidence_pack_hash):
        return {
            "schema_version": "scenario-compile-manifest.v1", "compiler_version": COMPILER_VERSION,
            "project_id": project_id, "draft_name": draft_name, "scenario": scenario, "manual_assumptions": assumptions,
            "candidate_hashes": [{item.candidate_id: item.candidate_hash} for item in candidates],
            "decision_hashes": [{item.decision_id: item.decision_hash} for item in decisions],
            "extraction_hashes": extraction_hashes, "evidence_pack_hash": evidence_pack_hash,
        }

    def _verify_draft_integrity(self, draft: ScenarioDraft, actor: UserIdentity) -> None:
        candidates, decisions = self._pinned_items(draft, actor)
        if not draft.evidence_pack_id or not draft.evidence_pack_hash:
            raise HTTPException(status_code=409, detail="Submitted Scenario Draft has no frozen Evidence Pack")
        pack = evidence_registry.get_pack(draft.evidence_pack_id, organization_id=draft.organization_id)
        if pack.manifest_hash != draft.evidence_pack_hash:
            raise HTTPException(status_code=409, detail="Scenario Draft Evidence Pack hash mismatch")
        expected = stable_hash(self._draft_core(draft.project_id, draft.name, draft.scenario, draft.manual_assumptions, candidates, decisions, self._extraction_hashes(candidates), draft.evidence_pack_hash))
        if expected != draft.draft_hash:
            raise HTTPException(status_code=409, detail="Scenario Draft hash verification failed")


class _CancelledAtBoundary(RuntimeError):
    pass


def _document(row) -> SourceDocument:
    return SourceDocument(
        document_id=row["document_id"], organization_id=row["organization_id"], project_id=row["project_id"],
        original_filename=row["original_filename"], media_type=row["media_type"], size_bytes=int(row["size_bytes"]),
        content_hash=row["content_hash"], title=row["title"], category=row["category"], publisher=row["publisher"],
        license_name=row["license_name"], license_url=row["license_url"], observed_at=row["observed_at"], cutoff_at=row["cutoff_at"],
        status=row["status"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"],
    )


def _job(row) -> DocumentExtractionJob:
    return DocumentExtractionJob(
        job_id=row["job_id"], organization_id=row["organization_id"], project_id=row["project_id"], document_id=row["document_id"],
        parent_job_id=row["parent_job_id"], status=row["status"], request_hash=row["request_hash"], extractor_version=row["extractor_version"],
        provider=row["provider"], worker_id=row["worker_id"], attempt_count=int(row["attempt_count"]), warnings=loads(row["warning_json"], []),
        error_code=row["error_code"], error_message=row["error_message"], created_by_user_id=row["created_by_user_id"],
        created_at=row["created_at"], started_at=row["started_at"], updated_at=row["updated_at"], completed_at=row["completed_at"],
    )


def _event(row) -> DocumentExtractionEvent:
    return DocumentExtractionEvent(job_id=row["job_id"], seq=int(row["seq"]), event_type=row["event_type"], title=row["title"], detail=row["detail"], payload=loads(row["payload_json"], {}), created_at=row["created_at"])


def _extraction(row) -> DocumentExtraction:
    return DocumentExtraction(extraction_id=row["extraction_id"], job_id=row["job_id"], document_id=row["document_id"], extractor_version=row["extractor_version"], chunk_manifest=loads(row["chunk_manifest_json"], []), snapshot_ids=loads(row["snapshot_ids_json"], []), provider_audit=loads(row["provider_audit_json"], {}), extraction_hash=row["extraction_hash"], total_chars=int(row["total_chars"]), total_chunks=int(row["total_chunks"]), created_at=row["created_at"])


def _candidate(row, latest_decision=None) -> ScenarioCandidate:
    return ScenarioCandidate(candidate_id=row["candidate_id"], extraction_id=row["extraction_id"], organization_id=row["organization_id"], project_id=row["project_id"], candidate_type=row["candidate_type"], canonical_value=row["canonical_value"], display_value=row["display_value"], relation=loads(row["relation_json"], {}), snapshot_id=row["snapshot_id"], locator=loads(row["locator_json"], {}), excerpt=row["excerpt"], confidence=float(row["confidence"]), extractor_source=row["extractor_source"], validation_status=row["validation_status"], validation_reason=row["validation_reason"], candidate_hash=row["candidate_hash"], created_at=row["created_at"], latest_decision=latest_decision)


def _decision(row) -> ScenarioCandidateDecision:
    return ScenarioCandidateDecision(decision_id=row["decision_id"], candidate_id=row["candidate_id"], organization_id=row["organization_id"], project_id=row["project_id"], decision=row["decision"], normalized_value=row["normalized_value"], comment=row["comment"], actor_user_id=row["actor_user_id"], decision_hash=row["decision_hash"], created_at=row["created_at"])


def _draft(row, candidate_ids, reviews) -> ScenarioDraft:
    return ScenarioDraft(draft_id=row["draft_id"], organization_id=row["organization_id"], project_id=row["project_id"], parent_draft_id=row["parent_draft_id"], version=int(row["version"]), status=row["status"], name=row["name"], scenario=loads(row["scenario_json"], {}), manual_assumptions=loads(row["manual_assumptions_json"], {}), compiler_version=row["compiler_version"], evidence_pack_id=row["evidence_pack_id"], evidence_pack_hash=row["evidence_pack_hash"], draft_hash=row["draft_hash"], created_by_user_id=row["created_by_user_id"], submitted_by_user_id=row["submitted_by_user_id"], approved_by_user_id=row["approved_by_user_id"], review_case_id=row["review_case_id"], created_at=row["created_at"], submitted_at=row["submitted_at"], approved_at=row["approved_at"], closed_at=row["closed_at"], candidate_ids=candidate_ids, reviews=reviews)


def _draft_review(row) -> ScenarioDraftReview:
    return ScenarioDraftReview(review_id=row["review_id"], draft_id=row["draft_id"], decision=row["decision"], comment=row["comment"], reviewer_user_id=row["reviewer_user_id"], review_hash=row["review_hash"], created_at=row["created_at"])


def _validate_canonical(candidate_type: str, value: str) -> None:
    allowed = {"scenario_preset": {item.key for item in SCENARIOS}, "country": {item.code for item in COUNTRIES}, "supply_chain": {item.key for item in SUPPLY_CHAINS}, "policy_action": set(POLICY_ACTIONS)}
    if candidate_type in allowed and value not in allowed[candidate_type]:
        raise HTTPException(status_code=422, detail=f"Unknown canonical {candidate_type}: {value}")


def _provider_name() -> str:
    value = os.getenv("SCENARIO_EXTRACTION_PROVIDER", "disabled").strip().lower()
    return value if value in {"disabled", "deepseek", "siliconflow"} else "disabled"


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Timestamp must be ISO-8601") from exc
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
