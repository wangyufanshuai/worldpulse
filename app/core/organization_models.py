from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


OrganizationRole = Literal["owner", "admin", "analyst", "reviewer", "viewer"]
IngestionJobStatus = Literal["queued", "running", "cancelling", "cancelled", "failed", "completed"]


class OrganizationCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")


class Organization(BaseModel):
    organization_id: str
    slug: str
    name: str
    status: str
    member_role: OrganizationRole | None = None
    created_by_user_id: str | None = None
    created_at: str
    updated_at: str


class OrganizationMemberAddRequest(BaseModel):
    user_id: str = Field(min_length=3, max_length=80)
    role: OrganizationRole


class OrganizationMember(BaseModel):
    organization_id: str
    user_id: str
    username: str
    display_name: str
    role: OrganizationRole
    status: str
    added_by_user_id: str | None = None
    created_at: str


class IngestionPolicyCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    version: str = Field(min_length=1, max_length=80)
    allowed_connector_types: list[str] = Field(default_factory=lambda: ["manual_json"], min_length=1, max_length=10)
    allowed_categories: list[str] = Field(default_factory=lambda: ["energy", "food", "trade", "finance", "sanctions", "conflict", "climate", "other"], min_length=1, max_length=100)
    max_records: int = Field(default=100, ge=1, le=10_000)
    max_bytes: int = Field(default=1_000_000, ge=1_024, le=50_000_000)
    require_license_metadata: bool = True
    require_cutoff: bool = True
    retention_days: int = Field(default=3650, ge=1, le=36_500)


class IngestionPolicy(BaseModel):
    policy_id: str
    organization_id: str
    name: str
    version: str
    status: str
    allowed_connector_types: list[str]
    allowed_categories: list[str]
    max_records: int
    max_bytes: int
    require_license_metadata: bool
    require_cutoff: bool
    retention_days: int
    manifest: dict
    manifest_hash: str
    created_by_user_id: str | None = None
    created_at: str
    retired_at: str | None = None


class DataConnectorCreateRequest(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    connector_type: Literal["manual_json"] = "manual_json"
    source_locator: str = Field(min_length=3, max_length=1000)
    policy_id: str | None = Field(default=None, max_length=80)
    config: dict = Field(default_factory=dict)


class DataConnector(BaseModel):
    connector_id: str
    organization_id: str
    policy_id: str
    name: str
    connector_type: str
    source_locator: str
    config: dict
    config_hash: str
    status: str
    created_by_user_id: str | None = None
    created_at: str
    retired_at: str | None = None


class IngestionRecordInput(BaseModel):
    external_ref: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    content: dict
    content_text: str = Field(default="", max_length=200_000)
    observed_at: str
    cutoff_at: str


class IngestionJobCreateRequest(BaseModel):
    connector_id: str = Field(min_length=3, max_length=80)
    project_id: str | None = Field(default=None, max_length=80)
    records: list[IngestionRecordInput] = Field(min_length=1, max_length=10_000)
    idempotency_key: str | None = Field(default=None, max_length=160)


class IngestionJob(BaseModel):
    job_id: str
    organization_id: str
    connector_id: str
    policy_id: str
    project_id: str | None = None
    parent_job_id: str | None = None
    status: IngestionJobStatus
    request_hash: str
    idempotency_key: str | None = None
    record_count: int
    accepted_count: int
    rejected_count: int
    manifest: dict = Field(default_factory=dict)
    manifest_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_by_user_id: str | None = None
    worker_id: str | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None


class IngestionEvent(BaseModel):
    job_id: str
    seq: int
    event_type: str
    title: str
    detail: str
    payload: dict = Field(default_factory=dict)
    created_at: str


class IngestionSummary(BaseModel):
    organization_id: str
    connector_count: int
    active_policy_count: int
    queued_jobs: int
    running_jobs: int
    failed_jobs: int
    completed_jobs: int
    accepted_records: int
    rejected_records: int
    latest_jobs: list[IngestionJob] = Field(default_factory=list)
    connectors: list[DataConnector] = Field(default_factory=list)
    policies: list[IngestionPolicy] = Field(default_factory=list)
    generated_at: str
