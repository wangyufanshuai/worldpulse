from __future__ import annotations

from datetime import datetime
import json
from uuid import uuid4

from fastapi import HTTPException

from app.core.evidence_models import EvidenceSnapshotCreate, EvidenceSourceCreate
from app.core.organization_models import (
    DataConnector,
    DataConnectorCreateRequest,
    IngestionEvent,
    IngestionJob,
    IngestionJobCreateRequest,
    IngestionPolicy,
    IngestionPolicyCreateRequest,
    IngestionRecordInput,
    IngestionSummary,
)
from app.core.trust_models import UserIdentity
from app.services import evidence_registry
from app.services.consistency.hashing import stable_hash
from app.db.postgres import is_postgres_url
from app.services.organizations import ORG_WRITE_ROLES, require_organization_role, require_resource_scope, scope_resource
from app.services.project_store import connect, dumps, init_db, loads
from app.services.security import redact_secrets


FORBIDDEN_CONFIG_KEYS = {"password", "secret", "token", "api_key", "apikey", "authorization", "cookie"}
DEFAULT_CATEGORIES = ["energy", "food", "trade", "finance", "sanctions", "conflict", "climate", "other"]


def ensure_default_policy(organization_id: str, actor: UserIdentity) -> IngestionPolicy:
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT policy_id FROM ingestion_policies WHERE organization_id = ? AND status = 'active' ORDER BY created_at, policy_id LIMIT 1",
            (organization_id,),
        ).fetchone()
    if row:
        return get_policy(organization_id, row["policy_id"], actor)
    return create_policy(organization_id, IngestionPolicyCreateRequest(name="Default governed manual ingestion", version="1.0.0"), actor)


