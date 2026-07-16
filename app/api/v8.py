from __future__ import annotations

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from fastapi.responses import FileResponse

from app.core.models import RunJobStatus
from app.core.scenario_compiler_models import (
    DocumentExtractionEvent, DocumentExtractionJob, DocumentUploadResult, ScenarioCandidate,
    ScenarioCandidateDecision, ScenarioCandidateDecisionRequest, ScenarioDraft, ScenarioDraftCreateRequest,
    ScenarioDraftReviewRequest, ScenarioDraftRunRequest, SourceDocument,
)
from app.services.auth import ensure_system_user
from app.services.scenario_compiler import ScenarioCompilerService


router = APIRouter()
service = ScenarioCompilerService()


def _actor(request: Request):
    return getattr(request.state, "user", None) or ensure_system_user()


@router.post("/organizations/{organization_id}/projects/{project_id}/documents", response_model=DocumentUploadResult)
async def document_upload(
    organization_id: str, project_id: str, request: Request,
    file: UploadFile = File(...), title: str = Form(...), category: str = Form(...),
    publisher: str = Form(...), license_name: str = Form(...), license_url: str = Form(""),
    observed_at: str = Form(...), cutoff_at: str = Form(...),
) -> DocumentUploadResult:
    return await service.upload_document(
        organization_id, project_id, file, _actor(request), title=title, category=category,
        publisher=publisher, license_name=license_name, license_url=license_url,
        observed_at=observed_at, cutoff_at=cutoff_at,
    )


@router.get("/organizations/{organization_id}/projects/{project_id}/documents", response_model=list[SourceDocument])
def document_list(organization_id: str, project_id: str, request: Request) -> list[SourceDocument]:
    return service.list_documents(organization_id, project_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/documents/{document_id}", response_model=SourceDocument)
def document_detail(organization_id: str, project_id: str, document_id: str, request: Request) -> SourceDocument:
    return service.get_document(organization_id, project_id, document_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/documents/{document_id}/download")
def document_download(organization_id: str, project_id: str, document_id: str, request: Request):
    path, document = service.document_download(organization_id, project_id, document_id, _actor(request))
    return FileResponse(path, media_type=document.media_type, filename=document.original_filename, content_disposition_type="attachment")


@router.post("/organizations/{organization_id}/projects/{project_id}/documents/{document_id}/extract", response_model=DocumentExtractionJob)
def extraction_create(organization_id: str, project_id: str, document_id: str, request: Request) -> DocumentExtractionJob:
    return service.create_extraction_job(organization_id, project_id, document_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/extraction-jobs", response_model=list[DocumentExtractionJob])
def extraction_list(organization_id: str, project_id: str, request: Request) -> list[DocumentExtractionJob]:
    return service.list_extraction_jobs(organization_id, project_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}", response_model=DocumentExtractionJob)
def extraction_detail(organization_id: str, project_id: str, job_id: str, request: Request) -> DocumentExtractionJob:
    return service.get_extraction_job(organization_id, project_id, job_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}/events", response_model=list[DocumentExtractionEvent])
def extraction_events(organization_id: str, project_id: str, job_id: str, request: Request, after_seq: int = Query(default=0, ge=0)) -> list[DocumentExtractionEvent]:
    return service.list_extraction_events(organization_id, project_id, job_id, _actor(request), after_seq=after_seq)


@router.post("/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}/cancel", response_model=DocumentExtractionJob)
def extraction_cancel(organization_id: str, project_id: str, job_id: str, request: Request) -> DocumentExtractionJob:
    return service.cancel_extraction_job(organization_id, project_id, job_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}/retry", response_model=DocumentExtractionJob)
def extraction_retry(organization_id: str, project_id: str, job_id: str, request: Request) -> DocumentExtractionJob:
    return service.retry_extraction_job(organization_id, project_id, job_id, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/scenario-candidates", response_model=list[ScenarioCandidate])
def scenario_candidates(organization_id: str, project_id: str, request: Request) -> list[ScenarioCandidate]:
    return service.list_candidates(organization_id, project_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-candidates/{candidate_id}/decision", response_model=ScenarioCandidateDecision)
def scenario_candidate_decision(organization_id: str, project_id: str, candidate_id: str, payload: ScenarioCandidateDecisionRequest, request: Request) -> ScenarioCandidateDecision:
    return service.decide_candidate(organization_id, project_id, candidate_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/scenario-drafts", response_model=list[ScenarioDraft])
def scenario_draft_list(organization_id: str, project_id: str, request: Request) -> list[ScenarioDraft]:
    return service.list_drafts(organization_id, project_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts", response_model=ScenarioDraft)
def scenario_draft_create(organization_id: str, project_id: str, payload: ScenarioDraftCreateRequest, request: Request) -> ScenarioDraft:
    return service.create_draft(organization_id, project_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}", response_model=ScenarioDraft)
def scenario_draft_detail(organization_id: str, project_id: str, draft_id: str, request: Request) -> ScenarioDraft:
    return service.get_draft(organization_id, project_id, draft_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}/submit", response_model=ScenarioDraft)
def scenario_draft_submit(organization_id: str, project_id: str, draft_id: str, request: Request) -> ScenarioDraft:
    return service.submit_draft(organization_id, project_id, draft_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}/review", response_model=ScenarioDraft)
def scenario_draft_review(organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftReviewRequest, request: Request) -> ScenarioDraft:
    return service.review_draft(organization_id, project_id, draft_id, payload, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}/clone", response_model=ScenarioDraft)
def scenario_draft_clone(organization_id: str, project_id: str, draft_id: str, request: Request) -> ScenarioDraft:
    return service.clone_draft(organization_id, project_id, draft_id, _actor(request))


@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}/runs", response_model=RunJobStatus)
def scenario_draft_run(organization_id: str, project_id: str, draft_id: str, payload: ScenarioDraftRunRequest, request: Request) -> RunJobStatus:
    return service.create_run_from_draft(organization_id, project_id, draft_id, payload, _actor(request))
