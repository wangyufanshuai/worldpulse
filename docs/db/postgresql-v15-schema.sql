-- WorldPulse PostgreSQL schema export
-- Generated from the canonical numbered migrations; apply in version order.
CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL);

-- 0001_v12_baseline / sha256:028e4893b4c2a4c71c90211405be4d0b6fa1042c7a88a7741a0f4aa0e1dda3fc
CREATE TABLE research_projects (
    project_id TEXT PRIMARY KEY, title TEXT NOT NULL, question TEXT NOT NULL, region TEXT NOT NULL,
    asset_scope TEXT NOT NULL, event_window_days INTEGER NOT NULL, event_types TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'research', scenario_config TEXT NOT NULL DEFAULT '{}',
    status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE TABLE research_runs (
    run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL,
    completed_at TEXT, summary TEXT NOT NULL, data_snapshot TEXT NOT NULL, risk_snapshot TEXT NOT NULL,
    event_snapshot TEXT NOT NULL, simulation_snapshot TEXT NOT NULL, backtest_snapshot TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
);
CREATE TABLE causal_graph_snapshots (
    graph_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, generated_at TEXT NOT NULL,
    nodes TEXT NOT NULL, edges TEXT NOT NULL, confidence DOUBLE PRECISION NOT NULL, evidence_sources TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id), FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
);
CREATE TABLE ai_reports (
    report_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, run_id TEXT NOT NULL, generated_at TEXT NOT NULL,
    mode TEXT NOT NULL, title TEXT NOT NULL, summary TEXT NOT NULL, key_findings TEXT NOT NULL,
    evidence TEXT NOT NULL, uncertainties TEXT NOT NULL, watch_signals TEXT NOT NULL,
    scenario_suggestions TEXT NOT NULL, citations TEXT NOT NULL DEFAULT '[]', markdown TEXT NOT NULL,
    disclaimer TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
);
CREATE TABLE chat_messages (
    message_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
    created_at TEXT NOT NULL, mode TEXT NOT NULL, FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
);
CREATE TABLE run_jobs (
    run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, engine_mode TEXT NOT NULL, status TEXT NOT NULL,
    current_phase TEXT NOT NULL, progress DOUBLE PRECISION NOT NULL DEFAULT 0, seed INTEGER, parent_run_id TEXT,
    scenario_json TEXT NOT NULL, result_run_id TEXT, error_code TEXT, error_message TEXT, created_at TEXT NOT NULL,
    started_at TEXT, updated_at TEXT NOT NULL, completed_at TEXT, cancel_requested_at TEXT, pause_requested_at TEXT,
    worker_id TEXT, lease_expires_at TEXT, attempt_count INTEGER NOT NULL DEFAULT 0, current_attempt_id TEXT,
    max_attempts INTEGER NOT NULL DEFAULT 3, next_attempt_at TEXT, terminal_reason TEXT, request_hash TEXT,
    idempotency_key TEXT, FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
);
CREATE TABLE run_events (
    run_id TEXT NOT NULL, seq INTEGER NOT NULL, event_type TEXT NOT NULL, phase TEXT NOT NULL, tick INTEGER,
    title TEXT NOT NULL, detail TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL,
    PRIMARY KEY(run_id, seq), FOREIGN KEY(run_id) REFERENCES run_jobs(run_id)
);
CREATE TABLE run_artifacts (
    artifact_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, artifact_type TEXT NOT NULL, schema_version TEXT NOT NULL,
    content_json TEXT NOT NULL, sha256 TEXT NOT NULL, created_at TEXT NOT NULL, attempt_id TEXT, step_id TEXT,
    artifact_version INTEGER NOT NULL DEFAULT 1, supersedes_artifact_id TEXT,
    FOREIGN KEY(run_id) REFERENCES run_jobs(run_id)
);
CREATE TABLE run_event_counters (
    run_id TEXT PRIMARY KEY, next_seq INTEGER NOT NULL DEFAULT 1, FOREIGN KEY(run_id) REFERENCES run_jobs(run_id)
);
CREATE TABLE run_steps (
    step_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, step_key TEXT NOT NULL, step_version TEXT NOT NULL,
    attempt_id TEXT NOT NULL, input_hash TEXT NOT NULL, output_hash TEXT, status TEXT NOT NULL,
    started_at TEXT NOT NULL, completed_at TEXT, duration_ms INTEGER NOT NULL DEFAULT 0, error_code TEXT,
    artifact_refs TEXT NOT NULL DEFAULT '[]', input_json TEXT NOT NULL DEFAULT '{}', output_json TEXT NOT NULL DEFAULT '{}',
    FOREIGN KEY(run_id) REFERENCES run_jobs(run_id), UNIQUE(run_id, step_key, attempt_id)
);
CREATE TABLE run_attempts (
    attempt_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, worker_id TEXT NOT NULL, attempt_number INTEGER NOT NULL,
    status TEXT NOT NULL, resume_from_step TEXT, started_at TEXT NOT NULL, completed_at TEXT,
    error_code TEXT, error_message TEXT, FOREIGN KEY(run_id) REFERENCES run_jobs(run_id), UNIQUE(run_id, attempt_number)
);
CREATE UNIQUE INDEX idx_run_jobs_project_idempotency ON run_jobs(project_id, idempotency_key) WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_run_jobs_claimable ON run_jobs(status, next_attempt_at, created_at);
CREATE INDEX idx_run_attempts_run_number ON run_attempts(run_id, attempt_number);
CREATE INDEX idx_run_artifacts_lineage ON run_artifacts(run_id, artifact_type, attempt_id, artifact_version);

