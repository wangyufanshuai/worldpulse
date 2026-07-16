CREATE TABLE worker_nodes (
    worker_id TEXT PRIMARY KEY,
    worker_kind TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'starting',
    hostname TEXT NOT NULL,
    process_id INTEGER NOT NULL,
    version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    heartbeat_at TEXT NOT NULL,
    lease_expires_at TEXT NOT NULL,
    current_job_id TEXT,
    jobs_completed INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    CHECK(worker_kind IN ('lifecycle','ingestion')),
    CHECK(status IN ('starting','ready','busy','draining','stopped','failed'))
);

CREATE TABLE organization_quotas (
    organization_id TEXT PRIMARY KEY,
    max_projects INTEGER NOT NULL DEFAULT 100,
    max_active_runs INTEGER NOT NULL DEFAULT 10,
    max_ingestion_jobs_per_day INTEGER NOT NULL DEFAULT 500,
    max_evidence_snapshots INTEGER NOT NULL DEFAULT 100000,
    updated_by_user_id TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(updated_by_user_id) REFERENCES users(user_id),
    CHECK(max_projects >= 1),
    CHECK(max_active_runs >= 1),
    CHECK(max_ingestion_jobs_per_day >= 1),
    CHECK(max_evidence_snapshots >= 1)
);

CREATE TABLE organization_quota_events (
    event_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    previous_json TEXT NOT NULL,
    current_json TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(actor_user_id) REFERENCES users(user_id)
);

INSERT INTO organization_quotas
(organization_id, max_projects, max_active_runs, max_ingestion_jobs_per_day, max_evidence_snapshots, updated_at)
SELECT organization_id, 100, 10, 500, 100000, '2026-07-16T00:00:00.000' FROM organizations;

CREATE INDEX idx_worker_nodes_freshness ON worker_nodes(worker_kind, status, lease_expires_at);
CREATE INDEX idx_quota_events_org ON organization_quota_events(organization_id, created_at);
