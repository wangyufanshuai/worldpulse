from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field

EvaluationMode = Literal["deterministic", "hybrid", "negotiation"]
BatchStatus = Literal["queued", "running", "pausing", "paused", "cancelling", "cancelled", "failed", "completed"]
BenchmarkCurationProfile = Literal["pilot", "wave", "release"]

class EvaluationRuntimeProfile(BaseModel):
    provider: Literal["mock", "deepseek", "siliconflow"] = "mock"
    model: str = "mock-deterministic-v1"
    fallback_mode: Literal["mock", "skip"] = "mock"
    agent_runtime_version: str = "agent-runtime.v1"
    negotiation_runtime_version: str = "negotiation-runtime.v1"
    agent_pack_builder_version: str = "agent-pack.v1"
    action_adapter_version: str = "action-adapter.v1"
    max_calls: int = Field(default=36, ge=1, le=200)
    token_budget: int = Field(default=60000, ge=100, le=500000)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    seeds: list[int] = Field(default_factory=lambda: [11, 29, 47])

class EvaluationSuiteManifest(BaseModel):
    suite_id: str
    schema_version: str
    version: str
    status: Literal["active", "retired"]
    manifest: dict = Field(default_factory=dict)
    manifest_hash: str
    case_count: int = 0
    created_at: str

class EvaluationCase(BaseModel):
    case_id: str
    suite_id: str
    version: str
    domain: str
    title: str
    input: dict
    qualitative_expectations: dict = Field(default_factory=dict)
    safety_probes: dict = Field(default_factory=dict)
    evidence: list[dict] = Field(default_factory=list)
    case_hash: str
    is_active: bool = True

class EvaluationBatch(BaseModel):
    batch_id: str
    organization_id: str
    project_id: str | None = None
    scenario_draft_id: str | None = None
    scenario_draft_hash: str | None = None
    evidence_pack_hash: str | None = None
    suite_id: str
    suite_hash: str
    rule_pack_id: str | None = None
    rule_pack_hash: str | None = None
    runtime_profile: dict = Field(default_factory=dict)
    runtime_profile_hash: str
    provider_mode: str
    source_type: str
    status: BatchStatus
    parent_batch_id: str | None = None
    total_members: int = 0
    completed_members: int = 0
    failed_members: int = 0
    safety_status: str = "pending"
    quality_status: str = "pending"
    metrics: dict = Field(default_factory=dict)
    report_hash: str | None = None
    created_by_user_id: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    evaluation_track: str = "engineering_standard"
    benchmark_suite_id: str | None = None
    benchmark_suite_hash: str | None = None
    label_pack_id: str | None = None
    label_pack_hash: str | None = None
    gate_manifest_hash: str | None = None
    root_batch_id: str | None = None
    coordinator_worker_id: str | None = None
    coordinator_lease_expires_at: str | None = None

class EvaluationMember(BaseModel):
    member_id: str
    batch_id: str
    case_id: str
    engine_mode: EvaluationMode
    seed: int
    run_id: str | None = None
    status: str
    baseline_result_hash: str | None = None
    result_hash: str | None = None
    metrics: dict = Field(default_factory=dict)
    artifact_refs: list[str] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None
    input_hash: str | None = None
    expected_baseline_hash: str | None = None
    verification_status: str = "pending"
    verification_hash: str | None = None

class EvaluationMetric(BaseModel):
    metric_id: str
    batch_id: str
    member_id: str | None = None
    scope: str
    metric_key: str
    value: dict | float | int | str
    passed: bool | None = None
    metric_hash: str
    created_at: str

class EvaluationSafetyGate(BaseModel):
    status: Literal["pending", "passed", "failed", "not_applicable"]
    checks: dict = Field(default_factory=dict)

class EvaluationModeScorecard(BaseModel):
    mode: EvaluationMode
    member_count: int = 0
    completed_count: int = 0
    metrics: dict = Field(default_factory=dict)

class ModeEligibility(BaseModel):
    deterministic: bool = True
    hybrid: bool = False
    negotiation: bool = False
    reasons: dict = Field(default_factory=dict)

class EvaluationReport(BaseModel):
    batch: EvaluationBatch
    safety_gate: EvaluationSafetyGate
    scorecards: list[EvaluationModeScorecard] = Field(default_factory=list)
    mode_eligibility: ModeEligibility = Field(default_factory=ModeEligibility)
    report_hash: str

class EvaluationBatchCreateRequest(BaseModel):
    provider: Literal["mock", "deepseek", "siliconflow"] = "mock"
    case_ids: list[str] = Field(default_factory=list, max_length=12)

class EvaluationControlResponse(BaseModel):
    batch: EvaluationBatch

class HistoricalEvidenceItem(BaseModel):
    evidence_id: str
    case_id: str
    evidence_role: Literal["input", "outcome"]
    publisher: str
    license_name: str
    source_url: str
    observed_at: str
    cutoff_at: str
    blob_sha256: str
    locator: dict = Field(default_factory=dict)
    evidence_hash: str

