from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


WorkerKind = Literal["lifecycle", "ingestion"]
WorkerStatus = Literal["starting", "ready", "busy", "draining", "stopped", "failed", "stale"]


class WorkerNode(BaseModel):
    worker_id: str
    worker_kind: WorkerKind
    status: WorkerStatus
    hostname: str
    process_id: int
    version: str
    started_at: str
    heartbeat_at: str
    lease_expires_at: str
    current_job_id: str | None = None
    jobs_completed: int = 0
    last_error_code: str | None = None
    metadata: dict = Field(default_factory=dict)
    fresh: bool = True


class OrganizationQuotaUpdate(BaseModel):
    max_projects: int = Field(default=100, ge=1, le=100_000)
    max_active_runs: int = Field(default=10, ge=1, le=10_000)
    max_ingestion_jobs_per_day: int = Field(default=500, ge=1, le=1_000_000)
    max_evidence_snapshots: int = Field(default=100_000, ge=1, le=10_000_000)
    max_source_documents: int = Field(default=500, ge=1, le=1_000_000)
    max_document_bytes: int = Field(default=5_368_709_120, ge=1_024, le=1_099_511_627_776)


class OrganizationQuota(OrganizationQuotaUpdate):
    organization_id: str
    updated_by_user_id: str | None = None
    updated_at: str


class OrganizationUsage(BaseModel):
    organization_id: str
    projects: int
    active_runs: int
    ingestion_jobs_today: int
    evidence_snapshots: int
    source_documents: int = 0
    document_bytes: int = 0
    generated_at: str


class PlatformReadiness(BaseModel):
    status: Literal["ready", "degraded", "not_ready"]
    database_backend: Literal["sqlite", "postgresql"]
    schema_ok: bool
    rule_pack_ok: bool
    worker_requirement_enabled: bool
    worker_requirement_met: bool
    lifecycle_workers_fresh: int
    ingestion_workers_fresh: int
    queued_runs: int
    queued_ingestion_jobs: int
    queued_document_jobs: int = 0
    queued_monitoring_polls: int = 0
    queued_webhook_deliveries: int = 0
    continuous_intelligence_enabled: bool = False
    blob_storage_ok: bool = True
    checked_at: str
    reasons: list[str] = Field(default_factory=list)


class OrganizationOperationsSummary(BaseModel):
    organization_id: str
    quota: OrganizationQuota
    usage: OrganizationUsage
    workers: list[WorkerNode]
    readiness: PlatformReadiness
    continuous_intelligence: dict = Field(default_factory=dict)
    generated_at: str
