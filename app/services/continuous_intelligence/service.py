from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from uuid import uuid4

from fastapi import HTTPException
import requests

from app.core.continuous_intelligence_models import (
    AlertLineage, ContinuousIntelligenceSummary, InAppNotification, IntelligenceAlert,
    IntelligenceAlertEvent, MonitoringPollEvent, MonitoringPollJob, MonitoringSource,
    MonitoringSourceCreate, MonitoringSourceStatusRequest, NotificationSubscription,
    NotificationSubscriptionCreate, WatchRule, WatchlistCreate, WatchlistManifest,
    WebhookDelivery,
)
from app.core.trust_models import UserIdentity
from app.db.postgres import is_postgres_url
from app.services import ingestion
from app.services.auth import ensure_system_user, record_security_event
from app.services.consistency.hashing import stable_hash
from app.services.organizations import ORG_WRITE_ROLES, require_organization_role, require_resource_scope, scope_resource
from app.services.project_store import connect, dumps, init_db, loads
from app.services.reviews import create_review_case
from app.services.scenario_compiler import ScenarioCompilerService
from app.services.scenario_compiler.extraction import deterministic_candidates
from app.services.security import redact_secrets
from app.services.war_room.data import COUNTRIES, POLICY_ACTIONS, SCENARIOS, SUPPLY_CHAINS

from .feed import continuous_intelligence_enabled, fetch_feed, parse_feed, render_entry_markdown, validate_remote_url


READ_ROLES = {"owner", "admin", "analyst", "reviewer", "viewer"}
SEVERITY_RANK = {"info": 0, "warning": 1, "high": 2, "critical": 3}
BACKOFF_MINUTES = [1, 5, 15, 60, 360]
LEASE_SECONDS = 60


