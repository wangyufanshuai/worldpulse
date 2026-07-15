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
    confidence REAL NOT NULL,
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
