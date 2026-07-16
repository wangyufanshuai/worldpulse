from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceType = Literal["rss_atom", "json_feed"]
SourceStatus = Literal["active", "paused", "degraded", "retired"]
PollStatus = Literal["queued", "running", "cancelling", "cancelled", "failed", "completed"]
WatchlistStatus = Literal["draft", "active", "paused", "retired"]
AlertStatus = Literal["open", "acknowledged", "dismissed", "resolved"]
Severity = Literal["info", "warning", "high", "critical"]
WatchCandidateType = Literal["scenario_preset", "country", "supply_chain", "policy_action"]
SubscriptionChannel = Literal["in_app", "webhook"]


class MonitoringSourceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=160)
    source_type: SourceType
    feed_url: str = Field(min_length=8, max_length=2000)
    publisher: str = Field(min_length=1, max_length=200)
    license_name: str = Field(min_length=1, max_length=200)
    license_url: str = Field(default="", max_length=1000)
    category: str = Field(default="other", min_length=1, max_length=80)
    poll_interval_minutes: int = Field(default=60, ge=15, le=1440)
    policy_id: str | None = Field(default=None, max_length=80)


class MonitoringSourceStatusRequest(BaseModel):
    status: Literal["active", "paused", "retired"]


class MonitoringSource(BaseModel):
    source_id: str
    organization_id: str
    project_id: str
    policy_id: str
    parent_source_id: str | None = None
    name: str
    source_type: SourceType
    feed_url: str
    publisher: str
    license_name: str
    license_url: str = ""
    category: str
    poll_interval_minutes: int
    status: SourceStatus
    etag: str | None = None
    last_modified: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    consecutive_failures: int = 0
    last_error_code: str | None = None
    last_polled_at: str | None = None
    next_poll_at: str | None = None
    created_by_user_id: str
    created_at: str
    updated_at: str
    retired_at: str | None = None


class MonitoringPollJob(BaseModel):
    poll_id: str
    organization_id: str
    project_id: str
    source_id: str
    parent_poll_id: str | None = None
    status: PollStatus
    scheduled_for: str
    request_hash: str
    worker_id: str | None = None
    lease_expires_at: str | None = None
    attempt_count: int = 0
    response_status: int | None = None
    response_hash: str | None = None
    discovered_count: int = 0
    changed_count: int = 0
    matched_count: int = 0
    materialized_count: int = 0
    result: dict[str, Any] = Field(default_factory=dict)
    result_hash: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_by_user_id: str
    created_at: str
    started_at: str | None = None
    updated_at: str
    completed_at: str | None = None


class MonitoringPollEvent(BaseModel):
    poll_id: str
    seq: int
    event_type: str
    title: str
    detail: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class WatchRuleCreate(BaseModel):
    candidate_type: WatchCandidateType
    canonical_value: str = Field(min_length=1, max_length=160)
    severity: Severity = "warning"


class WatchRule(WatchRuleCreate):
    rule_id: str
    position: int
    rule_hash: str


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=2, max_length=160)
    rules: list[WatchRuleCreate] = Field(min_length=1, max_length=100)


class WatchlistManifest(BaseModel):
    watchlist_id: str
    family_id: str
    organization_id: str
    project_id: str
    parent_watchlist_id: str | None = None
    version: int
    name: str
    status: WatchlistStatus
    manifest: dict[str, Any]
    manifest_hash: str
    created_by_user_id: str
    created_at: str
    activated_at: str | None = None
    retired_at: str | None = None
    rules: list[WatchRule] = Field(default_factory=list)


class AlertLineage(BaseModel):
    document_id: str | None = None
    extraction_job_id: str | None = None
    extraction_id: str | None = None
    snapshot_ids: list[str] = Field(default_factory=list)
    candidate_ids: list[str] = Field(default_factory=list)
    pipeline_status: str = "pending"


class IntelligenceAlert(BaseModel):
    alert_id: str
    organization_id: str
    project_id: str
    watchlist_id: str
    source_id: str
    stable_key: str
    status: AlertStatus
    severity: Severity
    title: str
    summary: str
    revision_count: int
    latest_entry_id: str
    latest_entry_hash: str
    matches: list[dict[str, Any]] = Field(default_factory=list)
    lineage: AlertLineage = Field(default_factory=AlertLineage)
    alert_hash: str
    acknowledged_by_user_id: str | None = None
    acknowledged_at: str | None = None
    dismissed_by_user_id: str | None = None
    dismissed_at: str | None = None
    created_at: str
    updated_at: str


class IntelligenceAlertEvent(BaseModel):
    alert_id: str
    seq: int
    event_type: str
    entry_id: str | None = None
    actor_user_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    event_hash: str
    created_at: str


class NotificationSubscriptionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: SubscriptionChannel
    project_id: str | None = Field(default=None, max_length=80)
    watchlist_id: str | None = Field(default=None, max_length=80)
    endpoint_url: str | None = Field(default=None, max_length=2000)
    secret_ref: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{2,79}$")
    min_severity: Severity = "warning"

    @model_validator(mode="after")
    def validate_channel_fields(self):
        if self.channel == "webhook" and (not self.endpoint_url or not self.secret_ref):
            raise ValueError("Webhook subscriptions require endpoint_url and secret_ref")
        if self.channel == "in_app" and (self.endpoint_url or self.secret_ref):
            raise ValueError("In-app subscriptions cannot contain webhook configuration")
        return self


class NotificationSubscription(BaseModel):
    subscription_id: str
    organization_id: str
    project_id: str | None = None
    watchlist_id: str | None = None
    channel: SubscriptionChannel
    subscriber_user_id: str | None = None
    endpoint_url: str | None = None
    secret_ref: str | None = None
    min_severity: Severity
    status: Literal["active", "paused", "retired"]
    config: dict[str, Any] = Field(default_factory=dict)
    config_hash: str
    created_by_user_id: str
    created_at: str
    updated_at: str


class InAppNotification(BaseModel):
    notification_id: str
    organization_id: str
    seq: int
    user_id: str
    alert_id: str
    event_type: str
    entry_hash: str
    title: str
    body: str
    severity: Severity
    deep_link: str
    payload: dict[str, Any] = Field(default_factory=dict)
    payload_hash: str
    created_at: str
    read_at: str | None = None


class WebhookDelivery(BaseModel):
    delivery_id: str
    subscription_id: str
    alert_id: str
    event_type: str
    entry_hash: str
    status: Literal["queued", "delivering", "retrying", "delivered", "failed", "cancelled"]
    attempt_count: int
    next_attempt_at: str
    payload_hash: str
    response_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: str
    updated_at: str
    delivered_at: str | None = None


class ContinuousIntelligenceSummary(BaseModel):
    organization_id: str
    project_id: str
    enabled: bool
    active_sources: int
    degraded_sources: int
    queued_polls: int
    open_alerts: int
    high_alerts: int
    pending_candidates: int
    unread_notifications: int
    sources: list[MonitoringSource] = Field(default_factory=list)
    watchlists: list[WatchlistManifest] = Field(default_factory=list)
    alerts: list[IntelligenceAlert] = Field(default_factory=list)
    polls: list[MonitoringPollJob] = Field(default_factory=list)
    generated_at: str