def create_policy(organization_id: str, payload: IngestionPolicyCreateRequest, actor: UserIdentity) -> IngestionPolicy:
    require_organization_role(organization_id, actor, {"owner", "admin"})
    if set(payload.allowed_connector_types) - {"manual_json"}:
        raise HTTPException(status_code=422, detail="V1.5 allows only manual_json connectors")
    manifest = payload.model_dump(mode="json")
    manifest["schema_version"] = "ingestion-policy.v1"
    manifest_hash = stable_hash(manifest)
    policy_id = f"pol_{uuid4().hex[:20]}"
    now = _now()
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO ingestion_policies
                (policy_id, organization_id, name, version, status, allowed_connector_types_json,
                 allowed_categories_json, max_records, max_bytes, require_license_metadata, require_cutoff,
                 retention_days, manifest_json, manifest_hash, created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (policy_id, organization_id, payload.name, payload.version, dumps(payload.allowed_connector_types),
                 dumps(payload.allowed_categories), payload.max_records, payload.max_bytes,
                 int(payload.require_license_metadata), int(payload.require_cutoff), payload.retention_days,
                 dumps(manifest), manifest_hash, actor.user_id, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Ingestion policy version already exists") from exc
        raise
    return get_policy(organization_id, policy_id, actor)


def list_policies(organization_id: str, actor: UserIdentity) -> list[IngestionPolicy]:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ingestion_policies WHERE organization_id = ? ORDER BY created_at DESC, policy_id DESC", (organization_id,)).fetchall()
    return [_policy(row) for row in rows]


def get_policy(organization_id: str, policy_id: str, actor: UserIdentity) -> IngestionPolicy:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        row = conn.execute("SELECT * FROM ingestion_policies WHERE organization_id = ? AND policy_id = ?", (organization_id, policy_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown ingestion policy: {policy_id}")
    return _policy(row)


def create_connector(organization_id: str, payload: DataConnectorCreateRequest, actor: UserIdentity) -> DataConnector:
    require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
    _reject_secrets(payload.config)
    policy = get_policy(organization_id, payload.policy_id, actor) if payload.policy_id else ensure_default_policy(organization_id, actor)
    if payload.connector_type not in policy.allowed_connector_types:
        raise HTTPException(status_code=422, detail="Connector type is not allowed by the selected policy")
    if policy.require_license_metadata and not all(str(payload.config.get(key, "")).strip() for key in ("publisher", "license")):
        raise HTTPException(status_code=422, detail="Connector requires publisher and license metadata")
    connector_id = f"con_{uuid4().hex[:20]}"
    config_hash = stable_hash({"connector_type": payload.connector_type, "source_locator": payload.source_locator, "config": payload.config})
    now = _now()
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO data_connectors
                (connector_id, organization_id, policy_id, name, connector_type, source_locator, config_json,
                 config_hash, status, created_by_user_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?)
                """,
                (connector_id, organization_id, policy.policy_id, payload.name, payload.connector_type,
                 payload.source_locator, dumps(payload.config), config_hash, actor.user_id, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise HTTPException(status_code=409, detail="Connector name already exists in the organization") from exc
        raise
    scope_resource(organization_id, "connector", connector_id)
    return get_connector(organization_id, connector_id, actor)


def list_connectors(organization_id: str, actor: UserIdentity) -> list[DataConnector]:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        rows = conn.execute("SELECT * FROM data_connectors WHERE organization_id = ? ORDER BY created_at DESC, connector_id DESC", (organization_id,)).fetchall()
    return [_connector(row) for row in rows]


def get_connector(organization_id: str, connector_id: str, actor: UserIdentity) -> DataConnector:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        row = conn.execute("SELECT * FROM data_connectors WHERE organization_id = ? AND connector_id = ?", (organization_id, connector_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown data connector: {connector_id}")
    return _connector(row)


def create_job(organization_id: str, payload: IngestionJobCreateRequest, actor: UserIdentity) -> IngestionJob:
    require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
    connector = get_connector(organization_id, payload.connector_id, actor)
    policy = get_policy(organization_id, connector.policy_id, actor)
    if connector.status != "active" or policy.status != "active":
        raise HTTPException(status_code=409, detail="Connector and policy must be active")
    if payload.project_id:
        require_resource_scope(organization_id, "project", payload.project_id)
    request_payload = payload.model_dump(mode="json")
    _validate_request(request_payload["records"], connector, policy)
    request_hash = stable_hash({"organization_id": organization_id, "connector_hash": connector.config_hash, "policy_hash": policy.manifest_hash, "request": request_payload})
    if payload.idempotency_key:
        with connect() as conn:
            existing = conn.execute(
                "SELECT job_id, request_hash FROM ingestion_jobs WHERE organization_id = ? AND idempotency_key = ?",
                (organization_id, payload.idempotency_key),
            ).fetchone()
        if existing:
            if existing["request_hash"] == request_hash:
                return get_job(organization_id, existing["job_id"], actor)
            raise HTTPException(status_code=409, detail="Idempotency key was already used with different ingestion content")
    job_id = f"ing_{uuid4().hex[:20]}"
    now = _now()
    existing_job_id = None
    try:
        with connect() as conn:
            from app.services.operations import enforce_quota, lock_organization_quota

            if not is_postgres_url():
                conn.execute("BEGIN IMMEDIATE")
            lock_organization_quota(organization_id, conn)
            if payload.idempotency_key:
                existing = conn.execute(
                    "SELECT job_id, request_hash FROM ingestion_jobs WHERE organization_id = ? AND idempotency_key = ?",
                    (organization_id, payload.idempotency_key),
                ).fetchone()
                if existing:
                    if existing["request_hash"] != request_hash:
                        raise HTTPException(status_code=409, detail="Idempotency key was already used with different ingestion content")
                    existing_job_id = existing["job_id"]
            if existing_job_id is None:
                enforce_quota(organization_id, "ingestion_job", connection=conn)
                enforce_quota(organization_id, "evidence_snapshot", requested=len(payload.records), connection=conn)
                conn.execute(
                    """
                    INSERT INTO ingestion_jobs
                    (job_id, organization_id, connector_id, policy_id, project_id, status, request_json,
                     request_hash, idempotency_key, record_count, created_by_user_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (job_id, organization_id, connector.connector_id, policy.policy_id, payload.project_id,
                     dumps(request_payload), request_hash, payload.idempotency_key, len(payload.records), actor.user_id, now, now),
                )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper() and payload.idempotency_key:
            with connect() as conn:
                row = conn.execute("SELECT job_id, request_hash FROM ingestion_jobs WHERE organization_id = ? AND idempotency_key = ?", (organization_id, payload.idempotency_key)).fetchone()
            if row and row["request_hash"] == request_hash:
                return get_job(organization_id, row["job_id"], actor)
            raise HTTPException(status_code=409, detail="Idempotency key was already used with different ingestion content") from exc
        raise
    if existing_job_id is not None:
        return get_job(organization_id, existing_job_id, actor)
    append_event(job_id, "INGESTION", "Ingestion job queued", "受控采集任务已创建，等待独立 worker 或显式执行。", {"record_count": len(payload.records)})
    return get_job(organization_id, job_id, actor)


def execute_job(organization_id: str, job_id: str, actor: UserIdentity, *, worker_id: str = "api-bounded-executor") -> IngestionJob:
    require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
    job = get_job(organization_id, job_id, actor)
    if job.status == "completed":
        return job
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail=f"Ingestion job cannot execute from status {job.status}")
    now = _now()
    with connect() as conn:
        if job.status == "queued":
            updated = conn.execute(
                "UPDATE ingestion_jobs SET status = 'running', worker_id = ?, started_at = ?, updated_at = ? WHERE job_id = ? AND status = 'queued'",
                (worker_id, now, now, job_id),
            )
            if updated.rowcount != 1:
                raise HTTPException(status_code=409, detail="Ingestion job was claimed concurrently")
    append_event(job_id, "WORKER", "Ingestion execution started", "策略、连接器与全部记录将在写入证据注册表前完成校验。", {"worker_id": worker_id})
    try:
        with connect() as conn:
            row = conn.execute("SELECT request_json FROM ingestion_jobs WHERE job_id = ?", (job_id,)).fetchone()
        request = loads(row["request_json"], {})
        connector = get_connector(organization_id, job.connector_id, actor)
        policy = get_policy(organization_id, job.policy_id, actor)
        records = request.get("records", [])
        _validate_request(records, connector, policy)
        source = evidence_registry.create_source(EvidenceSourceCreate(
            source_type="governed_ingestion", name=connector.name,
            locator=f"{connector.source_locator}#{connector.connector_id}",
            publisher=str(connector.config.get("publisher", "")), trust_tier="external_governed",
            metadata={
                "organization_id": organization_id, "connector_id": connector.connector_id,
                "connector_hash": connector.config_hash, "policy_id": policy.policy_id,
                "policy_hash": policy.manifest_hash, "license": connector.config.get("license"),
            },
        ), actor, organization_id=organization_id)
        scope_resource(organization_id, "evidence_source", source.source_id)
        accepted = []
        for raw in records:
            record = IngestionRecordInput.model_validate(raw)
            snapshot = evidence_registry.create_snapshot(EvidenceSnapshotCreate(
                source_id=source.source_id, project_id=request.get("project_id"), external_ref=record.external_ref,
                title=record.title, category=record.category, content=record.content, content_text=record.content_text,
                observed_at=record.observed_at, cutoff_at=record.cutoff_at,
            ), actor, organization_id=organization_id, quota_reserved=True)
            payload_hash = stable_hash(record.model_dump(mode="json"))
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO ingestion_records
                    (record_id, job_id, external_ref, category, observed_at, cutoff_at, payload_hash,
                     evidence_snapshot_id, status, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'accepted', ?)
                    ON CONFLICT(job_id, external_ref) DO UPDATE SET
                        payload_hash = excluded.payload_hash, evidence_snapshot_id = excluded.evidence_snapshot_id,
                        status = 'accepted', rejection_reason = NULL
                    """,
                    (f"ir_{uuid4().hex[:20]}", job_id, record.external_ref, record.category,
                     snapshot.observed_at, snapshot.cutoff_at, payload_hash, snapshot.snapshot_id, _now()),
                )
            scope_resource(organization_id, "evidence_snapshot", snapshot.snapshot_id)
            accepted.append({"external_ref": record.external_ref, "payload_hash": payload_hash, "snapshot_id": snapshot.snapshot_id, "content_hash": snapshot.content_hash})
        manifest = {
            "schema_version": "ingestion-manifest.v1", "organization_id": organization_id,
            "job_id": job_id, "project_id": request.get("project_id"), "connector_id": connector.connector_id,
            "connector_hash": connector.config_hash, "policy_id": policy.policy_id, "policy_hash": policy.manifest_hash,
            "records": sorted(accepted, key=lambda item: item["external_ref"]),
        }
        manifest_hash = stable_hash(manifest)
        completed_at = _now()
        with connect() as conn:
            conn.execute(
                """
                UPDATE ingestion_jobs SET status = 'completed', accepted_count = ?, rejected_count = 0,
                    manifest_json = ?, manifest_hash = ?, completed_at = ?, updated_at = ?, error_code = NULL,
                    error_message = NULL WHERE job_id = ?
                """,
                (len(accepted), dumps(manifest), manifest_hash, completed_at, completed_at, job_id),
            )
        append_event(job_id, "SNAPSHOT", "Evidence snapshots committed", "全部记录已通过策略和时间截点检查，并写入不可变证据注册表。", {"accepted_count": len(accepted), "manifest_hash": manifest_hash})
    except Exception as exc:
        safe = redact_secrets(str(exc), max_length=1000) or type(exc).__name__
        with connect() as conn:
            conn.execute(
                "UPDATE ingestion_jobs SET status = 'failed', error_code = ?, error_message = ?, completed_at = ?, updated_at = ? WHERE job_id = ?",
                (type(exc).__name__, safe, _now(), _now(), job_id),
            )
        append_event(job_id, "CONSISTENCY", "Ingestion failed closed", "采集未通过治理门禁；错误已脱敏记录。", {"error_code": type(exc).__name__})
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=422, detail=safe) from exc
    return get_job(organization_id, job_id, actor)


def cancel_job(organization_id: str, job_id: str, actor: UserIdentity) -> IngestionJob:
    require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
    job = get_job(organization_id, job_id, actor)
    if job.status != "queued":
        raise HTTPException(status_code=409, detail="Only a queued ingestion job can be cancelled")
    with connect() as conn:
        conn.execute("UPDATE ingestion_jobs SET status = 'cancelled', cancel_requested_at = ?, completed_at = ?, updated_at = ? WHERE job_id = ?", (_now(), _now(), _now(), job_id))
    append_event(job_id, "WORKER", "Ingestion cancelled", "任务在写入任何证据快照前取消。", {})
    return get_job(organization_id, job_id, actor)


def retry_job(organization_id: str, job_id: str, actor: UserIdentity) -> IngestionJob:
    require_organization_role(organization_id, actor, ORG_WRITE_ROLES)
    previous = get_job(organization_id, job_id, actor)
    if previous.status not in {"failed", "cancelled"}:
        raise HTTPException(status_code=409, detail="Only failed or cancelled ingestion jobs can be retried")
    with connect() as conn:
        row = conn.execute("SELECT request_json FROM ingestion_jobs WHERE job_id = ?", (job_id,)).fetchone()
    request = loads(row["request_json"], {})
    request["idempotency_key"] = None
    retried = create_job(organization_id, IngestionJobCreateRequest.model_validate(request), actor)
    with connect() as conn:
        conn.execute("UPDATE ingestion_jobs SET parent_job_id = ? WHERE job_id = ?", (job_id, retried.job_id))
    return get_job(organization_id, retried.job_id, actor)


def claim_next_job(worker_id: str) -> tuple[str, str] | None:
    init_db()
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        lock_clause = " FOR UPDATE SKIP LOCKED" if is_postgres_url() else ""
        row = conn.execute(f"SELECT job_id, organization_id FROM ingestion_jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1{lock_clause}").fetchone()
        if row is None:
            return None
        updated = conn.execute("UPDATE ingestion_jobs SET status = 'running', worker_id = ?, started_at = ?, updated_at = ? WHERE job_id = ? AND status = 'queued'", (worker_id, _now(), _now(), row["job_id"]))
        return (row["organization_id"], row["job_id"]) if updated.rowcount == 1 else None


def execute_claimed_job(organization_id: str, job_id: str, worker_id: str) -> IngestionJob:
    with connect() as conn:
        row = conn.execute(
            """
            SELECT u.user_id, u.username, u.display_name, u.role, u.is_active
            FROM ingestion_jobs j JOIN users u ON u.user_id = j.created_by_user_id
            WHERE j.job_id = ? AND j.organization_id = ?
            """,
            (job_id, organization_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=409, detail="Ingestion job has no valid creator identity")
    actor = UserIdentity(
        user_id=row["user_id"], username=row["username"], display_name=row["display_name"],
        role=row["role"], is_active=bool(row["is_active"]),
    )
    return execute_job(organization_id, job_id, actor, worker_id=worker_id)


def get_job(organization_id: str, job_id: str, actor: UserIdentity) -> IngestionJob:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        row = conn.execute("SELECT * FROM ingestion_jobs WHERE organization_id = ? AND job_id = ?", (organization_id, job_id)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown ingestion job: {job_id}")
    return _job(row)


def list_jobs(organization_id: str, actor: UserIdentity, *, limit: int = 100) -> list[IngestionJob]:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ingestion_jobs WHERE organization_id = ? ORDER BY created_at DESC, job_id DESC LIMIT ?", (organization_id, max(1, min(limit, 500)))).fetchall()
    return [_job(row) for row in rows]


def list_events(organization_id: str, job_id: str, actor: UserIdentity, *, after_seq: int = 0) -> list[IngestionEvent]:
    get_job(organization_id, job_id, actor)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM ingestion_events WHERE job_id = ? AND seq > ? ORDER BY seq", (job_id, max(0, after_seq))).fetchall()
    return [_event(row) for row in rows]


def append_event(job_id: str, event_type: str, title: str, detail: str, payload: dict) -> IngestionEvent:
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO ingestion_event_counters(job_id, next_seq) VALUES (?, 1) ON CONFLICT(job_id) DO NOTHING", (job_id,))
        if is_postgres_url():
            counter = conn.execute("UPDATE ingestion_event_counters SET next_seq = next_seq + 1 WHERE job_id = ? RETURNING next_seq - 1 AS seq", (job_id,)).fetchone()
            seq = int(counter["seq"])
        else:
            counter = conn.execute("SELECT next_seq FROM ingestion_event_counters WHERE job_id = ?", (job_id,)).fetchone()
            seq = int(counter["next_seq"])
            conn.execute("UPDATE ingestion_event_counters SET next_seq = ? WHERE job_id = ?", (seq + 1, job_id))
        now = _now()
        conn.execute(
            "INSERT INTO ingestion_events(job_id, seq, event_type, title, detail, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (job_id, seq, event_type, title, detail, dumps(payload), now),
        )
    return IngestionEvent(job_id=job_id, seq=seq, event_type=event_type, title=title, detail=detail, payload=payload, created_at=now)


def ingestion_summary(organization_id: str, actor: UserIdentity) -> IngestionSummary:
    jobs = list_jobs(organization_id, actor, limit=20)
    connectors = list_connectors(organization_id, actor)
    policies = list_policies(organization_id, actor)
    counts = {status: sum(1 for job in jobs if job.status == status) for status in ("queued", "running", "failed", "completed")}
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(accepted_count), 0) accepted, COALESCE(SUM(rejected_count), 0) rejected FROM ingestion_jobs WHERE organization_id = ?",
            (organization_id,),
        ).fetchone()
    return IngestionSummary(
        organization_id=organization_id, connector_count=len(connectors), active_policy_count=sum(1 for item in policies if item.status == "active"),
        queued_jobs=counts["queued"], running_jobs=counts["running"], failed_jobs=counts["failed"], completed_jobs=counts["completed"],
        accepted_records=int(row["accepted"] or 0), rejected_records=int(row["rejected"] or 0),
        latest_jobs=jobs, connectors=connectors, policies=policies, generated_at=_now(),
    )


def _validate_request(records: list[dict], connector: DataConnector, policy: IngestionPolicy) -> None:
    if connector.connector_type not in policy.allowed_connector_types:
        raise HTTPException(status_code=422, detail="Connector type is not allowed by policy")
    if len(records) > policy.max_records:
        raise HTTPException(status_code=422, detail=f"Record count exceeds policy maximum of {policy.max_records}")
    size = len(json.dumps(records, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    if size > policy.max_bytes:
        raise HTTPException(status_code=422, detail=f"Payload exceeds policy maximum of {policy.max_bytes} bytes")
    seen = set()
    for raw in records:
        record = IngestionRecordInput.model_validate(raw)
        if record.external_ref in seen:
            raise HTTPException(status_code=422, detail=f"Duplicate external_ref: {record.external_ref}")
        seen.add(record.external_ref)
        if record.category not in policy.allowed_categories:
            raise HTTPException(status_code=422, detail=f"Category is not allowed by policy: {record.category}")
        observed, cutoff = _parse_time(record.observed_at), _parse_time(record.cutoff_at)
        if observed > cutoff:
            raise HTTPException(status_code=422, detail=f"Future data is prohibited for {record.external_ref}")


def _reject_secrets(config: dict) -> None:
    def walk(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower().replace("-", "_") in FORBIDDEN_CONFIG_KEYS:
                    raise HTTPException(status_code=422, detail=f"Connector secrets must use an external secret reference: {key}")
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)
    walk(config)


def _policy(row) -> IngestionPolicy:
    return IngestionPolicy(
        policy_id=row["policy_id"], organization_id=row["organization_id"], name=row["name"], version=row["version"], status=row["status"],
        allowed_connector_types=loads(row["allowed_connector_types_json"], []), allowed_categories=loads(row["allowed_categories_json"], []),
        max_records=int(row["max_records"]), max_bytes=int(row["max_bytes"]), require_license_metadata=bool(row["require_license_metadata"]),
        require_cutoff=bool(row["require_cutoff"]), retention_days=int(row["retention_days"]), manifest=loads(row["manifest_json"], {}),
        manifest_hash=row["manifest_hash"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], retired_at=row["retired_at"],
    )


def _connector(row) -> DataConnector:
    return DataConnector(
        connector_id=row["connector_id"], organization_id=row["organization_id"], policy_id=row["policy_id"], name=row["name"],
        connector_type=row["connector_type"], source_locator=row["source_locator"], config=loads(row["config_json"], {}),
        config_hash=row["config_hash"], status=row["status"], created_by_user_id=row["created_by_user_id"], created_at=row["created_at"], retired_at=row["retired_at"],
    )


def _job(row) -> IngestionJob:
    return IngestionJob(
        job_id=row["job_id"], organization_id=row["organization_id"], connector_id=row["connector_id"], policy_id=row["policy_id"],
        project_id=row["project_id"], parent_job_id=row["parent_job_id"], status=row["status"], request_hash=row["request_hash"],
        idempotency_key=row["idempotency_key"], record_count=int(row["record_count"] or 0), accepted_count=int(row["accepted_count"] or 0),
        rejected_count=int(row["rejected_count"] or 0), manifest=loads(row["manifest_json"], {}), manifest_hash=row["manifest_hash"],
        error_code=row["error_code"], error_message=row["error_message"], created_by_user_id=row["created_by_user_id"], worker_id=row["worker_id"],
        created_at=row["created_at"], started_at=row["started_at"], updated_at=row["updated_at"], completed_at=row["completed_at"],
    )


def _event(row) -> IngestionEvent:
    return IngestionEvent(job_id=row["job_id"], seq=int(row["seq"]), event_type=row["event_type"], title=row["title"], detail=row["detail"], payload=loads(row["payload_json"], {}), created_at=row["created_at"])


def _parse_time(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid ISO timestamp: {value}") from exc


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
