from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.evaluation_models import (
    EvaluationBatch,
    EvaluationVerificationResult,
    HistoricalBenchmarkCase,
    HistoricalBenchmarkReport,
    HistoricalBenchmarkSuite,
    HistoricalEvaluationCreateRequest,
    LabelPackImportRequest,
    LabelPackReviewRequest,
    SealedLabelPack,
)
from app.services.auth import ensure_system_user
from app.services.evaluation import EvaluationService
from app.services.evaluation import benchmark
from app.services.evaluation.gates import list_verification_results


router = APIRouter()
service = EvaluationService()


def actor(request: Request):
    return getattr(request.state, "user", None) or ensure_system_user()


def organization(request: Request) -> str:
    return str(request.state.organization_id)


@router.get("/evaluation/benchmark-suites", response_model=list[HistoricalBenchmarkSuite])
def benchmark_suites():
    return benchmark.list_suites()


@router.get("/evaluation/benchmark-suites/{suite_id}", response_model=HistoricalBenchmarkSuite)
def benchmark_suite(suite_id: str):
    return benchmark.get_suite(suite_id)


@router.get("/evaluation/benchmark-suites/{suite_id}/cases", response_model=list[HistoricalBenchmarkCase])
def benchmark_cases(suite_id: str):
    return benchmark.list_cases(suite_id)


@router.post("/organizations/{organization_id}/evaluation/label-packs", response_model=SealedLabelPack)
def import_label_pack(organization_id: str, payload: LabelPackImportRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return benchmark.import_label_pack(organization_id, payload, actor(request))


@router.get("/organizations/{organization_id}/evaluation/label-packs", response_model=list[SealedLabelPack])
def label_packs(organization_id: str, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return benchmark.list_label_packs(organization_id)


@router.post("/organizations/{organization_id}/evaluation/label-packs/{pack_id}/approve", response_model=SealedLabelPack)
def approve_label_pack(organization_id: str, pack_id: str, payload: LabelPackReviewRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return benchmark.review_label_pack(organization_id, pack_id, payload, actor(request))


@router.post("/organizations/{organization_id}/evaluations/historical", response_model=EvaluationBatch)
def create_historical(organization_id: str, payload: HistoricalEvaluationCreateRequest, request: Request):
    if organization_id != organization(request):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Unknown organization resource")
    return service.create_historical_batch(organization_id, actor(request), payload)


@router.get("/evaluations/{batch_id}/verification", response_model=list[EvaluationVerificationResult])
def verification(batch_id: str, request: Request):
    service.get_batch(batch_id, organization(request))
    return list_verification_results(batch_id)


@router.get("/evaluations/{batch_id}/historical-report", response_model=HistoricalBenchmarkReport)
def historical_report(batch_id: str, request: Request):
    return service.historical_report(batch_id, organization(request))
