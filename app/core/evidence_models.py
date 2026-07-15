from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


EvidenceSourceStatus = Literal["active", "degraded", "retired"]
EvidenceRelation = Literal["supports", "contradicts", "context"]


class EvidenceSourceCreate(BaseModel):
    source_type: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    locator: str = Field(min_length=1, max_length=1000)
    publisher: str = Field(default="", max_length=200)
    trust_tier: str = Field(default="internal", max_length=40)
    metadata: dict = Field(default_factory=dict)


class EvidenceSource(BaseModel):
    source_id: str
    source_type: str
    name: str
    locator: str
    publisher: str
    status: EvidenceSourceStatus
    trust_tier: str
    metadata: dict = Field(default_factory=dict)
    created_by_user_id: str | None = None
    created_at: str
    retired_at: str | None = None


class EvidenceSnapshotCreate(BaseModel):
    source_id: str = Field(min_length=3, max_length=80)
    project_id: str | None = Field(default=None, max_length=80)
    external_ref: str = Field(min_length=1, max_length=500)
    title: str = Field(min_length=1, max_length=300)
    category: str = Field(min_length=1, max_length=80)
    content: dict
    content_text: str = Field(default="", max_length=200_000)
    observed_at: str
    cutoff_at: str


class EvidenceSnapshot(BaseModel):
    snapshot_id: str
    source_id: str
    project_id: str | None = None
    external_ref: str
    title: str
    category: str
    content: dict
    content_text: str
    observed_at: str
    cutoff_at: str
    captured_at: str
    content_hash: str
    created_by_user_id: str | None = None
    integrity_status: Literal["verified", "failed"] = "verified"


class EvidenceSnapshotSummary(BaseModel):
    snapshot_id: str
    source_id: str
    project_id: str | None = None
    external_ref: str
    title: str
    category: str
    observed_at: str
    cutoff_at: str
    captured_at: str
    content_hash: str
    created_by_user_id: str | None = None
    integrity_status: Literal["verified", "failed"] = "verified"


class EvidenceClaimCreate(BaseModel):
    project_id: str | None = Field(default=None, max_length=80)
    run_id: str | None = Field(default=None, max_length=80)
    statement: str = Field(min_length=1, max_length=10_000)
    claim_type: str = Field(default="finding", max_length=80)
    confidence: float = Field(default=0.72, ge=0, le=1)
    valid_from: str | None = None
    valid_to: str | None = None
    cutoff_at: str
    snapshot_ids: list[str] = Field(default_factory=list, max_length=100)
    relation: EvidenceRelation = "supports"


class EvidenceClaim(BaseModel):
    claim_id: str
    project_id: str | None = None
    run_id: str | None = None
    statement: str
    claim_type: str
    confidence: float
    valid_from: str | None = None
    valid_to: str | None = None
    cutoff_at: str
    claim_hash: str
    created_by_user_id: str | None = None
    created_at: str
    links: list[dict] = Field(default_factory=list)


class EvidencePackCreate(BaseModel):
    project_id: str | None = Field(default=None, max_length=80)
    run_id: str | None = Field(default=None, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    cutoff_at: str
    snapshot_ids: list[str] = Field(default_factory=list, max_length=500)
    claim_ids: list[str] = Field(default_factory=list, max_length=500)


class EvidencePack(BaseModel):
    pack_id: str
    project_id: str | None = None
    run_id: str | None = None
    name: str
    cutoff_at: str
    manifest: dict
    manifest_hash: str
    created_by_user_id: str | None = None
    created_at: str


class EvidenceSearchResult(BaseModel):
    query: str
    cutoff_at: str | None = None
    total: int
    snapshots: list[EvidenceSnapshotSummary] = Field(default_factory=list)
    claims: list[EvidenceClaim] = Field(default_factory=list)


class ProjectEvidenceSummary(BaseModel):
    project_id: str
    source_count: int
    snapshot_count: int
    claim_count: int
    linked_claim_count: int
    pack_count: int
    coverage: float
    integrity_status: Literal["verified", "failed", "empty"]
    cutoff_safe: bool
    latest_cutoff_at: str | None = None
    latest_pack: EvidencePack | None = None
    sources: list[EvidenceSource] = Field(default_factory=list)
    recent_snapshots: list[EvidenceSnapshotSummary] = Field(default_factory=list)
    recent_claims: list[EvidenceClaim] = Field(default_factory=list)
    generated_at: str


class EvidenceSyncResult(BaseModel):
    project_id: str
    run_id: str | None = None
    sources_created: int = 0
    snapshots_created: int = 0
    claims_created: int = 0
    links_created: int = 0
    summary: ProjectEvidenceSummary
