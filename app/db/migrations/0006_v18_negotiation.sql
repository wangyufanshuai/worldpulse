ALTER TABLE run_jobs ADD COLUMN agent_pack_id TEXT;
ALTER TABLE run_jobs ADD COLUMN agent_pack_hash TEXT;

CREATE TABLE agent_packs (
    agent_pack_id TEXT PRIMARY KEY,
    schema_version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    seed INTEGER NOT NULL,
    profiles_json TEXT NOT NULL,
    manifest_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    CHECK(status IN ('active','retired'))
);

CREATE TABLE negotiation_sessions (
    session_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    agent_pack_id TEXT NOT NULL,
    agent_pack_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    current_tick INTEGER NOT NULL DEFAULT 0,
    baseline_result_hash TEXT NOT NULL,
    final_result_hash TEXT,
    cumulative_patch_json TEXT NOT NULL DEFAULT '{}',
    applied_proposal_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(run_id) REFERENCES run_jobs(run_id),
    FOREIGN KEY(agent_pack_id) REFERENCES agent_packs(agent_pack_id),
    CHECK(status IN ('running','paused','cancelled','failed','completed')),
    CHECK(current_tick >= 0 AND current_tick <= 6)
);

CREATE TABLE negotiation_rounds (
    round_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    simulation_day INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    scheduled_agents_json TEXT NOT NULL,
    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL DEFAULT '{}',
    input_hash TEXT NOT NULL,
    output_hash TEXT,
    previous_state_hash TEXT NOT NULL,
    modifier_bundle_hash TEXT,
    result_state_hash TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    FOREIGN KEY(session_id) REFERENCES negotiation_sessions(session_id),
    UNIQUE(session_id, tick),
    CHECK(tick >= 1 AND tick <= 6),
    CHECK(status IN ('running','completed','failed'))
);

CREATE TABLE negotiation_messages (
    message_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    round_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    sender_agent_id TEXT NOT NULL,
    recipient_agent_ids_json TEXT NOT NULL,
    message_type TEXT NOT NULL,
    visibility TEXT NOT NULL,
    parent_message_id TEXT,
    proposal_id TEXT,
    narrative TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    provider TEXT NOT NULL,
    model TEXT NOT NULL,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    estimated_tokens INTEGER NOT NULL DEFAULT 0,
    fallback_used INTEGER NOT NULL DEFAULT 0,
    previous_hash TEXT,
    message_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES negotiation_sessions(session_id),
    FOREIGN KEY(round_id) REFERENCES negotiation_rounds(round_id),
    FOREIGN KEY(parent_message_id) REFERENCES negotiation_messages(message_id),
    UNIQUE(session_id, seq),
    UNIQUE(session_id, tick, sender_agent_id),
    CHECK(message_type IN ('proposal','counteroffer','accept','reject','withdrawal','public_statement')),
    CHECK(visibility IN ('public','direct')),
    CHECK(fallback_used IN (0,1))
);

CREATE TABLE negotiation_commitments (
    commitment_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    source_proposal_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    party_agent_ids_json TEXT NOT NULL,
    terms_json TEXT NOT NULL,
    commitment_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(session_id) REFERENCES negotiation_sessions(session_id),
    FOREIGN KEY(source_message_id) REFERENCES negotiation_messages(message_id),
    UNIQUE(session_id, source_proposal_id)
);

CREATE TABLE negotiation_commitment_events (
    event_id TEXT PRIMARY KEY,
    commitment_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    tick INTEGER NOT NULL,
    seq INTEGER NOT NULL,
    status TEXT NOT NULL,
    actor_agent_id TEXT NOT NULL,
    source_message_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    event_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    FOREIGN KEY(commitment_id) REFERENCES negotiation_commitments(commitment_id),
    FOREIGN KEY(session_id) REFERENCES negotiation_sessions(session_id),
    FOREIGN KEY(source_message_id) REFERENCES negotiation_messages(message_id),
    UNIQUE(commitment_id, seq),
    CHECK(status IN ('proposed','active','rejected','withdrawn','expired'))
);

CREATE INDEX idx_agent_packs_status ON agent_packs(status, created_at);
CREATE INDEX idx_negotiation_rounds_session ON negotiation_rounds(session_id, tick);
CREATE INDEX idx_negotiation_messages_session ON negotiation_messages(session_id, seq);
CREATE INDEX idx_negotiation_messages_tick ON negotiation_messages(session_id, tick, seq);
CREATE INDEX idx_negotiation_commitments_session ON negotiation_commitments(session_id, created_at);
CREATE INDEX idx_negotiation_commitment_events_session ON negotiation_commitment_events(session_id, tick, seq);
