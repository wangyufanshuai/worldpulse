"""Application port for the Scenario Compiler bounded context."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

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


class ScenarioCompilerApplicationPort(Protocol):
    def register_generated_document(
        self,
        organization_id: str,
        project_id: str,
        content: str,
        actor: Any,
        *,
        filename: str,
        title: str,
        category: str,
        publisher: str,
        license_name: str,
        license_url: str,
        observed_at: str,
        cutoff_at: str,
    ) -> DocumentUploadResult: ...

    async def upload_document(
        self,
        organization_id: str,
        project_id: str,
        upload: Any,
        actor: Any,
        *,
        title: str,
        category: str,
        publisher: str,
        license_name: str,
        license_url: str,
        observed_at: str,
        cutoff_at: str,
    ) -> DocumentUploadResult: ...

    def list_documents(self, organization_id: str, project_id: str, actor: Any) -> list[SourceDocument]: ...

    def get_document(self, organization_id: str, project_id: str, document_id: str, actor: Any) -> SourceDocument: ...

    def document_download(self, organization_id: str, project_id: str, document_id: str, actor: Any) -> tuple[Path, SourceDocument]: ...

    def create_extraction_job(self, organization_id: str, project_id: str, document_id: str, actor: Any, *, provider_override: str | None = None) -> DocumentExtractionJob: ...

    def list_extraction_jobs(self, organization_id: str, project_id: str, actor: Any) -> list[DocumentExtractionJob]: ...

    def get_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob: ...

    def list_extraction_events(self, organization_id: str, project_id: str, job_id: str, actor: Any, after_seq: int = 0) -> list[DocumentExtractionEvent]: ...

    def cancel_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob: ...

    def retry_extraction_job(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtractionJob: ...

    def claim_next_extraction_job(self, worker_id: str) -> tuple[str, str, str] | None: ...

    def execute_claimed_extraction(self, organization_id: str, project_id: str, job_id: str, worker_id: str) -> DocumentExtractionJob: ...

    def execute_extraction(self, organization_id: str, project_id: str, job_id: str, actor: Any, *, worker_id: str = "api-bounded-executor") -> DocumentExtractionJob: ...

    def list_candidates(self, organization_id: str, project_id: str, actor: Any) -> list[ScenarioCandidate]: ...

    def decide_candidate(self, organization_id: str, project_id: str, candidate_id: str, payload: ScenarioCandidateDecisionRequest, actor: Any) -> ScenarioCandidateDecision: ...

    def create_draft(self, organization_id: str, project_id: str, payload: ScenarioDraftCreateRequest, actor: Any) -> ScenarioDraft: ...

    def list_drafts(self, organization_id: str, project_id: str, actor: Any) -> list[ScenarioDraft]: ...

    def get_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft: ...

    def submit_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft: ...

    def review_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftReviewRequest, actor: Any) -> ScenarioDraft: ...

    def clone_draft(self, organization_id: str, project_id: str, draft_id: str, actor: Any) -> ScenarioDraft: ...

    def create_run_from_draft(self, organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftRunRequest, actor: Any) -> RunJobStatus: ...

    def get_extraction(self, organization_id: str, project_id: str, job_id: str, actor: Any) -> DocumentExtraction | None: ...

    def append_extraction_event(self, job_id: str, event_type: str, title: str, detail: str, payload: dict) -> DocumentExtractionEvent: ...

    def verify_blobs(self) -> dict: ...
