ALTER TABLE evaluation_batches ADD COLUMN evaluation_track TEXT NOT NULL DEFAULT 'engineering_standard';
ALTER TABLE evaluation_batches ADD COLUMN benchmark_suite_id TEXT;
ALTER TABLE evaluation_batches ADD COLUMN benchmark_suite_hash TEXT;
ALTER TABLE evaluation_batches ADD COLUMN label_pack_id TEXT;
ALTER TABLE evaluation_batches ADD COLUMN label_pack_hash TEXT;
ALTER TABLE evaluation_batches ADD COLUMN gate_manifest_hash TEXT;
ALTER TABLE evaluation_batches ADD COLUMN root_batch_id TEXT;
ALTER TABLE evaluation_batches ADD COLUMN coordinator_worker_id TEXT;
ALTER TABLE evaluation_batches ADD COLUMN coordinator_lease_expires_at TEXT;
ALTER TABLE evaluation_batches ADD COLUMN coordinator_attempt_count INTEGER NOT NULL DEFAULT 0;

ALTER TABLE evaluation_members ADD COLUMN input_hash TEXT;
ALTER TABLE evaluation_members ADD COLUMN expected_baseline_hash TEXT;
ALTER TABLE evaluation_members ADD COLUMN verification_status TEXT NOT NULL DEFAULT 'pending';
ALTER TABLE evaluation_members ADD COLUMN verification_hash TEXT;

CREATE TABLE historical_benchmark_suites (
    suite_id TEXT PRIMARY KEY,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    development_count INTEGER NOT NULL DEFAULT 0,
    blind_count INTEGER NOT NULL DEFAULT 0,
    created_by_user_id TEXT,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    retired_at TEXT,
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    CHECK(status IN ('draft','active','retired'))
);

CREATE TABLE historical_benchmark_cases (
    case_id TEXT PRIMARY KEY,
    suite_id TEXT NOT NULL,
    version TEXT NOT NULL,
    domain TEXT NOT NULL,
    split TEXT NOT NULL,
    title TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    observation_window_days INTEGER NOT NULL,
    scenario_json TEXT NOT NULL,
    evidence_manifest_json TEXT NOT NULL,
    development_labels_json TEXT,
    label_confidence DOUBLE PRECISION NOT NULL,
    case_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(suite_id) REFERENCES historical_benchmark_suites(suite_id),
    UNIQUE(suite_id, domain, split, title),
    CHECK(split IN ('development','blind')),
    CHECK(domain IN ('strait','energy','food','sanctions','trade','finance'))
);

CREATE TABLE historical_benchmark_evidence (
    evidence_id TEXT PRIMARY KEY,
    case_id TEXT NOT NULL,
    evidence_role TEXT NOT NULL,
    publisher TEXT NOT NULL,
    license_name TEXT NOT NULL,
    source_url TEXT NOT NULL,
    observed_at TEXT NOT NULL,
    cutoff_at TEXT NOT NULL,
    blob_sha256 TEXT NOT NULL,
    locator_json TEXT NOT NULL DEFAULT '{}',
    evidence_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(case_id) REFERENCES historical_benchmark_cases(case_id),
    CHECK(evidence_role IN ('input','outcome'))
);

CREATE TABLE historical_label_packs (
    label_pack_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    suite_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'uploaded',
    blob_sha256 TEXT NOT NULL,
    manifest_hash TEXT NOT NULL,
    signature TEXT NOT NULL,
    signer_key_id TEXT NOT NULL,
    encryption_key_id TEXT NOT NULL,
    nonce_b64 TEXT NOT NULL,
    evidence_hash TEXT NOT NULL,
    case_count INTEGER NOT NULL,
    imported_by_user_id TEXT NOT NULL,
    bound_root_batch_id TEXT,
    comparison_started_at TEXT,
    consumed_at TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(suite_id) REFERENCES historical_benchmark_suites(suite_id),
    FOREIGN KEY(imported_by_user_id) REFERENCES users(user_id),
    FOREIGN KEY(bound_root_batch_id) REFERENCES evaluation_batches(batch_id),
    UNIQUE(organization_id, suite_id, manifest_hash),
    CHECK(status IN ('uploaded','reviewing','active','consuming','consumed','rejected'))
);

CREATE TABLE historical_label_pack_reviews (
    review_id TEXT PRIMARY KEY,
    label_pack_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL,
    reviewer_role TEXT NOT NULL,
    decision TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    review_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(label_pack_id) REFERENCES historical_label_packs(label_pack_id),
    FOREIGN KEY(reviewer_user_id) REFERENCES users(user_id),
    UNIQUE(label_pack_id, reviewer_user_id),
    CHECK(reviewer_role IN ('admin','reviewer')),
    CHECK(decision IN ('approve','reject'))
);

CREATE TABLE evaluation_gate_manifests (
    gate_manifest_id TEXT PRIMARY KEY,
    version TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    retired_at TEXT,
    CHECK(status IN ('active','retired'))
);

CREATE TABLE evaluation_verification_results (
    verification_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL,
    member_id TEXT,
    check_key TEXT NOT NULL,
    status TEXT NOT NULL,
    observed_json TEXT NOT NULL,
    evidence_artifact_ids_json TEXT NOT NULL DEFAULT '[]',
    verifier_version TEXT NOT NULL,
    verification_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(batch_id) REFERENCES evaluation_batches(batch_id),
    FOREIGN KEY(member_id) REFERENCES evaluation_members(member_id),
    UNIQUE(batch_id, member_id, check_key),
    CHECK(status IN ('passed','failed','not_applicable'))
);

CREATE INDEX idx_historical_cases_suite_split ON historical_benchmark_cases(suite_id, split, domain);
CREATE INDEX idx_label_packs_org_status ON historical_label_packs(organization_id, status, created_at);
CREATE INDEX idx_verification_batch_status ON evaluation_verification_results(batch_id, status, check_key);
CREATE INDEX idx_evaluation_batches_track_status ON evaluation_batches(evaluation_track, status, created_at);
