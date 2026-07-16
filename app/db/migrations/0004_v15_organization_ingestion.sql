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