class HistoricalBenchmarkCase(BaseModel):
    case_id: str
    suite_id: str
    version: str
    domain: str
    split: Literal["development", "blind"]
    title: str
    cutoff_at: str
    observation_window_days: int
    scenario: dict
    evidence_manifest: dict = Field(default_factory=dict)
    labels: dict | None = None
    label_confidence: float
    case_hash: str
    evidence: list[HistoricalEvidenceItem] = Field(default_factory=list)

class HistoricalBenchmarkSuite(BaseModel):
    suite_id: str
    version: str
    status: Literal["draft", "active", "retired"]
    manifest: dict = Field(default_factory=dict)
    manifest_hash: str
    development_count: int
    blind_count: int
    created_at: str
    activated_at: str | None = None

class SealedLabelPack(BaseModel):
    label_pack_id: str
    organization_id: str
    suite_id: str
    status: str
    blob_sha256: str
    manifest_hash: str
    signature: str
    signer_key_id: str
    encryption_key_id: str
    evidence_hash: str
    case_count: int
    imported_by_user_id: str
    bound_root_batch_id: str | None = None
    comparison_started_at: str | None = None
    consumed_at: str | None = None
    created_at: str
    approvals: list[dict] = Field(default_factory=list)

class LabelPackReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    comment: str = Field(default="", max_length=2000)

class LabelPackImportRequest(BaseModel):
    suite_id: str
    ciphertext_b64: str = Field(min_length=20)
    nonce_b64: str = Field(min_length=8)
    manifest_hash: str = Field(min_length=64, max_length=64)
    signature: str = Field(min_length=20)
    signer_key_id: str = Field(min_length=1, max_length=80)
    encryption_key_id: str = Field(min_length=1, max_length=80)
    evidence_hash: str = Field(min_length=64, max_length=64)
    case_count: int = Field(default=30, ge=1, le=120)

class EvaluationGateManifest(BaseModel):
    gate_manifest_id: str
    version: str
    status: str
    manifest: dict
    manifest_hash: str
    created_at: str

class EvaluationVerificationResult(BaseModel):
    verification_id: str
    batch_id: str
    member_id: str | None = None
    check_key: str
    status: Literal["passed", "failed", "not_applicable"]
    observed: dict = Field(default_factory=dict)
    evidence_artifact_ids: list[str] = Field(default_factory=list)
    verifier_version: str
    verification_hash: str
    created_at: str

class HistoricalEvaluationCreateRequest(BaseModel):
    suite_id: str = "historical-benchmark.v1"
    label_pack_id: str
    provider: Literal["mock"] = "mock"

class HistoricalBenchmarkReport(BaseModel):
    batch: EvaluationBatch
    suite: HistoricalBenchmarkSuite
    verification: list[EvaluationVerificationResult]
    aggregate_metrics: dict = Field(default_factory=dict)
    blind_labels_redacted: bool = True
    report_hash: str

class BenchmarkPreflightReport(BaseModel):
    status: Literal["passed", "failed"]
    profile: BenchmarkCurationProfile
    case_count: int
    domain_counts: dict[str, int] = Field(default_factory=dict)
    blind_count: int = 0
    publisher_counts: dict[str, int] = Field(default_factory=dict)
    checks: dict = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)
    report_hash: str

class BenchmarkSourceStatus(BaseModel):
    status: Literal["complete", "incomplete", "failed"]
    acquisition_lock_hash_valid: bool
    entry_count: int
    verified_count: int
    missing_count: int
    invalid_count: int
    publisher_counts: dict[str, int] = Field(default_factory=dict)
    domain_publisher_counts: dict[str, dict[str, int]] = Field(default_factory=dict)
    missing_evidence_ids: list[str] = Field(default_factory=list)
    invalid_evidence_ids: list[str] = Field(default_factory=list)
    license_error_evidence_ids: list[str] = Field(default_factory=list)
    hash_error_evidence_ids: list[str] = Field(default_factory=list)
    concentration_warnings: list[str] = Field(default_factory=list)
    status_hash: str

class BenchmarkRightsReview(BaseModel):
    decision: Literal["approved"]
    reviewed_by: str
    reviewed_at: str
    scope: Literal["local_archive_and_evaluation"]
    decision_basis: str
    publisher: str
    source_url: str
    license_name: str
    license_url: str
    review_hash: str

class AgentOutcomeObservation(BaseModel):
    engine_mode: EvaluationMode
    score: float | None = None
    allowed_action_recall: float | None = None
    forbidden_action_pass: float | None = None
    commitment_pattern_match: float | None = None
    actual_action_types: list[str] = Field(default_factory=list)
    active_commitment_types: list[str] = Field(default_factory=list)
    verifier_version: str = "agent-outcome-observation.v1"

class ReleaseEvidenceManifest(BaseModel):
    version: str = "release-evidence-manifest.v1"
    suite_hash: str
    source_plan_hash: str
    acquisition_lock_hash: str
    label_pack_hash: str
    gate_manifest_hash: str
    rule_pack_hash: str
    runtime_profile_hashes: list[str] = Field(default_factory=list)
    batch_hashes: list[str] = Field(default_factory=list)
    member_hashes: list[str] = Field(default_factory=list)
    artifact_hashes: list[str] = Field(default_factory=list)
    verification_hashes: list[str] = Field(default_factory=list)
    report_hashes: list[str] = Field(default_factory=list)
    manifest_hash: str
