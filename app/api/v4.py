from __future__ import annotations

from fastapi import APIRouter, Query, Request

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
from app.services.auth import ensure_system_user
from app.services import evidence_registry


router = APIRouter()


def _actor(request: Request):
    return getattr(request.state, "user", None) or ensure_system_user()


@router.get("/evidence/sources", response_model=list[EvidenceSource])
def evidence_sources(status: str | None = None, source_type: str | None = None) -> list[EvidenceSource]:
    return evidence_registry.list_sources(status=status, source_type=source_type)


@router.post("/evidence/sources", response_model=EvidenceSource)
def evidence_source_create(payload: EvidenceSourceCreate, request: Request) -> EvidenceSource:
    return evidence_registry.create_source(payload, _actor(request))


@router.get("/evidence/sources/{source_id}", response_model=EvidenceSource)
def evidence_source_detail(source_id: str) -> EvidenceSource:
    return evidence_registry.get_source(source_id)


@router.post("/evidence/snapshots", response_model=EvidenceSnapshot)
def evidence_snapshot_create(payload: EvidenceSnapshotCreate, request: Request) -> EvidenceSnapshot:
    return evidence_registry.create_snapshot(payload, _actor(request))


@router.get("/evidence/snapshots/{snapshot_id}", response_model=EvidenceSnapshot)
def evidence_snapshot_detail(snapshot_id: str) -> EvidenceSnapshot:
    return evidence_registry.get_snapshot(snapshot_id)


@router.post("/evidence/claims", response_model=EvidenceClaim)
def evidence_claim_create(payload: EvidenceClaimCreate, request: Request) -> EvidenceClaim:
    return evidence_registry.create_claim(payload, _actor(request))


@router.get("/evidence/claims/{claim_id}", response_model=EvidenceClaim)
def evidence_claim_detail(claim_id: str) -> EvidenceClaim:
    return evidence_registry.get_claim(claim_id)


@router.get("/evidence/search", response_model=EvidenceSearchResult)
def evidence_search(
    query: str = "", project_id: str | None = None, category: str | None = None,
    cutoff_at: str | None = None, limit: int = Query(default=50, ge=1, le=200),
) -> EvidenceSearchResult:
    return evidence_registry.search_evidence(
        query=query, project_id=project_id, category=category, cutoff_at=cutoff_at, limit=limit,
    )


@router.post("/evidence/packs", response_model=EvidencePack)
def evidence_pack_create(payload: EvidencePackCreate, request: Request) -> EvidencePack:
    return evidence_registry.create_pack(payload, _actor(request))


@router.get("/evidence/packs/{pack_id}", response_model=EvidencePack)
def evidence_pack_detail(pack_id: str) -> EvidencePack:
    return evidence_registry.get_pack(pack_id)


@router.post("/evidence/calibration/sync")
def evidence_calibration_sync(request: Request) -> dict:
    return evidence_registry.sync_calibration_evidence(_actor(request))


@router.post("/projects/{project_id}/evidence/sync", response_model=EvidenceSyncResult)
def project_evidence_sync(project_id: str, request: Request, run_id: str | None = None) -> EvidenceSyncResult:
    return evidence_registry.sync_project_evidence(project_id, _actor(request), run_id=run_id)


@router.get("/projects/{project_id}/evidence-summary", response_model=ProjectEvidenceSummary)
def project_evidence_summary(project_id: str) -> ProjectEvidenceSummary:
    return evidence_registry.project_evidence_summary(project_id)
