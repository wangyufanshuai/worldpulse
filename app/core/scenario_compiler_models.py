from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


DocumentMediaType = Literal["application/pdf", "text/plain", "text/markdown", "text/csv"]
DocumentStatus = Literal["uploaded", "extracting", "ready", "failed", "retired"]
ExtractionJobStatus = Literal["queued", "running", "cancelling", "cancelled", "failed", "completed"]
CandidateType = Literal["scenario_preset", "country", "supply_chain", "policy_action", "relationship", "event_date"]
CandidateDecisionType = Literal["accepted", "rejected"]
ScenarioDraftStatus = Literal["draft", "submitted", "approved", "revision_requested", "rejected", "superseded"]
ScenarioReviewDecision = Literal["approve", "request_revision", "reject"]


class SourceDocument(BaseModel):
    document_id: str
    organization_id: str
    project_id: str
    original_filename: str
    media_type: DocumentMediaType
    size_bytes: int
    content_hash: str
    title: str
    category: str
    publisher: str
    license_name: str
    license_url: str = ""
    observed_at: str
    cutoff_at: str
    status: DocumentStatus
    created_by_user_id: str | None = None
    created_at: str


class DocumentUploadResult(BaseModel):
    document: SourceDocument
    deduplicated: bool = False


class DocumentExtractionJob(BaseModel):
    job_id: str
    organization_id: str
    project_id: str
    document_id: str
    parent_job_id: str | None = None
    status: ExtractionJobStatus
    request_hash: str
    extractor_version: str
    provider: str
    worker_id: str | None = None
    attempt_count: int = 0
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_by_user_id: str | None = None
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None


class DocumentExtractionEvent(BaseModel):
    job_id: str
    seq: int
    event_type: str
    title: str
    detail: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class DocumentExtraction(BaseModel):
    extraction_id: str
    job_id: str
    document_id: str
    extractor_version: str
    chunk_manifest: list[dict[str, Any]]
    snapshot_ids: list[str]
    provider_audit: dict[str, Any] = Field(default_factory=dict)
    extraction_hash: str
    total_chars: int
    total_chunks: int
    created_at: str


class ScenarioCandidateDecision(BaseModel):
    decision_id: str
    candidate_id: str
    organization_id: str
    project_id: str
    decision: CandidateDecisionType
    normalized_value: str | None = None
    comment: str = ""
    actor_user_id: str
    decision_hash: str
    created_at: str


class ScenarioCandidate(BaseModel):
    candidate_id: str
    extraction_id: str
    organization_id: str
    project_id: str
    candidate_type: CandidateType
    canonical_value: str
    display_value: str
    relation: dict[str, Any] = Field(default_factory=dict)
    snapshot_id: str
    locator: dict[str, Any]
    excerpt: str
    confidence: float
    extractor_source: str
    validation_status: Literal["valid", "invalid"]
    validation_reason: str | None = None
    candidate_hash: str
    created_at: str
    latest_decision: ScenarioCandidateDecision | None = None


class ScenarioCandidateDecisionRequest(BaseModel):
    decision: CandidateDecisionType
    normalized_value: str | None = Field(default=None, max_length=160)
    comment: str = Field(default="", max_length=2000)


class ScenarioDraftCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=200)
    candidate_ids: list[str] = Field(min_length=1, max_length=500)
    duration_days: int | None = Field(default=None, ge=7, le=90)
    intensity: float | None = Field(default=None, ge=0.05, le=1)
    propagation: float | None = Field(default=None, ge=0.05, le=0.9)
    assumption_reason: str = Field(default="", max_length=3000)


class ScenarioDraftReviewRequest(BaseModel):
    decision: ScenarioReviewDecision
    comment: str = Field(default="", max_length=3000)


class ScenarioDraftRunRequest(BaseModel):
    engine_mode: Literal["deterministic", "hybrid", "negotiation"] = "deterministic"
    seed: int = 42
    max_attempts: int = Field(default=3, ge=1, le=10)


class ScenarioDraftReview(BaseModel):
    review_id: str
    draft_id: str
    decision: ScenarioReviewDecision
    comment: str
    reviewer_user_id: str
    review_hash: str
    created_at: str


class ScenarioCompileManifest(BaseModel):
    schema_version: str = "scenario-compile-manifest.v1"
    compiler_version: str
    scenario: dict[str, Any]
    manual_assumptions: dict[str, Any]
    candidate_hashes: list[dict[str, str]]
    decision_hashes: list[dict[str, str]]
    extraction_hashes: list[dict[str, str]]
    evidence_pack_hash: str | None = None
    manifest_hash: str


class ScenarioDraft(BaseModel):
    draft_id: str
    organization_id: str
    project_id: str
    parent_draft_id: str | None = None
    version: int
    status: ScenarioDraftStatus
    name: str
    scenario: dict[str, Any]
    manual_assumptions: dict[str, Any]
    compiler_version: str
    evidence_pack_id: str | None = None
    evidence_pack_hash: str | None = None
    draft_hash: str
    created_by_user_id: str
    submitted_by_user_id: str | None = None
    approved_by_user_id: str | None = None
    review_case_id: str | None = None
    created_at: str
    submitted_at: str | None = None
    approved_at: str | None = None
    closed_at: str | None = None
    candidate_ids: list[str] = Field(default_factory=list)
    reviews: list[ScenarioDraftReview] = Field(default_factory=list)