class ContinuousIntelligenceService:
    def __init__(self) -> None:
        self.compiler = ScenarioCompilerService()

    # Sources -----------------------------------------------------------------
    def create_source(self, organization_id: str, project_id: str, payload: MonitoringSourceCreate, actor: UserIdentity) -> MonitoringSource:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        require_resource_scope(organization_id, "project", project_id)
        validate_remote_url(payload.feed_url)
        policy = ingestion.get_policy(organization_id, payload.policy_id, actor) if payload.policy_id else ingestion.ensure_default_policy(organization_id, actor)
        if payload.category not in policy.allowed_categories:
            raise HTTPException(status_code=422, detail="Monitoring source category is not allowed by the ingestion policy")
        core = {
            "schema_version": "monitoring-source.v1", "organization_id": organization_id, "project_id": project_id,
            **payload.model_dump(mode="json"), "policy_hash": policy.manifest_hash,
        }
        config_hash = stable_hash(core); source_id = f"msrc_{uuid4().hex[:20]}"; now = _now()
        try:
            with connect() as conn:
                conn.execute(
                    """INSERT INTO monitoring_sources
                    (source_id, organization_id, project_id, policy_id, name, source_type, feed_url, publisher,
                     license_name, license_url, category, poll_interval_minutes, status, config_json, config_hash,
                     created_by_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'paused', ?, ?, ?, ?, ?)""",
                    (source_id, organization_id, project_id, policy.policy_id, payload.name.strip(), payload.source_type,
                     payload.feed_url.strip(), payload.publisher.strip(), payload.license_name.strip(), payload.license_url.strip(),
                     payload.category, payload.poll_interval_minutes, dumps(core), config_hash, actor.user_id, now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(status_code=409, detail="Monitoring source name or immutable configuration already exists") from exc
            raise
        scope_resource(organization_id, "monitoring_source", source_id)
        return self.get_source(organization_id, project_id, source_id, actor)

    def list_sources(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[MonitoringSource]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM monitoring_sources WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, source_id DESC",
                (organization_id, project_id),
            ).fetchall()
        return [_source(row) for row in rows]

    def get_source(self, organization_id: str, project_id: str, source_id: str, actor: UserIdentity) -> MonitoringSource:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitoring_sources WHERE organization_id = ? AND project_id = ? AND source_id = ?",
                (organization_id, project_id, source_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown monitoring source: {source_id}")
        return _source(row)

    def update_source_status(self, organization_id: str, project_id: str, source_id: str, payload: MonitoringSourceStatusRequest, actor: UserIdentity) -> MonitoringSource:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        source = self.get_source(organization_id, project_id, source_id, actor)
        if source.status == "retired":
            raise HTTPException(status_code=409, detail="Retired monitoring sources are immutable")
        now = _now(); next_poll = now if payload.status == "active" else None
        with connect() as conn:
            conn.execute(
                "UPDATE monitoring_sources SET status = ?, next_poll_at = ?, retired_at = CASE WHEN ? = 'retired' THEN ? ELSE retired_at END, updated_at = ? WHERE source_id = ?",
                (payload.status, next_poll, payload.status, now, now, source_id),
            )
        record_security_event(
            "monitoring.source.status", "allowed", actor_user_id=actor.user_id,
            resource_type="monitoring_source", resource_id=source_id,
            detail={"from_status": source.status, "to_status": payload.status},
        )
        return self.get_source(organization_id, project_id, source_id, actor)

    def clone_source(self, organization_id: str, project_id: str, source_id: str, actor: UserIdentity) -> MonitoringSource:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        source = self.get_source(organization_id, project_id, source_id, actor)
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        cloned = self.create_source(organization_id, project_id, MonitoringSourceCreate(
            name=f"{source.name} · {suffix}", source_type=source.source_type, feed_url=source.feed_url,
            publisher=source.publisher, license_name=source.license_name, license_url=source.license_url,
            category=source.category, poll_interval_minutes=source.poll_interval_minutes, policy_id=source.policy_id,
        ), actor)
        with connect() as conn:
            conn.execute("UPDATE monitoring_sources SET parent_source_id = ? WHERE source_id = ?", (source_id, cloned.source_id))
        return self.get_source(organization_id, project_id, cloned.source_id, actor)

    # Watchlists ---------------------------------------------------------------
    def create_watchlist(self, organization_id: str, project_id: str, payload: WatchlistCreate, actor: UserIdentity, *, family_id: str | None = None, parent_id: str | None = None, version: int = 1) -> WatchlistManifest:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        require_resource_scope(organization_id, "project", project_id)
        normalized_rules = []
        seen = set()
        for position, rule in enumerate(payload.rules, start=1):
            _validate_watch_value(rule.candidate_type, rule.canonical_value)
            key = (rule.candidate_type, rule.canonical_value)
            if key in seen:
                raise HTTPException(status_code=422, detail=f"Duplicate watch rule: {rule.candidate_type}/{rule.canonical_value}")
            seen.add(key)
            normalized_rules.append({"position": position, **rule.model_dump(mode="json")})
        family_id = family_id or f"wlf_{uuid4().hex[:20]}"
        manifest = {
            "schema_version": "monitoring-watchlist.v1", "family_id": family_id, "version": version,
            "organization_id": organization_id, "project_id": project_id, "name": payload.name.strip(),
            "rules": normalized_rules,
        }
        manifest_hash = stable_hash(manifest); watchlist_id = f"wl_{manifest_hash[:20]}"; now = _now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO monitoring_watchlists
                (watchlist_id, family_id, organization_id, project_id, parent_watchlist_id, version, name, status,
                 manifest_json, manifest_hash, created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
                (watchlist_id, family_id, organization_id, project_id, parent_id, version, payload.name.strip(),
                 dumps(manifest), manifest_hash, actor.user_id, now),
            )
            for item in normalized_rules:
                rule_hash = stable_hash({"watchlist_hash": manifest_hash, **item})
                conn.execute(
                    """INSERT INTO monitoring_watch_rules
                    (rule_id, watchlist_id, position, candidate_type, canonical_value, severity, rule_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (f"wr_{rule_hash[:20]}", watchlist_id, item["position"], item["candidate_type"],
                     item["canonical_value"], item["severity"], rule_hash, now),
                )
        self.create_subscription(organization_id, NotificationSubscriptionCreate(
            channel="in_app", project_id=project_id, watchlist_id=watchlist_id, min_severity="info",
        ), actor)
        return self.get_watchlist(organization_id, project_id, watchlist_id, actor)

    def list_watchlists(self, organization_id: str, project_id: str, actor: UserIdentity) -> list[WatchlistManifest]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM monitoring_watchlists WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, watchlist_id DESC",
                (organization_id, project_id),
            ).fetchall()
        return [self._watchlist(row) for row in rows]

    def get_watchlist(self, organization_id: str, project_id: str, watchlist_id: str, actor: UserIdentity) -> WatchlistManifest:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitoring_watchlists WHERE organization_id = ? AND project_id = ? AND watchlist_id = ?",
                (organization_id, project_id, watchlist_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown monitoring watchlist: {watchlist_id}")
        return self._watchlist(row)

    def set_watchlist_status(self, organization_id: str, project_id: str, watchlist_id: str, status: str, actor: UserIdentity) -> WatchlistManifest:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        item = self.get_watchlist(organization_id, project_id, watchlist_id, actor)
        if item.status == "retired":
            raise HTTPException(status_code=409, detail="Retired watchlists are immutable")
        if status not in {"active", "paused"}:
            raise HTTPException(status_code=422, detail="Watchlist status action is invalid")
        now = _now()
        with connect() as conn:
            if status == "active":
                conn.execute("UPDATE monitoring_watchlists SET status = 'retired', retired_at = ? WHERE family_id = ? AND status = 'active' AND watchlist_id <> ?", (now, item.family_id, watchlist_id))
            conn.execute("UPDATE monitoring_watchlists SET status = ?, activated_at = CASE WHEN ? = 'active' THEN ? ELSE activated_at END WHERE watchlist_id = ?", (status, status, now, watchlist_id))
        record_security_event(
            "monitoring.watchlist.status", "allowed", actor_user_id=actor.user_id,
            resource_type="monitoring_watchlist", resource_id=watchlist_id,
            detail={"from_status": item.status, "to_status": status, "manifest_hash": item.manifest_hash},
        )
        return self.get_watchlist(organization_id, project_id, watchlist_id, actor)

    def clone_watchlist(self, organization_id: str, project_id: str, watchlist_id: str, actor: UserIdentity) -> WatchlistManifest:
        item = self.get_watchlist(organization_id, project_id, watchlist_id, actor)
        return self.create_watchlist(
            organization_id, project_id,
            WatchlistCreate(name=item.name, rules=[{"candidate_type": rule.candidate_type, "canonical_value": rule.canonical_value, "severity": rule.severity} for rule in item.rules]),
            actor, family_id=item.family_id, parent_id=item.watchlist_id, version=item.version + 1,
        )

    # Poll lifecycle -----------------------------------------------------------
    def enqueue_due_polls(self, *, now: str | None = None) -> int:
        if not continuous_intelligence_enabled():
            return 0
        now = now or _now()
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM monitoring_sources WHERE status = 'active' AND next_poll_at IS NOT NULL AND next_poll_at <= ? ORDER BY next_poll_at, source_id",
                (now,),
            ).fetchall()
        queued = 0
        for row in rows:
            actor = _actor_for_user(row["created_by_user_id"])
            try:
                self.queue_poll(row["organization_id"], row["project_id"], row["source_id"], actor, scheduled_for=row["next_poll_at"])
                queued += 1
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        return queued

    def queue_poll(self, organization_id: str, project_id: str, source_id: str, actor: UserIdentity, *, scheduled_for: str | None = None, parent_poll_id: str | None = None) -> MonitoringPollJob:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        if not continuous_intelligence_enabled():
            raise HTTPException(status_code=409, detail="Continuous intelligence network access is disabled")
        source = self.get_source(organization_id, project_id, source_id, actor)
        if source.status not in {"active", "degraded"}:
            raise HTTPException(status_code=409, detail=f"Monitoring source cannot poll from status {source.status}")
        scheduled_for = scheduled_for or _now()
        request_hash = stable_hash({"source_hash": source.config_hash, "scheduled_for": scheduled_for, "parent_poll_id": parent_poll_id})
        poll_id = f"mpoll_{uuid4().hex[:20]}"; now = _now()
        try:
            with connect() as conn:
                conn.execute(
                    """INSERT INTO monitoring_poll_jobs
                    (poll_id, organization_id, project_id, source_id, parent_poll_id, status, scheduled_for,
                     request_hash, created_by_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                    (poll_id, organization_id, project_id, source_id, parent_poll_id, scheduled_for, request_hash, actor.user_id, now, now),
                )
        except Exception as exc:
            if "UNIQUE" in str(exc).upper():
                raise HTTPException(status_code=409, detail="A poll is already queued for this source and schedule") from exc
            raise
        with connect() as conn:
            if source.status == "active":
                conn.execute(
                    "UPDATE monitoring_sources SET next_poll_at = ?, updated_at = ? WHERE source_id = ? AND (next_poll_at IS NULL OR next_poll_at <= ?)",
                    ((datetime.now(timezone.utc) + timedelta(minutes=source.poll_interval_minutes)).isoformat(timespec="milliseconds"), _now(), source_id, scheduled_for),
                )
        self.append_poll_event(poll_id, "WORKER", "Feed poll queued", "持续情报采集任务已进入 ingestion worker 队列。", {"source_id": source_id})
        return self.get_poll(organization_id, project_id, poll_id, actor)

    def list_polls(self, organization_id: str, project_id: str, actor: UserIdentity, limit: int = 100) -> list[MonitoringPollJob]:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            rows = conn.execute(
                "SELECT * FROM monitoring_poll_jobs WHERE organization_id = ? AND project_id = ? ORDER BY created_at DESC, poll_id DESC LIMIT ?",
                (organization_id, project_id, max(1, min(limit, 500))),
            ).fetchall()
        return [_poll(row) for row in rows]

    def get_poll(self, organization_id: str, project_id: str, poll_id: str, actor: UserIdentity) -> MonitoringPollJob:
        self._project_access(organization_id, project_id, actor)
        with connect() as conn:
            row = conn.execute(
                "SELECT * FROM monitoring_poll_jobs WHERE organization_id = ? AND project_id = ? AND poll_id = ?",
                (organization_id, project_id, poll_id),
            ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown monitoring poll: {poll_id}")
        return _poll(row)

    def list_poll_events(self, organization_id: str, project_id: str, poll_id: str, actor: UserIdentity, *, after_seq: int = 0) -> list[MonitoringPollEvent]:
        self.get_poll(organization_id, project_id, poll_id, actor)
        with connect() as conn:
            rows = conn.execute("SELECT * FROM monitoring_poll_events WHERE poll_id = ? AND seq > ? ORDER BY seq", (poll_id, max(0, after_seq))).fetchall()
        return [_poll_event(row) for row in rows]

    def append_poll_event(self, poll_id: str, event_type: str, title: str, detail: str, payload: dict) -> MonitoringPollEvent:
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            conn.execute("INSERT INTO monitoring_poll_event_counters(poll_id, next_seq) VALUES (?, 1) ON CONFLICT(poll_id) DO NOTHING", (poll_id,))
            if is_postgres_url():
                counter = conn.execute("UPDATE monitoring_poll_event_counters SET next_seq = next_seq + 1 WHERE poll_id = ? RETURNING next_seq - 1 AS seq", (poll_id,)).fetchone()
                seq = int(counter["seq"])
            else:
                counter = conn.execute("SELECT next_seq FROM monitoring_poll_event_counters WHERE poll_id = ?", (poll_id,)).fetchone()
                seq = int(counter["next_seq"]); conn.execute("UPDATE monitoring_poll_event_counters SET next_seq = ? WHERE poll_id = ?", (seq + 1, poll_id))
            created_at = _now()
            conn.execute(
                "INSERT INTO monitoring_poll_events(poll_id, seq, event_type, title, detail, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (poll_id, seq, event_type, title, detail, dumps(payload), created_at),
            )
        return MonitoringPollEvent(poll_id=poll_id, seq=seq, event_type=event_type, title=title, detail=detail, payload=payload, created_at=created_at)

    def recover_stale_work(self) -> int:
        now = _now(); recovered = 0
        with connect() as conn:
            rows = conn.execute("SELECT poll_id FROM monitoring_poll_jobs WHERE status = 'running' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?", (now,)).fetchall()
            for row in rows:
                conn.execute("UPDATE monitoring_poll_jobs SET status = 'queued', worker_id = NULL, lease_expires_at = NULL, updated_at = ?, error_code = 'lease_expired' WHERE poll_id = ?", (now, row["poll_id"]))
                recovered += 1
            deliveries = conn.execute("SELECT delivery_id FROM webhook_deliveries WHERE status = 'delivering' AND lease_expires_at IS NOT NULL AND lease_expires_at < ?", (now,)).fetchall()
            for row in deliveries:
                conn.execute("UPDATE webhook_deliveries SET status = 'retrying', worker_id = NULL, lease_expires_at = NULL, next_attempt_at = ?, updated_at = ?, error_code = 'lease_expired' WHERE delivery_id = ?", (now, now, row["delivery_id"]))
                recovered += 1
        return recovered

    def claim_next_poll(self, worker_id: str) -> tuple[str, str, str] | None:
        self.recover_stale_work(); now = _now()
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            lock = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
            row = conn.execute(f"SELECT poll_id, organization_id, project_id FROM monitoring_poll_jobs WHERE status = 'queued' AND scheduled_for <= ? ORDER BY scheduled_for, poll_id LIMIT 1{lock}", (now,)).fetchone()
            if row is None:
                return None
            changed = conn.execute(
                "UPDATE monitoring_poll_jobs SET status = 'running', worker_id = ?, lease_expires_at = ?, attempt_count = attempt_count + 1, started_at = COALESCE(started_at, ?), updated_at = ? WHERE poll_id = ? AND status = 'queued'",
                (worker_id, _after(LEASE_SECONDS), now, now, row["poll_id"]),
            )
        return (row["organization_id"], row["project_id"], row["poll_id"]) if changed.rowcount == 1 else None

    def execute_claimed_poll(self, organization_id: str, project_id: str, poll_id: str, worker_id: str) -> MonitoringPollJob:
        with connect() as conn:
            row = conn.execute("SELECT created_by_user_id FROM monitoring_poll_jobs WHERE poll_id = ?", (poll_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown monitoring poll: {poll_id}")
        actor = _actor_for_user(row["created_by_user_id"])
        poll = self.get_poll(organization_id, project_id, poll_id, actor)
        if poll.status != "running":
            raise HTTPException(status_code=409, detail=f"Monitoring poll cannot execute from {poll.status}")
        source = self.get_source(organization_id, project_id, poll.source_id, actor)
        self.append_poll_event(poll_id, "WORKER", "Feed poll started", "开始执行受限网络读取、去重和确定性监测。", {"worker_id": worker_id})
        try:
            cutoff = _now()
            fetched = fetch_feed(source.feed_url, etag=source.etag, last_modified=source.last_modified)
            if fetched.status_code == 304:
                result = {"outcome": "not_modified", "source_hash": source.config_hash}
                self._complete_poll(poll, source, fetched, result, discovered=0, changed=0, matched=0, materialized=0)
                return self.get_poll(organization_id, project_id, poll_id, actor)
            response_hash = hashlib.sha256(fetched.content).hexdigest()
            entries = parse_feed(fetched.content, source.source_type, cutoff_at=cutoff)
            changed = matched = materialized = 0
            entry_results = []
            for entry in entries:
                outcome = self._process_entry(source, poll, entry, actor, cutoff)
                entry_results.append(outcome)
                changed += int(outcome["changed"]); matched += int(outcome["matched"]); materialized += int(outcome["materialized"])
            result = {
                "schema_version": "monitoring-poll-result.v1", "source_hash": source.config_hash,
                "response_hash": response_hash, "entry_results": entry_results,
            }
            fetched = type(fetched)(fetched.status_code, fetched.content, fetched.content_type, fetched.etag, fetched.last_modified, fetched.final_url)
            self._complete_poll(poll, source, fetched, result, discovered=len(entries), changed=changed, matched=matched, materialized=materialized)
        except Exception as exc:
            self._fail_poll(poll, source, exc)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=422, detail=redact_secrets(str(exc), max_length=500) or type(exc).__name__) from exc
        return self.get_poll(organization_id, project_id, poll_id, actor)

    def _process_entry(self, source: MonitoringSource, poll: MonitoringPollJob, entry: dict, actor: UserIdentity, cutoff: str) -> dict:
        with connect() as conn:
            existing = conn.execute(
                "SELECT * FROM monitoring_entries WHERE source_id = ? AND stable_key = ? AND content_hash = ?",
                (source.source_id, entry["stable_key"], entry["content_hash"]),
            ).fetchone()
            revision_row = conn.execute("SELECT COALESCE(MAX(revision), 0) AS revision FROM monitoring_entries WHERE source_id = ? AND stable_key = ?", (source.source_id, entry["stable_key"])).fetchone()
        if existing:
            with connect() as conn:
                conn.execute("UPDATE monitoring_entries SET last_seen_at = ? WHERE entry_id = ?", (_now(), existing["entry_id"]))
            return {"entry_id": existing["entry_id"], "entry_hash": entry["content_hash"], "changed": False, "matched": bool(loads(existing["match_json"], [])), "materialized": bool(existing["document_id"]), "duplicate": True}
        matches_by_watchlist = self._match_entry(source.organization_id, source.project_id, entry["text"], actor)
        flat_matches = [match for group in matches_by_watchlist.values() for match in group]
        entry_id = f"ment_{uuid4().hex[:20]}"; revision = int(revision_row["revision"] or 0) + 1; now = _now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO monitoring_entries
                (entry_id, source_id, poll_id, stable_key, revision, canonical_url, title, published_at, content_hash,
                 metadata_json, match_json, materialization_status, first_seen_at, last_seen_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry_id, source.source_id, poll.poll_id, entry["stable_key"], revision, entry["canonical_url"], entry["title"],
                 entry["published_at"], entry["content_hash"], dumps({"text_chars": len(entry["text"])}), dumps(flat_matches),
                 "pending" if flat_matches else "unmatched", now, now, now),
            )
        if not flat_matches:
            return {"entry_id": entry_id, "entry_hash": entry["content_hash"], "changed": True, "matched": False, "materialized": False, "duplicate": False}
        markdown = render_entry_markdown(entry, publisher=source.publisher, source_url=source.feed_url)
        upload = self.compiler.register_generated_document(
            source.organization_id, source.project_id, markdown, actor,
            filename=f"feed-{entry_id}.md", title=entry["title"], category=source.category,
            publisher=source.publisher, license_name=source.license_name, license_url=source.license_url,
            observed_at=entry["published_at"], cutoff_at=cutoff,
        )
        extraction = self.compiler.create_extraction_job(source.organization_id, source.project_id, upload.document.document_id, actor, provider_override="disabled")
        with connect() as conn:
            conn.execute(
                "UPDATE monitoring_entries SET materialization_status = 'queued', document_id = ?, extraction_job_id = ? WHERE entry_id = ?",
                (upload.document.document_id, extraction.job_id, entry_id),
            )
        for watchlist_id, matches in matches_by_watchlist.items():
            self._upsert_alert(source, watchlist_id, entry_id, entry, matches, upload.document.document_id, extraction.job_id)
        return {"entry_id": entry_id, "entry_hash": entry["content_hash"], "changed": True, "matched": True, "materialized": True, "duplicate": False}

    def _match_entry(self, organization_id: str, project_id: str, text: str, actor: UserIdentity) -> dict[str, list[dict]]:
        with connect() as conn:
            rows = conn.execute("SELECT * FROM monitoring_watchlists WHERE organization_id = ? AND project_id = ? AND status = 'active'", (organization_id, project_id)).fetchall()
        extracted = deterministic_candidates([{"text": text, "locator": {"kind": "monitoring_preview"}}], ["monitoring-preview"])
        values = {(item["candidate_type"], item["canonical_value"]) for item in extracted}
        result: dict[str, list[dict]] = {}
        for row in rows:
            watchlist = self._watchlist(row)
            matches = [rule.model_dump(mode="json") for rule in watchlist.rules if (rule.candidate_type, rule.canonical_value) in values]
            if matches:
                result[watchlist.watchlist_id] = matches
        return result

    def _upsert_alert(self, source: MonitoringSource, watchlist_id: str, entry_id: str, entry: dict, matches: list[dict], document_id: str, extraction_job_id: str) -> IntelligenceAlert:
        severity = max((item["severity"] for item in matches), key=lambda item: SEVERITY_RANK[item])
        now = _now()
        with connect() as conn:
            existing = conn.execute("SELECT * FROM intelligence_alerts WHERE watchlist_id = ? AND source_id = ? AND stable_key = ?", (watchlist_id, source.source_id, entry["stable_key"])).fetchone()
            lineage = {"document_id": document_id, "extraction_job_id": extraction_job_id, "snapshot_ids": [], "candidate_ids": [], "pipeline_status": "extracting"}
            if existing:
                conn.execute(
                    """UPDATE intelligence_alerts SET status = 'open', severity = ?, title = ?, summary = ?,
                    revision_count = revision_count + 1, latest_entry_id = ?, latest_entry_hash = ?, match_json = ?,
                    lineage_json = ?, updated_at = ?, dismissed_by_user_id = NULL, dismissed_at = NULL
                    WHERE alert_id = ?""",
                    (severity, entry["title"], _summary(entry["text"]), entry_id, entry["content_hash"], dumps(matches), dumps(lineage), now, existing["alert_id"]),
                )
                alert_id = existing["alert_id"]; event_type = "alert.updated"
            else:
                alert_hash = stable_hash({"watchlist_id": watchlist_id, "source_hash": source.config_hash, "stable_key": entry["stable_key"]})
                alert_id = f"ial_{alert_hash[:20]}"
                conn.execute(
                    """INSERT INTO intelligence_alerts
                    (alert_id, organization_id, project_id, watchlist_id, source_id, stable_key, status, severity,
                     title, summary, latest_entry_id, latest_entry_hash, match_json, lineage_json, alert_hash, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (alert_id, source.organization_id, source.project_id, watchlist_id, source.source_id, entry["stable_key"], severity,
                     entry["title"], _summary(entry["text"]), entry_id, entry["content_hash"], dumps(matches), dumps(lineage), alert_hash, now, now),
                )
                event_type = "alert.opened"
        self.append_alert_event(alert_id, event_type, {"entry_hash": entry["content_hash"], "matches": matches, "lineage": lineage}, entry_id=entry_id)
        alert = self._get_alert_unscoped(alert_id)
        self._dispatch_alert(alert, event_type)
        return alert

    def _complete_poll(self, poll: MonitoringPollJob, source: MonitoringSource, fetched, result: dict, *, discovered: int, changed: int, matched: int, materialized: int) -> None:
        now = _now(); result_hash = stable_hash(result)
        next_poll = (datetime.now(timezone.utc) + timedelta(minutes=source.poll_interval_minutes)).isoformat(timespec="milliseconds")
        with connect() as conn:
            conn.execute(
                """UPDATE monitoring_poll_jobs SET status = 'completed', response_status = ?, response_hash = ?,
                discovered_count = ?, changed_count = ?, matched_count = ?, materialized_count = ?, result_json = ?,
                result_hash = ?, completed_at = ?, updated_at = ?, lease_expires_at = NULL WHERE poll_id = ?""",
                (fetched.status_code, hashlib.sha256(fetched.content).hexdigest() if fetched.content else None, discovered, changed,
                 matched, materialized, dumps(result), result_hash, now, now, poll.poll_id),
            )
            conn.execute(
                """UPDATE monitoring_sources SET status = 'active', etag = COALESCE(?, etag), last_modified = COALESCE(?, last_modified),
                consecutive_failures = 0, last_error_code = NULL, last_polled_at = ?, next_poll_at = ?, updated_at = ? WHERE source_id = ?""",
                (fetched.etag, fetched.last_modified, now, next_poll, now, source.source_id),
            )
        self.append_poll_event(poll.poll_id, "SNAPSHOT", "Feed poll committed", "条目版本、告警与受治理材料引用已原子记录。", {"result_hash": result_hash, "discovered": discovered, "changed": changed, "matched": matched})

    def _fail_poll(self, poll: MonitoringPollJob, source: MonitoringSource, exc: Exception) -> None:
        now = _now(); failures = source.consecutive_failures + 1
        delay = BACKOFF_MINUTES[min(failures - 1, len(BACKOFF_MINUTES) - 1)]
        next_poll = (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat(timespec="milliseconds")
        safe = redact_secrets(str(exc), max_length=500) or type(exc).__name__
        next_status = "degraded" if failures >= 5 else source.status
        with connect() as conn:
            conn.execute("UPDATE monitoring_poll_jobs SET status = 'failed', error_code = ?, error_message = ?, completed_at = ?, updated_at = ?, lease_expires_at = NULL WHERE poll_id = ?", (type(exc).__name__, safe, now, now, poll.poll_id))
            conn.execute("UPDATE monitoring_sources SET status = ?, consecutive_failures = ?, last_error_code = ?, last_polled_at = ?, next_poll_at = ?, updated_at = ? WHERE source_id = ?", (next_status, failures, type(exc).__name__, now, next_poll, now, source.source_id))
        self.append_poll_event(poll.poll_id, "CONSISTENCY", "Feed poll failed closed", "外部响应未通过持续情报安全或完整性门禁。", {"error_code": type(exc).__name__, "retry_at": next_poll})
        if failures >= 5:
            create_review_case("monitoring_source_degraded", "monitoring_source", source.source_id, "Monitoring source failed five consecutive polls", severity="high", payload={"poll_id": poll.poll_id, "error_code": type(exc).__name__})

    # Alert lineage and triage -------------------------------------------------
    def finalize_extraction(self, extraction_job_id: str) -> int:
        with connect() as conn:
            entries = conn.execute("SELECT * FROM monitoring_entries WHERE extraction_job_id = ?", (extraction_job_id,)).fetchall()
            job = conn.execute("SELECT status, error_code FROM document_extraction_jobs WHERE job_id = ?", (extraction_job_id,)).fetchone()
        if not entries or job is None:
            return 0
        updated = 0
        for entry in entries:
            with connect() as conn:
                alert_rows = conn.execute("SELECT * FROM intelligence_alerts WHERE latest_entry_id = ?", (entry["entry_id"],)).fetchall()
                extraction = conn.execute("SELECT * FROM document_extractions WHERE job_id = ?", (extraction_job_id,)).fetchone()
                candidate_rows = conn.execute("SELECT candidate_id FROM scenario_candidates WHERE extraction_id = ? ORDER BY candidate_id", (extraction["extraction_id"],)).fetchall() if extraction else []
            if job["status"] == "completed" and extraction:
                lineage = {
                    "document_id": entry["document_id"], "extraction_job_id": extraction_job_id,
                    "extraction_id": extraction["extraction_id"], "snapshot_ids": loads(extraction["snapshot_ids_json"], []),
                    "candidate_ids": [row["candidate_id"] for row in candidate_rows], "pipeline_status": "ready",
                }
                entry_status = "ready"; event_type = "candidate.ready"
            elif job["status"] in {"failed", "cancelled"}:
                lineage = {"document_id": entry["document_id"], "extraction_job_id": extraction_job_id, "snapshot_ids": [], "candidate_ids": [], "pipeline_status": "failed", "error_code": job["error_code"]}
                entry_status = "failed"; event_type = "pipeline.failed"
            else:
                continue
            with connect() as conn:
                conn.execute("UPDATE monitoring_entries SET materialization_status = ? WHERE entry_id = ?", (entry_status, entry["entry_id"]))
                conn.execute("UPDATE intelligence_alerts SET lineage_json = ?, updated_at = ? WHERE latest_entry_id = ?", (dumps(lineage), _now(), entry["entry_id"]))
            for row in alert_rows:
                self.append_alert_event(row["alert_id"], event_type, {"entry_hash": entry["content_hash"], "lineage": lineage}, entry_id=entry["entry_id"])
                self._dispatch_alert(self._get_alert_unscoped(row["alert_id"]), event_type)
                updated += 1
        return updated

    def list_alerts(self, organization_id: str, project_id: str, actor: UserIdentity, *, status: str | None = None, limit: int = 200) -> list[IntelligenceAlert]:
        self._project_access(organization_id, project_id, actor)
        sql = "SELECT * FROM intelligence_alerts WHERE organization_id = ? AND project_id = ?"; params: list = [organization_id, project_id]
        if status:
            sql += " AND status = ?"; params.append(status)
        sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, updated_at DESC LIMIT ?"; params.append(max(1, min(limit, 500)))
        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_alert(row) for row in rows]

    def get_alert(self, organization_id: str, project_id: str, alert_id: str, actor: UserIdentity) -> IntelligenceAlert:
        self._project_access(organization_id, project_id, actor)
        alert = self._get_alert_unscoped(alert_id)
        if alert.organization_id != organization_id or alert.project_id != project_id:
            raise HTTPException(status_code=404, detail=f"Unknown intelligence alert: {alert_id}")
        return alert

    def _get_alert_unscoped(self, alert_id: str) -> IntelligenceAlert:
        with connect() as conn:
            row = conn.execute("SELECT * FROM intelligence_alerts WHERE alert_id = ?", (alert_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown intelligence alert: {alert_id}")
        return _alert(row)

    def list_alert_events(self, organization_id: str, project_id: str, alert_id: str, actor: UserIdentity) -> list[IntelligenceAlertEvent]:
        self.get_alert(organization_id, project_id, alert_id, actor)
        with connect() as conn:
            rows = conn.execute("SELECT * FROM intelligence_alert_events WHERE alert_id = ? ORDER BY seq", (alert_id,)).fetchall()
        return [_alert_event(row) for row in rows]

    def append_alert_event(self, alert_id: str, event_type: str, payload: dict, *, entry_id: str | None = None, actor_user_id: str | None = None) -> IntelligenceAlertEvent:
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM intelligence_alert_events WHERE alert_id = ?", (alert_id,)).fetchone()
            seq = int(row["seq"]); now = _now(); event_hash = stable_hash({"alert_id": alert_id, "seq": seq, "event_type": event_type, "entry_id": entry_id, "actor": actor_user_id, "payload": payload})
            conn.execute("INSERT INTO intelligence_alert_events(alert_id, seq, event_type, entry_id, actor_user_id, payload_json, event_hash, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (alert_id, seq, event_type, entry_id, actor_user_id, dumps(payload), event_hash, now))
        return IntelligenceAlertEvent(alert_id=alert_id, seq=seq, event_type=event_type, entry_id=entry_id, actor_user_id=actor_user_id, payload=payload, event_hash=event_hash, created_at=now)

    def set_alert_status(self, organization_id: str, project_id: str, alert_id: str, status: str, actor: UserIdentity) -> IntelligenceAlert:
        require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
        self.get_alert(organization_id, project_id, alert_id, actor)
        if status not in {"acknowledged", "dismissed"}:
            raise HTTPException(status_code=422, detail="Alert status action is invalid")
        now = _now()
        with connect() as conn:
            if status == "acknowledged":
                conn.execute("UPDATE intelligence_alerts SET status = ?, acknowledged_by_user_id = ?, acknowledged_at = ?, updated_at = ? WHERE alert_id = ?", (status, actor.user_id, now, now, alert_id))
            else:
                conn.execute("UPDATE intelligence_alerts SET status = ?, dismissed_by_user_id = ?, dismissed_at = ?, updated_at = ? WHERE alert_id = ?", (status, actor.user_id, now, now, alert_id))
        self.append_alert_event(alert_id, f"alert.{status}", {}, actor_user_id=actor.user_id)
        return self.get_alert(organization_id, project_id, alert_id, actor)

    # Notifications and webhooks ---------------------------------------------
    def create_subscription(self, organization_id: str, payload: NotificationSubscriptionCreate, actor: UserIdentity) -> NotificationSubscription:
        if payload.channel == "webhook":
            require_organization_role(organization_id, actor, {"owner", "admin"})
            validate_remote_url(payload.endpoint_url or "", webhook=True)
        else:
            require_organization_role(organization_id, actor, READ_ROLES)
        if payload.project_id:
            require_resource_scope(organization_id, "project", payload.project_id)
        if payload.watchlist_id:
            with connect() as conn:
                watch = conn.execute("SELECT organization_id, project_id FROM monitoring_watchlists WHERE watchlist_id = ?", (payload.watchlist_id,)).fetchone()
            if watch is None or watch["organization_id"] != organization_id:
                raise HTTPException(status_code=404, detail="Unknown notification watchlist")
        core = {"schema_version": "alert-subscription.v1", "organization_id": organization_id, "user_id": actor.user_id if payload.channel == "in_app" else None, **payload.model_dump(mode="json")}
        config_hash = stable_hash(core)
        with connect() as conn:
            existing = conn.execute("SELECT * FROM alert_subscriptions WHERE config_hash = ?", (config_hash,)).fetchone()
        if existing:
            return _subscription(existing)
        subscription_id = f"sub_{config_hash[:20]}"; now = _now()
        with connect() as conn:
            conn.execute(
                """INSERT INTO alert_subscriptions
                (subscription_id, organization_id, project_id, watchlist_id, channel, subscriber_user_id,
                 endpoint_url, secret_ref, min_severity, status, config_json, config_hash, created_by_user_id,
                 created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                (subscription_id, organization_id, payload.project_id, payload.watchlist_id, payload.channel,
                 actor.user_id if payload.channel == "in_app" else None, payload.endpoint_url, payload.secret_ref,
                 payload.min_severity, dumps(core), config_hash, actor.user_id, now, now),
            )
        return self.get_subscription(organization_id, subscription_id, actor)

    def list_subscriptions(self, organization_id: str, actor: UserIdentity) -> list[NotificationSubscription]:
        require_organization_role(organization_id, actor, READ_ROLES)
        with connect() as conn:
            if _organization_role(organization_id, actor) in {"owner", "admin"}:
                rows = conn.execute("SELECT * FROM alert_subscriptions WHERE organization_id = ? ORDER BY created_at DESC", (organization_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM alert_subscriptions WHERE organization_id = ? AND channel = 'in_app' AND subscriber_user_id = ? ORDER BY created_at DESC", (organization_id, actor.user_id)).fetchall()
        return [_subscription(row) for row in rows]

    def get_subscription(self, organization_id: str, subscription_id: str, actor: UserIdentity) -> NotificationSubscription:
        subscriptions = self.list_subscriptions(organization_id, actor)
        item = next((sub for sub in subscriptions if sub.subscription_id == subscription_id), None)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Unknown notification subscription: {subscription_id}")
        return item

    def pause_subscription(self, organization_id: str, subscription_id: str, actor: UserIdentity) -> NotificationSubscription:
        item = self.get_subscription(organization_id, subscription_id, actor)
        if item.channel == "webhook":
            require_organization_role(organization_id, actor, {"owner", "admin"})
        with connect() as conn:
            conn.execute("UPDATE alert_subscriptions SET status = CASE WHEN status = 'active' THEN 'paused' ELSE 'active' END, updated_at = ? WHERE subscription_id = ?", (_now(), subscription_id))
        return self.get_subscription(organization_id, subscription_id, actor)

    def test_subscription(self, organization_id: str, subscription_id: str, actor: UserIdentity) -> dict:
        item = self.get_subscription(organization_id, subscription_id, actor)
        if item.channel != "webhook":
            raise HTTPException(status_code=409, detail="Only webhook subscriptions support test delivery")
        require_organization_role(organization_id, actor, {"owner", "admin"})
        payload = {"schema_version": "worldpulse-webhook.v1", "event_type": "subscription.test", "subscription_id": subscription_id, "created_at": _now()}
        delivery_id = self._queue_webhook(item, None, "subscription.test", "test", payload)
        return {"status": "queued", "delivery_id": delivery_id}

    def list_notifications(self, organization_id: str, actor: UserIdentity, *, after_seq: int = 0, unread_only: bool = False, limit: int = 200) -> list[InAppNotification]:
        require_organization_role(organization_id, actor, READ_ROLES)
        sql = "SELECT * FROM in_app_notifications WHERE organization_id = ? AND user_id = ? AND seq > ?"; params: list = [organization_id, actor.user_id, max(0, after_seq)]
        if unread_only:
            sql += " AND read_at IS NULL"
        sql += " ORDER BY seq DESC LIMIT ?"; params.append(max(1, min(limit, 500)))
        with connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_notification(row) for row in reversed(rows)]

    def mark_notification_read(self, organization_id: str, notification_id: str, actor: UserIdentity) -> InAppNotification:
        require_organization_role(organization_id, actor, READ_ROLES)
        with connect() as conn:
            changed = conn.execute("UPDATE in_app_notifications SET read_at = COALESCE(read_at, ?) WHERE organization_id = ? AND user_id = ? AND notification_id = ?", (_now(), organization_id, actor.user_id, notification_id))
            row = conn.execute("SELECT * FROM in_app_notifications WHERE notification_id = ? AND user_id = ?", (notification_id, actor.user_id)).fetchone()
        if changed.rowcount != 1 or row is None:
            raise HTTPException(status_code=404, detail=f"Unknown notification: {notification_id}")
        return _notification(row)

    def mark_all_notifications_read(self, organization_id: str, actor: UserIdentity) -> dict:
        require_organization_role(organization_id, actor, READ_ROLES)
        with connect() as conn:
            changed = conn.execute("UPDATE in_app_notifications SET read_at = ? WHERE organization_id = ? AND user_id = ? AND read_at IS NULL", (_now(), organization_id, actor.user_id))
        return {"updated": changed.rowcount}

    def _dispatch_alert(self, alert: IntelligenceAlert, event_type: str) -> None:
        with connect() as conn:
            rows = conn.execute(
                """SELECT * FROM alert_subscriptions WHERE organization_id = ? AND status = 'active'
                AND (project_id IS NULL OR project_id = ?) AND (watchlist_id IS NULL OR watchlist_id = ?)""",
                (alert.organization_id, alert.project_id, alert.watchlist_id),
            ).fetchall()
        payload = {
            "schema_version": "worldpulse-webhook.v1", "event_type": event_type, "alert_id": alert.alert_id,
            "organization_id": alert.organization_id, "project_id": alert.project_id, "watchlist_id": alert.watchlist_id,
            "source_id": alert.source_id, "severity": alert.severity, "title": alert.title,
            "entry_hash": alert.latest_entry_hash, "matches": alert.matches,
            "deep_link": f"/projects/{alert.project_id}/war-room/intelligence?alert={alert.alert_id}", "created_at": _now(),
        }
        for row in rows:
            subscription = _subscription(row)
            if SEVERITY_RANK[alert.severity] < SEVERITY_RANK[subscription.min_severity]:
                continue
            if subscription.channel == "in_app":
                self._create_in_app_notification(subscription, alert, event_type, payload)
            else:
                self._queue_webhook(subscription, alert, event_type, alert.latest_entry_hash, payload)

    def _create_in_app_notification(self, subscription: NotificationSubscription, alert: IntelligenceAlert, event_type: str, payload: dict) -> None:
        user_id = subscription.subscriber_user_id
        if not user_id:
            return
        now = _now(); payload_hash = stable_hash(payload); notification_id = f"ntf_{uuid4().hex[:20]}"
        try:
            with connect() as conn:
                if not is_postgres_url():
                    conn.execute("BEGIN IMMEDIATE")
                conn.execute("INSERT INTO organization_notification_counters(organization_id, next_seq) VALUES (?, 1) ON CONFLICT(organization_id) DO NOTHING", (alert.organization_id,))
                if is_postgres_url():
                    row = conn.execute("UPDATE organization_notification_counters SET next_seq = next_seq + 1 WHERE organization_id = ? RETURNING next_seq - 1 AS seq", (alert.organization_id,)).fetchone(); seq = int(row["seq"])
                else:
                    row = conn.execute("SELECT next_seq FROM organization_notification_counters WHERE organization_id = ?", (alert.organization_id,)).fetchone(); seq = int(row["next_seq"])
                    conn.execute("UPDATE organization_notification_counters SET next_seq = ? WHERE organization_id = ?", (seq + 1, alert.organization_id))
                conn.execute(
                    """INSERT INTO in_app_notifications
                    (notification_id, organization_id, seq, user_id, alert_id, event_type, entry_hash, title, body,
                     severity, deep_link, payload_json, payload_hash, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (notification_id, alert.organization_id, seq, user_id, alert.alert_id, event_type, alert.latest_entry_hash,
                     alert.title, alert.summary, alert.severity, payload["deep_link"], dumps(payload), payload_hash, now),
                )
        except Exception as exc:
            if "UNIQUE" not in str(exc).upper():
                raise

    def _queue_webhook(self, subscription: NotificationSubscription, alert: IntelligenceAlert | None, event_type: str, entry_hash: str, payload: dict) -> str:
        payload_hash = stable_hash(payload); delivery_id = f"whd_{uuid4().hex[:20]}"; now = _now()
        alert_id = alert.alert_id if alert else "subscription-test"
        with connect() as conn:
            existing = conn.execute("SELECT delivery_id FROM webhook_deliveries WHERE subscription_id = ? AND alert_id = ? AND event_type = ? AND entry_hash = ?", (subscription.subscription_id, alert_id, event_type, entry_hash)).fetchone()
            if existing:
                return existing["delivery_id"]
            # Test deliveries need a real alert FK. Use the most recent project alert when available.
            if alert is None:
                row = conn.execute("SELECT alert_id FROM intelligence_alerts WHERE organization_id = ? ORDER BY updated_at DESC LIMIT 1", (subscription.organization_id,)).fetchone()
                if row is None:
                    raise HTTPException(status_code=409, detail="Webhook test requires at least one intelligence alert")
                alert_id = row["alert_id"]
            conn.execute(
                """INSERT INTO webhook_deliveries
                (delivery_id, subscription_id, alert_id, event_type, entry_hash, status, next_attempt_at,
                 payload_json, payload_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?)""",
                (delivery_id, subscription.subscription_id, alert_id, event_type, entry_hash, now, dumps(payload), payload_hash, now, now),
            )
        return delivery_id

    def claim_next_webhook(self, worker_id: str) -> str | None:
        self.recover_stale_work(); now = _now()
        with connect() as conn:
            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            lock = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
            row = conn.execute(f"SELECT delivery_id FROM webhook_deliveries WHERE status IN ('queued','retrying') AND next_attempt_at <= ? ORDER BY next_attempt_at, delivery_id LIMIT 1{lock}", (now,)).fetchone()
            if row is None:
                return None
            changed = conn.execute("UPDATE webhook_deliveries SET status = 'delivering', worker_id = ?, lease_expires_at = ?, attempt_count = attempt_count + 1, updated_at = ? WHERE delivery_id = ? AND status IN ('queued','retrying')", (worker_id, _after(LEASE_SECONDS), now, row["delivery_id"]))
        return row["delivery_id"] if changed.rowcount == 1 else None

    def execute_claimed_webhook(self, delivery_id: str, worker_id: str) -> WebhookDelivery:
        with connect() as conn:
            row = conn.execute("SELECT d.*, s.endpoint_url, s.secret_ref, s.status AS subscription_status FROM webhook_deliveries d JOIN alert_subscriptions s ON s.subscription_id = d.subscription_id WHERE d.delivery_id = ?", (delivery_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown webhook delivery: {delivery_id}")
        if row["subscription_status"] != "active":
            with connect() as conn:
                conn.execute("UPDATE webhook_deliveries SET status = 'cancelled', updated_at = ?, lease_expires_at = NULL WHERE delivery_id = ?", (_now(), delivery_id))
            return self.get_webhook_delivery(delivery_id)
        endpoint = validate_remote_url(row["endpoint_url"], resolve_dns=True, webhook=True)
        secret = os.getenv(f"WORLDPULSE_WEBHOOK_SECRET_{row['secret_ref']}", "")
        if not secret:
            self._retry_webhook(row, RuntimeError("webhook_secret_unavailable"))
            return self.get_webhook_delivery(delivery_id)
        body = json.dumps(loads(row["payload_json"], {}), ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = hmac.new(secret.encode("utf-8"), timestamp.encode("ascii") + b"." + body, hashlib.sha256).hexdigest()
        session = requests.Session(); session.trust_env = False
        try:
            response = session.post(endpoint, data=body, headers={
                "Content-Type": "application/json", "User-Agent": "WorldPulse/1.10 webhook",
                "X-WorldPulse-Event": row["event_type"], "X-WorldPulse-Delivery": delivery_id,
                "X-WorldPulse-Timestamp": timestamp, "X-WorldPulse-Signature": f"v1={signature}",
            }, timeout=(5, 15), allow_redirects=False)
            if response.status_code < 200 or response.status_code >= 300:
                raise RuntimeError(f"webhook_http_{response.status_code}")
            now = _now()
            with connect() as conn:
                conn.execute("UPDATE webhook_deliveries SET status = 'delivered', response_status = ?, delivered_at = ?, updated_at = ?, lease_expires_at = NULL, error_code = NULL, error_message = NULL WHERE delivery_id = ?", (response.status_code, now, now, delivery_id))
        except Exception as exc:
            self._retry_webhook(row, exc)
        finally:
            session.close()
        return self.get_webhook_delivery(delivery_id)

    def _retry_webhook(self, row, exc: Exception) -> None:
        attempts = int(row["attempt_count"])
        terminal = attempts >= 5
        status = "failed" if terminal else "retrying"
        delay = BACKOFF_MINUTES[min(max(attempts - 1, 0), len(BACKOFF_MINUTES) - 1)]
        next_attempt = (datetime.now(timezone.utc) + timedelta(minutes=delay)).isoformat(timespec="milliseconds")
        safe = redact_secrets(str(exc), max_length=300) or type(exc).__name__
        with connect() as conn:
            conn.execute("UPDATE webhook_deliveries SET status = ?, next_attempt_at = ?, error_code = ?, error_message = ?, updated_at = ?, lease_expires_at = NULL WHERE delivery_id = ?", (status, next_attempt, type(exc).__name__, safe, _now(), row["delivery_id"]))

    def get_webhook_delivery(self, delivery_id: str) -> WebhookDelivery:
        with connect() as conn:
            row = conn.execute("SELECT * FROM webhook_deliveries WHERE delivery_id = ?", (delivery_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Unknown webhook delivery: {delivery_id}")
        return _delivery(row)

    # Summary / verification --------------------------------------------------
    def summary(self, organization_id: str, project_id: str, actor: UserIdentity) -> ContinuousIntelligenceSummary:
        self._project_access(organization_id, project_id, actor)
        sources = self.list_sources(organization_id, project_id, actor)
        watchlists = self.list_watchlists(organization_id, project_id, actor)
        alerts = self.list_alerts(organization_id, project_id, actor, limit=50)
        polls = self.list_polls(organization_id, project_id, actor, limit=30)
        candidates = self.compiler.list_candidates(organization_id, project_id, actor)
        notifications = self.list_notifications(organization_id, actor, unread_only=True)
        return ContinuousIntelligenceSummary(
            organization_id=organization_id, project_id=project_id, enabled=continuous_intelligence_enabled(),
            active_sources=sum(item.status == "active" for item in sources), degraded_sources=sum(item.status == "degraded" for item in sources),
            queued_polls=sum(item.status == "queued" for item in polls), open_alerts=sum(item.status == "open" for item in alerts),
            high_alerts=sum(item.status == "open" and SEVERITY_RANK[item.severity] >= SEVERITY_RANK["high"] for item in alerts),
            pending_candidates=sum(
                item.latest_decision is None and (item.origin or {}).get("kind") == "continuous_intelligence"
                for item in candidates
            ),
            unread_notifications=len(notifications),
            sources=sources, watchlists=watchlists, alerts=alerts, polls=polls, generated_at=_now(),
        )

    def verify(self) -> dict:
        init_db()
        with connect() as conn:
            counts = conn.execute(
                """SELECT
                (SELECT COUNT(*) FROM monitoring_sources) AS sources,
                (SELECT COUNT(*) FROM monitoring_poll_jobs WHERE status = 'queued') AS queued_polls,
                (SELECT COUNT(*) FROM intelligence_alerts WHERE status = 'open') AS open_alerts,
                (SELECT COUNT(*) FROM webhook_deliveries WHERE status IN ('queued','retrying')) AS queued_webhooks"""
            ).fetchone()
            broken = conn.execute(
                """SELECT COUNT(*) FROM intelligence_alerts a
                LEFT JOIN monitoring_entries e ON e.entry_id = a.latest_entry_id WHERE e.entry_id IS NULL"""
            ).fetchone()[0]
        status = "ok" if int(broken) == 0 else "failed"
        return {"status": status, "enabled": continuous_intelligence_enabled(), "sources": int(counts["sources"]), "queued_polls": int(counts["queued_polls"]), "open_alerts": int(counts["open_alerts"]), "queued_webhooks": int(counts["queued_webhooks"]), "broken_alert_lineage": int(broken)}

    def retry_failed_deliveries(self) -> int:
        now = _now(); changed = 0
        with connect() as conn:
            rows = conn.execute("SELECT delivery_id, attempt_count FROM webhook_deliveries WHERE status = 'failed' AND attempt_count < 5").fetchall()
            for row in rows:
                conn.execute("UPDATE webhook_deliveries SET status = 'retrying', next_attempt_at = ?, updated_at = ?, error_code = NULL, error_message = NULL WHERE delivery_id = ?", (now, now, row["delivery_id"]))
                changed += 1
        return changed

    def _project_access(self, organization_id: str, project_id: str, actor: UserIdentity) -> None:
        require_organization_role(organization_id, actor, READ_ROLES)
        require_resource_scope(organization_id, "project", project_id)

    def _watchlist(self, row) -> WatchlistManifest:
        with connect() as conn:
            rule_rows = conn.execute("SELECT * FROM monitoring_watch_rules WHERE watchlist_id = ? ORDER BY position", (row["watchlist_id"],)).fetchall()
        rules = [WatchRule(rule_id=item["rule_id"], position=int(item["position"]), candidate_type=item["candidate_type"], canonical_value=item["canonical_value"], severity=item["severity"], rule_hash=item["rule_hash"]) for item in rule_rows]
        return WatchlistManifest(
            watchlist_id=row["watchlist_id"], family_id=row["family_id"], organization_id=row["organization_id"], project_id=row["project_id"],
            parent_watchlist_id=row["parent_watchlist_id"], version=int(row["version"]), name=row["name"], status=row["status"],
            manifest=loads(row["manifest_json"], {}), manifest_hash=row["manifest_hash"], created_by_user_id=row["created_by_user_id"],
            created_at=row["created_at"], activated_at=row["activated_at"], retired_at=row["retired_at"], rules=rules,
        )


def _source(row) -> MonitoringSource:
    return MonitoringSource(
        source_id=row["source_id"], organization_id=row["organization_id"], project_id=row["project_id"], policy_id=row["policy_id"],
        parent_source_id=row["parent_source_id"], name=row["name"], source_type=row["source_type"], feed_url=row["feed_url"],
        publisher=row["publisher"], license_name=row["license_name"], license_url=row["license_url"], category=row["category"],
        poll_interval_minutes=int(row["poll_interval_minutes"]), status=row["status"], etag=row["etag"], last_modified=row["last_modified"],
        config=loads(row["config_json"], {}), config_hash=row["config_hash"], consecutive_failures=int(row["consecutive_failures"]),
        last_error_code=row["last_error_code"], last_polled_at=row["last_polled_at"], next_poll_at=row["next_poll_at"],
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], updated_at=row["updated_at"], retired_at=row["retired_at"],
    )


def _poll(row) -> MonitoringPollJob:
    return MonitoringPollJob(
        poll_id=row["poll_id"], organization_id=row["organization_id"], project_id=row["project_id"], source_id=row["source_id"],
        parent_poll_id=row["parent_poll_id"], status=row["status"], scheduled_for=row["scheduled_for"], request_hash=row["request_hash"],
        worker_id=row["worker_id"], lease_expires_at=row["lease_expires_at"], attempt_count=int(row["attempt_count"]), response_status=row["response_status"],
        response_hash=row["response_hash"], discovered_count=int(row["discovered_count"]), changed_count=int(row["changed_count"]), matched_count=int(row["matched_count"]),
        materialized_count=int(row["materialized_count"]), result=loads(row["result_json"], {}), result_hash=row["result_hash"], error_code=row["error_code"],
        error_message=row["error_message"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], started_at=row["started_at"],
        updated_at=row["updated_at"], completed_at=row["completed_at"],
    )


def _poll_event(row) -> MonitoringPollEvent:
    return MonitoringPollEvent(poll_id=row["poll_id"], seq=int(row["seq"]), event_type=row["event_type"], title=row["title"], detail=row["detail"], payload=loads(row["payload_json"], {}), created_at=row["created_at"])


def _alert(row) -> IntelligenceAlert:
    return IntelligenceAlert(
        alert_id=row["alert_id"], organization_id=row["organization_id"], project_id=row["project_id"], watchlist_id=row["watchlist_id"],
        source_id=row["source_id"], stable_key=row["stable_key"], status=row["status"], severity=row["severity"], title=row["title"], summary=row["summary"],
        revision_count=int(row["revision_count"]), latest_entry_id=row["latest_entry_id"], latest_entry_hash=row["latest_entry_hash"],
        matches=loads(row["match_json"], []), lineage=AlertLineage.model_validate(loads(row["lineage_json"], {})), alert_hash=row["alert_hash"],
        acknowledged_by_user_id=row["acknowledged_by_user_id"], acknowledged_at=row["acknowledged_at"], dismissed_by_user_id=row["dismissed_by_user_id"],
        dismissed_at=row["dismissed_at"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _alert_event(row) -> IntelligenceAlertEvent:
    return IntelligenceAlertEvent(alert_id=row["alert_id"], seq=int(row["seq"]), event_type=row["event_type"], entry_id=row["entry_id"], actor_user_id=row["actor_user_id"], payload=loads(row["payload_json"], {}), event_hash=row["event_hash"], created_at=row["created_at"])


def _subscription(row) -> NotificationSubscription:
    return NotificationSubscription(
        subscription_id=row["subscription_id"], organization_id=row["organization_id"], project_id=row["project_id"], watchlist_id=row["watchlist_id"],
        channel=row["channel"], subscriber_user_id=row["subscriber_user_id"], endpoint_url=row["endpoint_url"], secret_ref=row["secret_ref"],
        min_severity=row["min_severity"], status=row["status"], config=loads(row["config_json"], {}), config_hash=row["config_hash"],
        created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], updated_at=row["updated_at"],
    )


def _notification(row) -> InAppNotification:
    return InAppNotification(
        notification_id=row["notification_id"], organization_id=row["organization_id"], seq=int(row["seq"]), user_id=row["user_id"],
        alert_id=row["alert_id"], event_type=row["event_type"], entry_hash=row["entry_hash"], title=row["title"], body=row["body"], severity=row["severity"],
        deep_link=row["deep_link"], payload=loads(row["payload_json"], {}), payload_hash=row["payload_hash"], created_at=row["created_at"], read_at=row["read_at"],
    )


def _delivery(row) -> WebhookDelivery:
    return WebhookDelivery(
        delivery_id=row["delivery_id"], subscription_id=row["subscription_id"], alert_id=row["alert_id"], event_type=row["event_type"], entry_hash=row["entry_hash"],
        status=row["status"], attempt_count=int(row["attempt_count"]), next_attempt_at=row["next_attempt_at"], payload_hash=row["payload_hash"],
        response_status=row["response_status"], error_code=row["error_code"], error_message=row["error_message"], created_at=row["created_at"],
        updated_at=row["updated_at"], delivered_at=row["delivered_at"],
    )


def _validate_watch_value(candidate_type: str, value: str) -> None:
    allowed = {
        "scenario_preset": {item.key for item in SCENARIOS}, "country": {item.code for item in COUNTRIES},
        "supply_chain": {item.key for item in SUPPLY_CHAINS}, "policy_action": set(POLICY_ACTIONS),
    }
    if value not in allowed.get(candidate_type, set()):
        raise HTTPException(status_code=422, detail=f"Unknown canonical watch value: {candidate_type}/{value}")


def _actor_for_user(user_id: str) -> UserIdentity:
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = ? AND is_active = 1", (user_id,)).fetchone()
    if row is None:
        return ensure_system_user()
    return UserIdentity(user_id=row["user_id"], username=row["username"], display_name=row["display_name"], role=row["role"], is_active=bool(row["is_active"]))


def _organization_role(organization_id: str, actor: UserIdentity) -> str:
    with connect() as conn:
        row = conn.execute("SELECT role FROM organization_members WHERE organization_id = ? AND user_id = ? AND status = 'active'", (organization_id, actor.user_id)).fetchone()
    return row["role"] if row else ""


def _summary(text: str) -> str:
    clean = " ".join(text.split())
    return clean[:360] + ("…" if len(clean) > 360 else "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _after(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat(timespec="milliseconds")