-- 0002_v13_trust_governance / sha256:02406de1f9ba6cbcd002b49872fe7a8f56a7da8a010d961880b11d517139b38c
CREATE TABLE users (
    user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
    display_name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','analyst','reviewer','viewer')),
    is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
    last_login_at TEXT
);
CREATE TABLE auth_sessions (
    session_id TEXT PRIMARY KEY, user_id TEXT NOT NULL, token_hash TEXT NOT NULL UNIQUE, csrf_hash TEXT NOT NULL,
    created_at TEXT NOT NULL, last_seen_at TEXT NOT NULL, idle_expires_at TEXT NOT NULL, absolute_expires_at TEXT NOT NULL,
    revoked_at TEXT, client_ip TEXT, user_agent TEXT, FOREIGN KEY(user_id) REFERENCES users(user_id)
);
CREATE TABLE security_audit_events (
    event_id TEXT PRIMARY KEY, actor_user_id TEXT, event_type TEXT NOT NULL, outcome TEXT NOT NULL,
    resource_type TEXT, resource_id TEXT, detail_json TEXT NOT NULL DEFAULT '{}', client_ip TEXT,
    created_at TEXT NOT NULL, FOREIGN KEY(actor_user_id) REFERENCES users(user_id)
);
CREATE TABLE rule_packs (
    rule_pack_id TEXT PRIMARY KEY, name TEXT NOT NULL, version TEXT NOT NULL UNIQUE,
    war_room_rule_version TEXT NOT NULL, consistency_rule_version TEXT NOT NULL,
    action_adapter_version TEXT NOT NULL, scoring_weights_version TEXT NOT NULL,
    evidence_policy_version TEXT NOT NULL, manifest_json TEXT NOT NULL, manifest_hash TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL CHECK(status IN ('draft','candidate','active','retired')),
    creator_user_id TEXT, created_at TEXT NOT NULL, submitted_at TEXT, activated_at TEXT,
    supersedes_rule_pack_id TEXT, FOREIGN KEY(creator_user_id) REFERENCES users(user_id),
    FOREIGN KEY(supersedes_rule_pack_id) REFERENCES rule_packs(rule_pack_id)
);
CREATE TABLE rule_pack_reviews (
    review_id TEXT PRIMARY KEY, rule_pack_id TEXT NOT NULL, reviewer_user_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('approve','reject','request_revision')),
    comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    FOREIGN KEY(rule_pack_id) REFERENCES rule_packs(rule_pack_id), FOREIGN KEY(reviewer_user_id) REFERENCES users(user_id)
);
CREATE TABLE calibration_cases (
    case_id TEXT PRIMARY KEY, version TEXT NOT NULL, category TEXT NOT NULL, title TEXT NOT NULL,
    cutoff_date TEXT NOT NULL, observation_window_days INTEGER NOT NULL, input_snapshot TEXT NOT NULL,
    labels_json TEXT NOT NULL, evidence_json TEXT NOT NULL, label_confidence DOUBLE PRECISION NOT NULL,
    case_hash TEXT NOT NULL UNIQUE, is_active INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL,
    UNIQUE(case_id, version)
);
CREATE TABLE calibration_runs (
    calibration_run_id TEXT PRIMARY KEY, rule_pack_id TEXT NOT NULL, lifecycle_run_id TEXT,
    status TEXT NOT NULL, metrics_json TEXT NOT NULL DEFAULT '{}', gate_status TEXT NOT NULL DEFAULT 'pending',
    created_by_user_id TEXT, created_at TEXT NOT NULL, completed_at TEXT,
    FOREIGN KEY(rule_pack_id) REFERENCES rule_packs(rule_pack_id), FOREIGN KEY(lifecycle_run_id) REFERENCES run_jobs(run_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id)
);
CREATE TABLE calibration_results (
    result_id TEXT PRIMARY KEY, calibration_run_id TEXT NOT NULL, case_id TEXT NOT NULL,
    metrics_json TEXT NOT NULL, passed INTEGER NOT NULL, result_hash TEXT NOT NULL, created_at TEXT NOT NULL,
    FOREIGN KEY(calibration_run_id) REFERENCES calibration_runs(calibration_run_id),
    FOREIGN KEY(case_id) REFERENCES calibration_cases(case_id), UNIQUE(calibration_run_id, case_id)
);
CREATE TABLE review_cases (
    review_id TEXT PRIMARY KEY, review_type TEXT NOT NULL, resource_type TEXT NOT NULL, resource_id TEXT NOT NULL,
    severity TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', reason TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
    assigned_to_user_id TEXT, created_at TEXT NOT NULL, closed_at TEXT,
    FOREIGN KEY(assigned_to_user_id) REFERENCES users(user_id)
);
CREATE TABLE review_decisions (
    decision_id TEXT PRIMARY KEY, review_id TEXT NOT NULL, reviewer_user_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK(decision IN ('confirmed','request_revision','reject_promotion','approve_promotion')),
    comment TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
    FOREIGN KEY(review_id) REFERENCES review_cases(review_id), FOREIGN KEY(reviewer_user_id) REFERENCES users(user_id)
);
ALTER TABLE run_jobs ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'war_room';
ALTER TABLE run_jobs ADD COLUMN rule_pack_id TEXT;
ALTER TABLE run_jobs ADD COLUMN rule_pack_hash TEXT;
CREATE INDEX idx_auth_sessions_token ON auth_sessions(token_hash, revoked_at);
CREATE INDEX idx_security_audit_created ON security_audit_events(created_at, event_type);
CREATE INDEX idx_rule_packs_status ON rule_packs(status, created_at);
CREATE INDEX idx_calibration_runs_pack ON calibration_runs(rule_pack_id, created_at);
CREATE INDEX idx_review_cases_status ON review_cases(status, severity, created_at);

