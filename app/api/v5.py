from __future__ import annotations

from fastapi import APIRouter, Query, Request

from app.core.organization_models import (
    DataConnector,
    DataConnectorCreateRequest,
    IngestionEvent,
    IngestionJob,
    IngestionJobCreateRequest,
    IngestionPolicy,
    IngestionPolicyCreateRequest,
    IngestionSummary,
    Organization,
    OrganizationCreateRequest,
    OrganizationMember,
    OrganizationMemberAddRequest,
)
from app.core.models import ResearchProject, ResearchProjectCreate
from app.services.auth import ensure_system_user
from app.services import ingestion, organizations
from app.services.projects import create_project, list_projects


router = APIRouter()


def _actor(request: Request):
    return getattr(request.state, "user", None) or ensure_system_user()


@router.get("/organizations", response_model=list[Organization])
def organization_list(request: Request) -> list[Organization]:
    return organizations.list_organizations(_actor(request))


@router.get("/organizations/current", response_model=Organization)
def organization_current(request: Request) -> Organization:
    return organizations.current_organization(_actor(request), request.headers.get("x-worldpulse-org"))


@router.post("/organizations", response_model=Organization)
def organization_create(payload: OrganizationCreateRequest, request: Request) -> Organization:
    return organizations.create_organization(payload, _actor(request))


@router.get("/organizations/{organization_id}/members", response_model=list[OrganizationMember])
def organization_member_list(organization_id: str, request: Request) -> list[OrganizationMember]:
    return organizations.list_members(organization_id, _actor(request))


@router.post("/organizations/{organization_id}/members", response_model=OrganizationMember)
def organization_member_add(organization_id: str, payload: OrganizationMemberAddRequest, request: Request) -> OrganizationMember:
    return organizations.add_member(organization_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/projects", response_model=list[ResearchProject])
def organization_project_list(organization_id: str, request: Request, limit: int = Query(default=50, ge=1, le=100)) -> list[ResearchProject]:
    organizations.require_organization_role(organization_id, _actor(request), {"owner", "admin", "analyst", "reviewer", "viewer"})
    return list_projects(limit=limit, organization_id=organization_id)


@router.post("/organizations/{organization_id}/projects", response_model=ResearchProject)
def organization_project_create(organization_id: str, payload: ResearchProjectCreate, request: Request) -> ResearchProject:
    organizations.require_organization_role(organization_id, _actor(request), organizations.ORG_WRITE_ROLES)
    return create_project(payload, organization_id=organization_id)


@router.get("/organizations/{organization_id}/ingestion/policies", response_model=list[IngestionPolicy])
def ingestion_policy_list(organization_id: str, request: Request) -> list[IngestionPolicy]:
    return ingestion.list_policies(organization_id, _actor(request))


@router.post("/organizations/{organization_id}/ingestion/policies", response_model=IngestionPolicy)
def ingestion_policy_create(organization_id: str, payload: IngestionPolicyCreateRequest, request: Request) -> IngestionPolicy:
    return ingestion.create_policy(organization_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/ingestion/connectors", response_model=list[DataConnector])
def ingestion_connector_list(organization_id: str, request: Request) -> list[DataConnector]:
    return ingestion.list_connectors(organization_id, _actor(request))


@router.post("/organizations/{organization_id}/ingestion/connectors", response_model=DataConnector)
def ingestion_connector_create(organization_id: str, payload: DataConnectorCreateRequest, request: Request) -> DataConnector:
    return ingestion.create_connector(organization_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/ingestion/jobs", response_model=list[IngestionJob])
def ingestion_job_list(organization_id: str, request: Request, limit: int = Query(default=100, ge=1, le=500)) -> list[IngestionJob]:
    return ingestion.list_jobs(organization_id, _actor(request), limit=limit)


@router.post("/organizations/{organization_id}/ingestion/jobs", response_model=IngestionJob)
def ingestion_job_create(organization_id: str, payload: IngestionJobCreateRequest, request: Request) -> IngestionJob:
    return ingestion.create_job(organization_id, payload, _actor(request))


@router.get("/organizations/{organization_id}/ingestion/jobs/{job_id}", response_model=IngestionJob)
def ingestion_job_detail(organization_id: str, job_id: str, request: Request) -> IngestionJob:
    return ingestion.get_job(organization_id, job_id, _actor(request))


@router.get("/organizations/{organization_id}/ingestion/jobs/{job_id}/events", response_model=list[IngestionEvent])
def ingestion_job_events(organization_id: str, job_id: str, request: Request, after_seq: int = 0) -> list[IngestionEvent]:
    return ingestion.list_events(organization_id, job_id, _actor(request), after_seq=after_seq)


@router.post("/organizations/{organization_id}/ingestion/jobs/{job_id}/execute", response_model=IngestionJob)
def ingestion_job_execute(organization_id: str, job_id: str, request: Request) -> IngestionJob:
    return ingestion.execute_job(organization_id, job_id, _actor(request))


@router.post("/organizations/{organization_id}/ingestion/jobs/{job_id}/cancel", response_model=IngestionJob)
def ingestion_job_cancel(organization_id: str, job_id: str, request: Request) -> IngestionJob:
    return ingestion.cancel_job(organization_id, job_id, _actor(request))


@router.post("/organizations/{organization_id}/ingestion/jobs/{job_id}/retry", response_model=IngestionJob)
def ingestion_job_retry(organization_id: str, job_id: str, request: Request) -> IngestionJob:
    return ingestion.retry_job(organization_id, job_id, _actor(request))


@router.get("/organizations/{organization_id}/ingestion/summary", response_model=IngestionSummary)
def ingestion_governance_summary(organization_id: str, request: Request) -> IngestionSummary:
    return ingestion.ingestion_summary(organization_id, _actor(request))
