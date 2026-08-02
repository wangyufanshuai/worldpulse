from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.api.dependencies import current_actor
from app.core.evidence_models import (
    EvidenceClaim,
    EvidenceClaimCreate,
    EvidencePack,
    EvidencePackCreate,
    EvidenceSearchResult,
    EvidenceSnapshot,
    EvidenceSnapshotCreate,
    EvidenceSource,
    EvidenceSourceCreate,
    EvidenceSyncResult,
    ProjectEvidenceSummary,
)
from app.services.evidence import EvidenceApplicationPort, evidence_service


router = APIRouter()
service: EvidenceApplicationPort = evidence_service


def _actor(request: Request):
    return current_actor(request)


def _organization(request: Request) -> str:
    return getattr(request.state, "organization_id", "org_default")


@router.get("/evidence/sources", response_model=list[EvidenceSource])
def evidence_sources(request: Request, status: str | None = None, source_type: str | None = None) -> list[EvidenceSource]:
    return service.list_sources(status=status, source_type=source_type, organization_id=_organization(request))


@router.post("/evidence/sources", response_model=EvidenceSource)
def evidence_source_create(payload: EvidenceSourceCreate, request: Request) -> EvidenceSource:
    return service.create_source(payload, _actor(request), organization_id=_organization(request))


@router.get("/evidence/sources/{source_id}", response_model=EvidenceSource)
def evidence_source_detail(source_id: str, request: Request) -> EvidenceSource:
    return service.get_source(source_id, organization_id=_organization(request))


@router.post("/evidence/snapshots", response_model=EvidenceSnapshot)
def evidence_snapshot_create(payload: EvidenceSnapshotCreate, request: Request) -> EvidenceSnapshot:
    return service.create_snapshot(payload, _actor(request), organization_id=_organization(request))


@router.get("/evidence/snapshots/{snapshot_id}", response_model=EvidenceSnapshot)
def evidence_snapshot_detail(snapshot_id: str, request: Request) -> EvidenceSnapshot:
    return service.get_snapshot(snapshot_id, organization_id=_organization(request))


@router.post("/evidence/claims", response_model=EvidenceClaim)
def evidence_claim_create(payload: EvidenceClaimCreate, request: Request) -> EvidenceClaim:
    return service.create_claim(payload, _actor(request), organization_id=_organization(request))


@router.get("/evidence/claims/{claim_id}", response_model=EvidenceClaim)
def evidence_claim_detail(claim_id: str, request: Request) -> EvidenceClaim:
    return service.get_claim(claim_id, organization_id=_organization(request))


@router.get("/evidence/search", response_model=EvidenceSearchResult)
def evidence_search(
    request: Request, query: str = "", project_id: str | None = None, category: str | None = None,
    cutoff_at: str | None = None, limit: int = Query(default=50, ge=1, le=200),
) -> EvidenceSearchResult:
    return service.search_evidence(
        query=query, project_id=project_id, category=category, cutoff_at=cutoff_at, limit=limit,
        organization_id=_organization(request),
    )


@router.post("/evidence/packs", response_model=EvidencePack)
def evidence_pack_create(payload: EvidencePackCreate, request: Request) -> EvidencePack:
    return service.create_pack(payload, _actor(request), organization_id=_organization(request))


@router.get("/evidence/packs/{pack_id}", response_model=EvidencePack)
def evidence_pack_detail(pack_id: str, request: Request) -> EvidencePack:
    return service.get_pack(pack_id, organization_id=_organization(request))


@router.post("/evidence/calibration/sync")
def evidence_calibration_sync(request: Request) -> dict:
    return service.sync_calibration_evidence(_actor(request), organization_id=_organization(request))


@router.post("/projects/{project_id}/evidence/sync", response_model=EvidenceSyncResult)
def project_evidence_sync(project_id: str, request: Request, run_id: str | None = None) -> EvidenceSyncResult:
    return service.sync_project_evidence(project_id, _actor(request), run_id=run_id, organization_id=_organization(request))


@router.get("/projects/{project_id}/evidence-summary", response_model=ProjectEvidenceSummary)
def project_evidence_summary(project_id: str) -> ProjectEvidenceSummary:
    return service.project_evidence_summary(project_id)
