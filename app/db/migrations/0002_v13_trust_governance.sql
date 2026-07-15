CREATE TABLE users (
    user_id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE, password_hash TEXT NOT NULL,
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
    labels_json TEXT NOT NULL, evidence_json TEXT NOT NULL, label_confidence REAL NOT NULL,
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
