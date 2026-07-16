CREATE TABLE monitoring_sources (
    source_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    parent_source_id TEXT,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    feed_url TEXT NOT NULL,
    publisher TEXT NOT NULL,
    license_name TEXT NOT NULL,
    license_url TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'other',
    poll_interval_minutes INTEGER NOT NULL DEFAULT 60,
    status TEXT NOT NULL DEFAULT 'paused',
    etag TEXT,
    last_modified TEXT,
    config_json TEXT NOT NULL,
    config_hash TEXT NOT NULL UNIQUE,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_error_code TEXT,
    last_polled_at TEXT,
    next_poll_at TEXT,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    retired_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(policy_id) REFERENCES ingestion_policies(policy_id),
    FOREIGN KEY(parent_source_id) REFERENCES monitoring_sources(source_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(organization_id, project_id, name),
    CHECK(source_type IN ('rss_atom','json_feed')),
    CHECK(status IN ('active','paused','degraded','retired')),
    CHECK(poll_interval_minutes BETWEEN 15 AND 1440)
);

CREATE TABLE monitoring_poll_jobs (
    poll_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    parent_poll_id TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    scheduled_for TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    worker_id TEXT,
    lease_expires_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    response_status INTEGER,
    response_hash TEXT,
    discovered_count INTEGER NOT NULL DEFAULT 0,
    changed_count INTEGER NOT NULL DEFAULT 0,
    matched_count INTEGER NOT NULL DEFAULT 0,
    materialized_count INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL DEFAULT '{}',
    result_hash TEXT,
    error_code TEXT,
    error_message TEXT,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    started_at TEXT,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    cancel_requested_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id),
    FOREIGN KEY(parent_poll_id) REFERENCES monitoring_poll_jobs(poll_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(source_id, scheduled_for),
    CHECK(status IN ('queued','running','cancelling','cancelled','failed','completed'))
);

CREATE TABLE monitoring_poll_event_counters (
    poll_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(poll_id) REFERENCES monitoring_poll_jobs(poll_id)
);

CREATE TABLE monitoring_poll_events (
    poll_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    PRIMARY KEY(poll_id, seq),
    FOREIGN KEY(poll_id) REFERENCES monitoring_poll_jobs(poll_id)
);

CREATE TABLE monitoring_entries (
    entry_id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    poll_id TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    revision INTEGER NOT NULL,
    canonical_url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    published_at TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    match_json TEXT NOT NULL DEFAULT '[]',
    materialization_status TEXT NOT NULL DEFAULT 'unmatched',
    document_id TEXT,
    extraction_job_id TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id),
    FOREIGN KEY(poll_id) REFERENCES monitoring_poll_jobs(poll_id),
    FOREIGN KEY(document_id) REFERENCES source_documents(document_id),
    FOREIGN KEY(extraction_job_id) REFERENCES document_extraction_jobs(job_id),
    UNIQUE(source_id, stable_key, content_hash),
    UNIQUE(source_id, stable_key, revision),
    CHECK(materialization_status IN ('unmatched','pending','queued','ready','failed','blocked'))
);

