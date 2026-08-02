from __future__ import annotations

from fastapi import APIRouter, Request

from app.api.dependencies import current_actor
from app.core.operations_models import OrganizationOperationsSummary, OrganizationQuota, OrganizationQuotaUpdate, PlatformReadiness, WorkerNode
from app.services import operations


router = APIRouter()


def _actor(request: Request):
    return current_actor(request)


@router.get("/platform/readiness", response_model=PlatformReadiness)
def platform_readiness() -> PlatformReadiness:
    return operations.platform_readiness()


@router.get("/workers", response_model=list[WorkerNode])
def worker_list() -> list[WorkerNode]:
    return operations.list_workers()


@router.post("/workers/{worker_id}/drain", response_model=WorkerNode)
def worker_drain(worker_id: str) -> WorkerNode:
    return operations.request_worker_drain(worker_id)


@router.get("/organizations/{organization_id}/operations", response_model=OrganizationOperationsSummary)
def organization_operations(organization_id: str, request: Request) -> OrganizationOperationsSummary:
    return operations.organization_operations(organization_id, _actor(request))


@router.put("/organizations/{organization_id}/quota", response_model=OrganizationQuota)
def organization_quota_update(organization_id: str, payload: OrganizationQuotaUpdate, request: Request) -> OrganizationQuota:
    return operations.update_quota(organization_id, payload, _actor(request))
