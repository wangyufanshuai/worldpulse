"""Compatibility application adapter for Scenario Compiler.

The public port is intentionally thin for this slice.  It lets API, worker,
and monitoring callers stop depending on the storage-heavy V1 service while
the compiler's repositories and state transitions migrate behind it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.models import RunJobStatus
from app.core.scenario_compiler_models import (
    DocumentExtraction,
    DocumentExtractionEvent,
    DocumentExtractionJob,
    DocumentUploadResult,
    ScenarioCandidate,
    ScenarioCandidateDecision,
    ScenarioCandidateDecisionRequest,
    ScenarioDraft,
    ScenarioDraftCreateRequest,
    ScenarioDraftReviewRequest,
    ScenarioDraftRunRequest,
    SourceDocument,
)

from .ports import ScenarioCompilerApplicationPort
from .service import ScenarioCompilerService


class ScenarioCompilerApplicationService:
    def __init__(self, delegate: ScenarioCompilerService | None = None) -> None:
        self._delegate = delegate or ScenarioCompilerService()

    def register_generated_document(self, organization_id: str, project_id: str, content: str, actor: Any, *, filename: str, title: str, category: str, publisher: str, license_name: str, license_url: str, observed_at: str, cutoff_at: str) -> DocumentUploadResult:
        return self._delegate.register_generated_document(organization_id, project_id, content, actor, filename=filename, title=title, category=category, publisher=publisher, license_name=license_name, license_url=license_url, observed_at=observed_at, cutoff_at=cutoff_at)

    async def upload_document(self, organization_id: str, project_id: str, upload: Any, actor: Any, *, title: str, category: str, publisher: str, license_name: str, license_url: str, observed_at: str, cutoff_at: str) -> DocumentUploadResult:
        return await self._delegate.upload_document(organization_id, project_id, upload, actor, title=title, category=category, publisher=publisher, license_name=license_name, license_url=license_url, observed_at=observed_at, cutoff_at=cutoff_at)

    def list_documents(self, organization_id: str, project_id: str, actor: Any) -> list[SourceDocument]:
        return self._delegate.list_documents(organization_id, project_id, actor)

    def get_document(self, organization_id: str, project_id: str, document_id: str, actor: Any) -> SourceDocument:
        return self._delegate.get_document(organization_id, project_id, document_id, actor)

    def document_download(self, organization_id: str, project_id: str, document_id: str, actor: Any) -> tuple[Path, SourceDocument]:
        return self._delegate.document_download(organization_id, project_id, document_id, actor)

    def create_extraction_job(self, organization_id: str, project_id: str, document_id: str, actor: Any, *, provider_override: str | None = None) -> DocumentExtractionJob:
        return self._delegate.create_extraction_job(organization_id, project_id, document_id, actor, provider_override=provider_override)

    def list_extraction_jobs(self, organization_id: str, project_id: str, actor: Any) -> list[DocumentExtractionJob]:
        return self._delegate.list_extraction_jobs(organization_id, project_id, actor)

    def get_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob:
        return self._delegate.get_extraction_job(organization_id, project_id, job_id, actor)

    def list_extraction_events(self, organization_id: str, project_id: str, job_id: str, actor: Any, after_seq: int = 0) -> list[DocumentExtractionEvent]:
        return self._delegate.list_extraction_events(organization_id, project_id, job_id, actor, after_seq=after_seq)

    def cancel_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob:
        return self._delegate.cancel_extraction_job(organization_id, project_id, job_id, actor)

    def retry_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob:
        return self._delegate.retry_extraction_job(organization_id, project_id, job_id, actor)

    def claim_next_extraction_job(self, worker_id: str) -> tuple[str, str, str] | None:
        return self._delegate.claim_next_extraction_job(worker_id)

    def execute_claimed_extraction(self, organization_id: str, project_id: str, job_id: str, worker_id: str) -> DocumentExtractionJob:
        return self._delegate.execute_claimed_extraction(organization_id, project_id, job_id, worker_id)

    def execute_extraction(self, organization_id: str, project_id: str, job_id: str, actor: Any, *, worker_id: str = "api-bounded-executor") -> DocumentExtractionJob:
        return self._delegate.execute_extraction(organization_id, project_id, job_id, actor, worker_id=worker_id)

    def list_candidates(self, organization_id: str, project_id: str, actor: Any) -> list[ScenarioCandidate]:
        return self._delegate.list_candidates(organization_id, project_id, actor)

    def decide_candidate(self, organization_id: str, project_id: str, candidate_id: str, payload: ScenarioCandidateDecisionRequest, actor: Any) -> ScenarioCandidateDecision:
        return self._delegate.decide_candidate(organization_id, project_id, candidate_id, payload, actor)

    def create_draft(self, organization_id: str, project_id: str, payload: ScenarioDraftCreateRequest, actor: Any) -> ScenarioDraft:
        return self._delegate.create_draft(organization_id, project_id, payload, actor)

    def list_drafts(self, organization_id: str, project_id: str, actor: Any) -> list[ScenarioDraft]:
        return self._delegate.list_drafts(organization_id, project_id, actor)

    def get_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft:
        return self._delegate.get_draft(organization_id, project_id, draft_id, actor)

    def submit_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft:
        return self._delegate.submit_draft(organization_id, project_id, draft_id, actor)

    def review_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftReviewRequest, actor: Any) -> ScenarioDraft:
        return self._delegate.review_draft(organization_id, project_id, draft_id, payload, actor)

    def clone_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft:
        return self._delegate.clone_draft(organization_id, project_id, draft_id, actor)

    def create_run_from_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftRunRequest, actor: Any) -> RunJobStatus:
        return self._delegate.create_run_from_draft(organization_id, project_id, draft_id, payload, actor)

    def get_extraction(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtraction | None:
        return self._delegate.get_extraction(organization_id, project_id, job_id, actor)

    def append_extraction_event(self, job_id: str, event_type: str, title: str, detail: str, payload: dict) -> DocumentExtractionEvent:
        return self._delegate.append_extraction_event(job_id, event_type, title, detail, payload)

    def verify_blobs(self) -> dict:
        return self._delegate.verify_blobs()


scenario_compiler_service: ScenarioCompilerApplicationPort = ScenarioCompilerApplicationService()
