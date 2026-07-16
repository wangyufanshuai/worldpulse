ALTER TABLE run_jobs ADD COLUMN evaluation_batch_id TEXT;
ALTER TABLE run_jobs ADD COLUMN evaluation_member_id TEXT;
ALTER TABLE run_jobs ADD COLUMN runtime_profile_json TEXT NOT NULL DEFAULT '{}';
ALTER TABLE run_jobs ADD COLUMN runtime_profile_hash TEXT;

CREATE TABLE evaluation_suites (
    suite_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    retired_at TEXT,
    CHECK(status IN ('active','retired'))
);

CREATE TABLE evaluation_cases (
    case_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL,
    version TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    input_json TEXT NOT NULL,
    qualitative_expectations_json TEXT NOT NULL DEFAULT '{}',
    safety_probes_json TEXT NOT NULL DEFAULT '{}',
    evidence_json TEXT NOT NULL DEFAULT '[]',
    case_hash TEXT NOT NULL UNIQUE,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    FOREIGN KEY(suite_id) REFERENCES evaluation_suites(suite_id)
);

CREATE TABLE evaluation_batches (
    batch_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT,
    scenario_draft_id TEXT,
    scenario_draft_hash TEXT,
    evidence_pack_hash TEXT,
    suite_id TEXT NOT NULL,
    suite_hash TEXT NOT NULL,
    rule_pack_id TEXT,
    rule_pack_hash TEXT,
    runtime_profile_json TEXT NOT NULL,
    runtime_profile_hash TEXT NOT NULL,
    provider_mode TEXT NOT NULL,
    source_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    parent_batch_id TEXT,
    total_members INTEGER NOT NULL DEFAULT 0,
    completed_members INTEGER NOT NULL DEFAULT 0,
    failed_members INTEGER NOT NULL DEFAULT 0,
    safety_status TEXT NOT NULL DEFAULT 'pending',
    quality_status TEXT NOT NULL DEFAULT 'pending',
    metrics_json TEXT NOT NULL DEFAULT '{}',
    report_hash TEXT,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(suite_id) REFERENCES evaluation_suites(suite_id),
    FOREIGN KEY(parent_batch_id) REFERENCES evaluation_batches(batch_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    CHECK(status IN ('queued','running','pausing','paused','cancelling','cancelled','failed','completed')),
    CHECK(provider_mode IN ('mock','deepseek','siliconflow')),
    CHECK(source_type IN ('standard','observation','project')),
    CHECK(safety_status IN ('pending','passed','failed','not_applicable'))
);

CREATE TABLE evaluation_members (
    member_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    case_id TEXT NOT NULL,
    engine_mode TEXT NOT NULL,
    seed INTEGER NOT NULL,
    run_id TEXT UNIQUE,
    status TEXT NOT NULL DEFAULT 'pending',
    baseline_result_hash TEXT,
    result_hash TEXT,
    metrics_json TEXT NOT NULL DEFAULT '{}',
    artifact_refs_json TEXT NOT NULL DEFAULT '[]',
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(batch_id) REFERENCES evaluation_batches(batch_id),
    FOREIGN KEY(case_id) REFERENCES evaluation_cases(case_id),
    FOREIGN KEY(run_id) REFERENCES run_jobs(run_id),
    UNIQUE(batch_id, case_id, engine_mode, seed),
    CHECK(engine_mode IN ('deterministic','hybrid','negotiation')),
    CHECK(status IN ('pending','queued','running','paused','cancelled','failed','completed'))
);

CREATE TABLE evaluation_metrics (
    metric_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    member_id TEXT,
    scope TEXT NOT NULL,
    metric_key TEXT NOT NULL,
    value_json TEXT NOT NULL,
    passed INTEGER,
    metric_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES evaluation_batches(batch_id),
    FOREIGN KEY(member_id) REFERENCES evaluation_members(member_id)
);

CREATE TABLE evaluation_event_counters (
    batch_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(batch_id) REFERENCES evaluation_batches(batch_id)
);

CREATE TABLE evaluation_events (
    batch_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    phase TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(batch_id, seq),
    FOREIGN KEY(batch_id) REFERENCES evaluation_batches(batch_id)
);

CREATE INDEX idx_evaluation_batches_org_status ON evaluation_batches(organization_id, status, created_at);
CREATE INDEX idx_evaluation_members_batch_status ON evaluation_members(batch_id, status);
