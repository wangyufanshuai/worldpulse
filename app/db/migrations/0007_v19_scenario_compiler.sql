ALTER TABLE run_jobs ADD COLUMN scenario_draft_id TEXT;
ALTER TABLE run_jobs ADD COLUMN scenario_draft_hash TEXT;
ALTER TABLE run_jobs ADD COLUMN scenario_evidence_pack_hash TEXT;

ALTER TABLE organization_quotas ADD COLUMN max_source_documents INTEGER NOT NULL DEFAULT 500;
ALTER TABLE organization_quotas ADD COLUMN max_document_bytes INTEGER NOT NULL DEFAULT 5368709120;

CREATE TABLE source_documents (
    document_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    original_filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    content_hash TEXT NOT NULL,
    blob_key TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    publisher TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(organization_id, project_id, content_hash),
    CHECK(media_type IN ('application/pdf','text/plain','text/markdown','text/csv')),
    CHECK(size_bytes > 0),
    CHECK(status IN ('uploaded','extracting','ready','failed','retired'))
);

CREATE TABLE document_extraction_jobs (
    job_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    parent_job_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    request_hash TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT 'disabled',
    worker_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    warning_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_message TEXT,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    cancel_requested_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(document_id) REFERENCES source_documents(document_id),
    FOREIGN KEY(parent_job_id) REFERENCES document_extraction_jobs(job_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(document_id, request_hash),
    CHECK(status IN ('queued','running','cancelling','cancelled','failed','completed'))
);

CREATE TABLE document_extraction_event_counters (
    job_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(job_id) REFERENCES document_extraction_jobs(job_id)
);

CREATE TABLE document_extraction_events (
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id, seq),
    FOREIGN KEY(job_id) REFERENCES document_extraction_jobs(job_id)
);

CREATE TABLE document_extractions (
    extraction_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    document_id TEXT NOT NULL,
    extractor_version TEXT NOT NULL,
    chunk_manifest_json TEXT NOT NULL,
    snapshot_ids_json TEXT NOT NULL,
    provider_audit_json TEXT NOT NULL DEFAULT '{}',
    extraction_hash TEXT NOT NULL UNIQUE,
    total_chars INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES document_extraction_jobs(job_id),
    FOREIGN KEY(document_id) REFERENCES source_documents(document_id)
);

CREATE TABLE scenario_candidates (
    candidate_id TEXT PRIMARY KEY,
    extraction_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    candidate_type TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    display_value TEXT NOT NULL,
    relation_json TEXT NOT NULL DEFAULT '{}',
    snapshot_id TEXT NOT NULL,
    locator_json TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    confidence REAL NOT NULL,
    extractor_source TEXT NOT NULL,
    validation_status TEXT NOT NULL DEFAULT 'valid',
    validation_reason TEXT,
    candidate_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(extraction_id) REFERENCES document_extractions(extraction_id),
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(snapshot_id) REFERENCES evidence_snapshots(snapshot_id),
    CHECK(candidate_type IN ('scenario_preset','country','supply_chain','policy_action','relationship','event_date')),
    CHECK(validation_status IN ('valid','invalid')),
    CHECK(confidence >= 0 AND confidence <= 1)
);

CREATE TABLE scenario_candidate_decisions (
    decision_id TEXT PRIMARY KEY,
    candidate_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    normalized_value TEXT,
    comment TEXT NOT NULL DEFAULT '',
    actor_user_id TEXT NOT NULL,
    decision_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(candidate_id) REFERENCES scenario_candidates(candidate_id),
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(actor_user_id) REFERENCES users(user_id),
    CHECK(decision IN ('accepted','rejected'))
);

CREATE TABLE scenario_drafts (
    draft_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    parent_draft_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'draft',
    name TEXT NOT NULL,
    scenario_json TEXT NOT NULL,
    manual_assumptions_json TEXT NOT NULL DEFAULT '{}',
    compiler_version TEXT NOT NULL,
    evidence_pack_id TEXT,
    evidence_pack_hash TEXT,
    draft_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT NOT NULL,
    submitted_by_user_id TEXT,
    approved_by_user_id TEXT,
    review_case_id TEXT,
    created_at TEXT NOT NULL,
    submitted_at TEXT,
    approved_at TEXT,
    closed_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(parent_draft_id) REFERENCES scenario_drafts(draft_id),
    FOREIGN KEY(evidence_pack_id) REFERENCES evidence_packs(pack_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    FOREIGN KEY(submitted_by_user_id) REFERENCES users(user_id),
    FOREIGN KEY(approved_by_user_id) REFERENCES users(user_id),
    FOREIGN KEY(review_case_id) REFERENCES review_cases(review_id),
    CHECK(status IN ('draft','submitted','approved','revision_requested','rejected','superseded'))
);

CREATE TABLE scenario_draft_items (
    draft_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    decision_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    candidate_hash TEXT NOT NULL,
    decision_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(draft_id, candidate_id),
    FOREIGN KEY(draft_id) REFERENCES scenario_drafts(draft_id),
    FOREIGN KEY(candidate_id) REFERENCES scenario_candidates(candidate_id),
    FOREIGN KEY(decision_id) REFERENCES scenario_candidate_decisions(decision_id)
);

CREATE TABLE scenario_draft_reviews (
    review_id TEXT PRIMARY KEY,
    draft_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    reviewer_user_id TEXT NOT NULL,
    review_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(draft_id) REFERENCES scenario_drafts(draft_id),
    FOREIGN KEY(reviewer_user_id) REFERENCES users(user_id),
    CHECK(decision IN ('approve','request_revision','reject'))
);

CREATE INDEX idx_source_documents_project ON source_documents(organization_id, project_id, created_at);
CREATE INDEX idx_document_jobs_claim ON document_extraction_jobs(status, created_at, job_id);
CREATE INDEX idx_document_jobs_project ON document_extraction_jobs(organization_id, project_id, created_at);
CREATE INDEX idx_document_events_job ON document_extraction_events(job_id, seq);
CREATE INDEX idx_candidates_project ON scenario_candidates(organization_id, project_id, candidate_type, created_at);
CREATE INDEX idx_candidate_decisions_candidate ON scenario_candidate_decisions(candidate_id, created_at);
CREATE INDEX idx_scenario_drafts_project ON scenario_drafts(organization_id, project_id, created_at);
CREATE INDEX idx_scenario_reviews_draft ON scenario_draft_reviews(draft_id, created_at);