CREATE TABLE monitoring_watchlists (
    watchlist_id TEXT PRIMARY KEY,
    family_id TEXT NOT NULL,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    parent_watchlist_id TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    manifest_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    activated_at TEXT,
    retired_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(parent_watchlist_id) REFERENCES monitoring_watchlists(watchlist_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    UNIQUE(family_id, version),
    CHECK(status IN ('draft','active','paused','retired'))
);

CREATE TABLE monitoring_watch_rules (
    rule_id TEXT PRIMARY KEY,
    watchlist_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    candidate_type TEXT NOT NULL,
    canonical_value TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    rule_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(watchlist_id) REFERENCES monitoring_watchlists(watchlist_id),
    UNIQUE(watchlist_id, position),
    UNIQUE(watchlist_id, candidate_type, canonical_value),
    CHECK(candidate_type IN ('scenario_preset','country','supply_chain','policy_action')),
    CHECK(severity IN ('info','warning','high','critical'))
);

CREATE TABLE intelligence_alerts (
    alert_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    watchlist_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    stable_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    revision_count INTEGER NOT NULL DEFAULT 1,
    latest_entry_id TEXT NOT NULL,
    latest_entry_hash TEXT NOT NULL,
    match_json TEXT NOT NULL,
    lineage_json TEXT NOT NULL DEFAULT '{}',
    alert_hash TEXT NOT NULL,
    acknowledged_by_user_id TEXT,
    acknowledged_at TEXT,
    dismissed_by_user_id TEXT,
    dismissed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(watchlist_id) REFERENCES monitoring_watchlists(watchlist_id),
    FOREIGN KEY(source_id) REFERENCES monitoring_sources(source_id),
    FOREIGN KEY(latest_entry_id) REFERENCES monitoring_entries(entry_id),
    FOREIGN KEY(acknowledged_by_user_id) REFERENCES users(user_id),
    FOREIGN KEY(dismissed_by_user_id) REFERENCES users(user_id),
    UNIQUE(watchlist_id, source_id, stable_key),
    CHECK(status IN ('open','acknowledged','dismissed','resolved')),
    CHECK(severity IN ('info','warning','high','critical'))
);

CREATE TABLE intelligence_alert_events (
    alert_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    entry_id TEXT,
    actor_user_id TEXT,
    payload_json TEXT NOT NULL DEFAULT '{}',
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    PRIMARY KEY(alert_id, seq),
    FOREIGN KEY(alert_id) REFERENCES intelligence_alerts(alert_id),
    FOREIGN KEY(entry_id) REFERENCES monitoring_entries(entry_id),
    FOREIGN KEY(actor_user_id) REFERENCES users(user_id)
);

CREATE TABLE alert_subscriptions (
    subscription_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    project_id TEXT,
    watchlist_id TEXT,
    channel TEXT NOT NULL,
    subscriber_user_id TEXT,
    endpoint_url TEXT,
    secret_ref TEXT,
    min_severity TEXT NOT NULL DEFAULT 'warning',
    status TEXT NOT NULL DEFAULT 'active',
    config_json TEXT NOT NULL DEFAULT '{}',
    config_hash TEXT NOT NULL UNIQUE,
    created_by_user_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
    FOREIGN KEY(watchlist_id) REFERENCES monitoring_watchlists(watchlist_id),
    FOREIGN KEY(subscriber_user_id) REFERENCES users(user_id),
    FOREIGN KEY(created_by_user_id) REFERENCES users(user_id),
    CHECK(channel IN ('in_app','webhook')),
    CHECK(min_severity IN ('info','warning','high','critical')),
    CHECK(status IN ('active','paused','retired'))
);

CREATE TABLE organization_notification_counters (
    organization_id TEXT PRIMARY KEY,
    next_seq INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id)
);

CREATE TABLE in_app_notifications (
    notification_id TEXT PRIMARY KEY,
    organization_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    severity TEXT NOT NULL,
    deep_link TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    payload_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    read_at TEXT,
    FOREIGN KEY(organization_id) REFERENCES organizations(organization_id),
    FOREIGN KEY(user_id) REFERENCES users(user_id),
    FOREIGN KEY(alert_id) REFERENCES intelligence_alerts(alert_id),
    UNIQUE(organization_id, seq),
    UNIQUE(user_id, alert_id, event_type, entry_hash),
    CHECK(severity IN ('info','warning','high','critical'))
);

CREATE TABLE webhook_deliveries (
    delivery_id TEXT PRIMARY KEY,
    subscription_id TEXT NOT NULL,
    alert_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    next_attempt_at TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    response_status INTEGER,
    error_code TEXT,
    error_message TEXT,
    worker_id TEXT,
    lease_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    delivered_at TEXT,
    FOREIGN KEY(subscription_id) REFERENCES alert_subscriptions(subscription_id),
    FOREIGN KEY(alert_id) REFERENCES intelligence_alerts(alert_id),
    UNIQUE(subscription_id, alert_id, event_type, entry_hash),
    CHECK(status IN ('queued','delivering','retrying','delivered','failed','cancelled'))
);

CREATE INDEX idx_monitoring_sources_due ON monitoring_sources(status, next_poll_at);
CREATE INDEX idx_monitoring_sources_project ON monitoring_sources(organization_id, project_id, created_at);
CREATE INDEX idx_monitoring_polls_claim ON monitoring_poll_jobs(status, scheduled_for, created_at);
CREATE INDEX idx_monitoring_poll_events ON monitoring_poll_events(poll_id, seq);
CREATE INDEX idx_monitoring_entries_source ON monitoring_entries(source_id, stable_key, revision);
CREATE INDEX idx_watchlists_project ON monitoring_watchlists(organization_id, project_id, status, created_at);
CREATE INDEX idx_alerts_project ON intelligence_alerts(organization_id, project_id, status, updated_at);
CREATE INDEX idx_alert_events ON intelligence_alert_events(alert_id, seq);
CREATE INDEX idx_notifications_user ON in_app_notifications(user_id, read_at, seq);
CREATE INDEX idx_webhook_deliveries_claim ON webhook_deliveries(status, next_attempt_at, created_at);
