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
    nodes TEXT NOT NULL, edges TEXT NOT NULL, confidence REAL NOT NULL, evidence_sources TEXT NOT NULL,
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
    current_phase TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, seed INTEGER, parent_run_id TEXT,
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