-- 0003_v14_evidence_registry / sha256:00ab2ec43fffcfcf127c92c9c1f6bb45c438211c8d45a04ec6aade500dd471cb
CREATE TABLE evidence_sources (
    source_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL,
    name TEXT NOT NULL,
    locator TEXT NOT NULL,
    publisher TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    trust_tier TEXT NOT NULL DEFAULT 'internal',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT,
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(source_type, locator),
    CHECK(status IN ('active', 'degraded', 'retired'))
);

CREATE TABLE evidence_snapshots (
    snapshot_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    project_id TEXT,
    external_ref TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    content_json TEXT NOT NULL,
    content_text TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    created_by_user_id TEXT,
    FOREIGN KEY(source_id) REFERENCES evidence_sources(source_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(source_id, external_ref, content_hash)
);

CREATE TABLE evidence_claims (
    claim_id TEXT PRIMARY KEY,
    project_id TEXT,
    run_id TEXT,
    statement TEXT NOT NULL,
    claim_type TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    cutoff_at TEXT NOT NULL,
    claim_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(run_id) REFERENCES research_runs(run_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    CHECK(confidence >= 0 AND confidence <= 1)
);

CREATE TABLE evidence_links (
    link_id TEXT PRIMARY KEY,
    claim_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'supports',
    citation_label TEXT NOT NULL DEFAULT '',
    excerpt TEXT NOT NULL DEFAULT '',
    locator_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY(claim_id) REFERENCES evidence_claims(claim_id),
    FOREIGN KEY(snapshot_id) REFERENCES evidence_snapshots(snapshot_id),
    UNIQUE(claim_id, snapshot_id, relation, citation_label),
    CHECK(relation IN ('supports', 'contradicts', 'context'))
);

CREATE TABLE evidence_packs (
    pack_id TEXT PRIMARY KEY,
    project_id TEXT,
    run_id TEXT,
    name TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(run_id) REFERENCES research_runs(run_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id)
);

CREATE TABLE evidence_pack_items (
    pack_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL,
    claim_id TEXT,
    position INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(pack_id, snapshot_id, claim_id),
    FOREIGN KEY(pack_id) REFERENCES evidence_packs(pack_id),
    FOREIGN KEY(snapshot_id) REFERENCES evidence_snapshots(snapshot_id),
    FOREIGN KEY(claim_id) REFERENCES evidence_claims(claim_id)
);

CREATE INDEX idx_evidence_snapshots_project_cutoff ON evidence_snapshots(project_id, cutoff_at, captured_at);
CREATE INDEX idx_evidence_snapshots_category ON evidence_snapshots(category, cutoff_at);
CREATE INDEX idx_evidence_claims_project_cutoff ON evidence_claims(project_id, cutoff_at, created_at);
CREATE INDEX idx_evidence_links_snapshot ON evidence_links(snapshot_id, claim_id);
CREATE INDEX idx_evidence_packs_project ON evidence_packs(project_id, created_at);

-- 0004_v15_organization_ingestion / sha256:48bb71e5207ee6cfc8e9c04a1d516e8e93e71707b340b9fbba1e187bddce3e83
CREATE TABLE organizations (
    organization_id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    CHECK(status IN ('active','suspended','retired'))
);

CREATE TABLE organization_members (
    organization_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    role TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    added_by_user_id TEXT,
    created_at TEXT NOT NULL,
    PRIMARY KEY(organization_id, user_id),
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(added_by_user_id) REFERENCES users(user_id),
    CHECK(role IN ('owner','admin','analyst','reviewer','viewer')),
    CHECK(status IN ('active','suspended','removed'))
);

CREATE TABLE organization_resources (
    organization_id TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY(organization_id, resource_type, resource_id),
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id)
);

CREATE TABLE ingestion_policies (
    policy_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    allowed_connector_types_json TEXT NOT NULL,
    allowed_categories_json TEXT NOT NULL,
    max_records INTEGER NOT NULL,
    max_bytes INTEGER NOT NULL,
    require_license_metadata INTEGER NOT NULL DEFAULT 1,
    require_cutoff INTEGER NOT NULL DEFAULT 1,
    retention_days INTEGER NOT NULL DEFAULT 3650,
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(organization_id, name, version),
    CHECK(status IN ('active','retired'))
);

CREATE TABLE data_connectors (
    connector_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    name TEXT NOT NULL,
    connector_type TEXT NOT NULL,
    source_locator TEXT NOT NULL,
    config_json TEXT NOT NULL DEFAULT '{}',
    config_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    retired_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(policy_id) REFERENCES ingestion_policies(policy_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(organization_id, name),
    CHECK(connector_type IN ('manual_json')),
    CHECK(status IN ('active','degraded','retired'))
);

CREATE TABLE ingestion_jobs (
    job_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    connector_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    project_id TEXT,
    parent_job_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    request_json TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    idempotency_key TEXT,
    record_count INTEGER NOT NULL DEFAULT 0,
    accepted_count INTEGER NOT NULL DEFAULT 0,
    rejected_count INTEGER NOT NULL DEFAULT 0,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    manifest_hash TEXT,
    error_code TEXT,
    error_message TEXT,
    created_by_user_id TEXT,
    worker_id TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    cancel_requested_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(connector_id) REFERENCES data_connectors(connector_id),
    FOREIGN KEY(policy_id) REFERENCES ingestion_policies(policy_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(parent_job_id) REFERENCES ingestion_jobs(job_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(organization_id, idempotency_key),
    CHECK(status IN ('queued','running','cancelling','cancelled','failed','completed'))
);

CREATE TABLE ingestion_event_counters (
    job_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(job_id) REFERENCES ingestion_jobs(job_id)
);

CREATE TABLE ingestion_events (
    job_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(job_id, seq),
    FOREIGN KEY(job_id) REFERENCES ingestion_jobs(job_id)
);

CREATE TABLE ingestion_records (
    record_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    external_ref TEXT NOT NULL,
    category TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    evidence_snapshot_id TEXT,
    status TEXT NOT NULL,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(job_id) REFERENCES ingestion_jobs(job_id),
    FOREIGN KEY(evidence_snapshot_id) REFERENCES evidence_snapshots(snapshot_id),
    UNIQUE(job_id, external_ref),
    CHECK(status IN ('accepted','rejected'))
);

INSERT INTO organizations
(organization_id, slug, name, status, created_at, updated_at)
VALUES ('org_default', 'default', 'WorldPulse Default Organization', 'active', '2026-07-16T00:00:00.000', '2026-07-16T00:00:00.000');

INSERT INTO organization_members
(organization_id, user_id, role, status, created_at)
SELECT 'org_default', user_id,
       CASE role WHEN 'admin' THEN 'owner' ELSE role END,
       'active', '2026-07-16T00:00:00.000'
FROM users;

INSERT INTO organization_resources
(organization_id, resource_type, resource_id, created_at)
SELECT 'org_default', 'project', project_id, '2026-07-16T00:00:00.000' FROM research_projects;

INSERT INTO organization_resources
(organization_id, resource_type, resource_id, created_at)
SELECT 'org_default', 'evidence_source', source_id, '2026-07-16T00:00:00.000' FROM evidence_sources;

CREATE INDEX idx_org_members_user ON organization_members(user_id, status, organization_id);
CREATE INDEX idx_org_resources_lookup ON organization_resources(resource_type, resource_id, organization_id);
CREATE INDEX idx_ingestion_policies_org ON ingestion_policies(organization_id, status, created_at);
CREATE INDEX idx_data_connectors_org ON data_connectors(organization_id, status, created_at);
CREATE INDEX idx_ingestion_jobs_claim ON ingestion_jobs(status, created_at);
CREATE INDEX idx_ingestion_jobs_org ON ingestion_jobs(organization_id, created_at);
CREATE INDEX idx_ingestion_records_job ON ingestion_records(job_id, status, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users(LOWER(username));
