from __future__ import annotations
import json
import time
from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse
from app.api.dependencies import current_actor
from app.core.evaluation_models import EvaluationBatchCreateRequest, EvaluationBatch, EvaluationMember, EvaluationMetric, EvaluationReport, EvaluationSuiteManifest
from app.services.evaluation import EvaluationApplicationPort, EvaluationService

router = APIRouter()
service: EvaluationApplicationPort = EvaluationService()

def actor(request: Request):
    return current_actor(request)

def organization(request: Request) -> str:
    return str(request.state.organization_id)

@router.get("/evaluation/suites", response_model=list[EvaluationSuiteManifest])
def suites(): return service.list_suites()

@router.get("/organizations/{organization_id}/evaluations", response_model=list[EvaluationBatch])
def batches(organization_id: str, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return service.list_batches(organization_id)

@router.post("/organizations/{organization_id}/evaluations/standard", response_model=EvaluationBatch)
def standard(organization_id: str, payload: EvaluationBatchCreateRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return service.create_standard_batch(organization_id, actor(request), payload)

@router.post("/organizations/{organization_id}/evaluations/observation", response_model=EvaluationBatch)
def observation(organization_id: str, payload: EvaluationBatchCreateRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return service.create_batch(organization_id, actor(request), payload, source_type="observation")

@router.post("/organizations/{organization_id}/projects/{project_id}/scenario-drafts/{draft_id}/evaluations", response_model=EvaluationBatch)
def project_experiment(organization_id: str, project_id: str, draft_id: str, payload: EvaluationBatchCreateRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return service.create_project_experiment(organization_id, project_id, draft_id, actor(request), payload)

@router.get("/evaluations/{batch_id}", response_model=EvaluationBatch)
def detail(batch_id: str, request: Request): return service.get_batch(batch_id, organization(request))

@router.get("/evaluations/{batch_id}/members", response_model=list[EvaluationMember])
def members(batch_id: str, request: Request): return service.list_members(batch_id, organization(request))

@router.get("/evaluations/{batch_id}/metrics", response_model=list[EvaluationMetric])
def metrics(batch_id: str, request: Request): return service.list_metrics(batch_id, organization(request))

@router.get("/evaluations/{batch_id}/events", response_model=list[dict])
def events(batch_id: str, request: Request, after_seq: int = Query(default=0, ge=0)): return service.list_events(batch_id, after_seq, organization(request))

@router.get("/evaluations/{batch_id}/events/stream")
def event_stream(batch_id: str, request: Request, after_seq: int = Query(default=0, ge=0)):
    organization_id = organization(request)
    service.get_batch(batch_id, organization_id)
    last = request.headers.get("last-event-id")
    if last and last.isdigit():
        after_seq = max(after_seq, int(last))
    def generate():
        cursor = after_seq
        idle = 0
        while idle < 20:
            rows = service.list_events(batch_id, cursor, organization_id)
            if rows:
                idle = 0
                for row in rows:
                    cursor = max(cursor, row["seq"])
                    yield f"id: {row['seq']}\nevent: evaluation\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            else:
                idle += 1
                yield ": keepalive\n\n"
                time.sleep(0.5)
    return StreamingResponse(generate(), media_type="text/event-stream")

@router.get("/evaluations/{batch_id}/report", response_model=EvaluationReport)
def report(batch_id: str, request: Request): return service.report(batch_id, organization(request))

@router.post("/evaluations/{batch_id}/pause", response_model=EvaluationBatch)
def pause(batch_id: str, request: Request): return service.control(batch_id, "pause", organization(request))

@router.post("/evaluations/{batch_id}/resume", response_model=EvaluationBatch)
def resume(batch_id: str, request: Request): return service.control(batch_id, "resume", organization(request))

@router.post("/evaluations/{batch_id}/cancel", response_model=EvaluationBatch)
def cancel(batch_id: str, request: Request): return service.control(batch_id, "cancel", organization(request))

@router.post("/evaluations/{batch_id}/retry", response_model=EvaluationBatch)
def retry(batch_id: str, request: Request): return service.retry(batch_id, actor(request), organization(request))
