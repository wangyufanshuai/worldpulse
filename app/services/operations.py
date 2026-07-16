from __future__ import annotations

from datetime import datetime, timedelta
import os
import socket
from uuid import uuid4

from fastapi import HTTPException

from app.core.operations_models import (
    OrganizationOperationsSummary,
    OrganizationQuota,
    OrganizationQuotaUpdate,
    OrganizationUsage,
    PlatformReadiness,
    WorkerNode,
)
from app.core.trust_models import UserIdentity
from app.db.postgres import is_postgres_url
from app.services.organizations import require_organization_role
from app.services.project_store import connect, dumps, init_db, loads
from app.version import WORLDPULSE_VERSION


DEFAULT_QUOTA = {
    "max_projects": 100,
    "max_active_runs": 10,
    "max_ingestion_jobs_per_day": 500,
    "max_evidence_snapshots": 100_000,
}


def register_worker(worker_id: str, worker_kind: str, *, lease_seconds: int = 30, metadata: dict | None = None) -> WorkerNode:
    if worker_kind not in {"lifecycle", "ingestion"}:
        raise ValueError(f"Unsupported worker kind: {worker_kind}")
    init_db()
    now = _now()
    expires = _after(lease_seconds)
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO worker_nodes
            (worker_id, worker_kind, status, hostname, process_id, version, started_at, heartbeat_at,
             lease_expires_at, jobs_completed, metadata_json)
            VALUES (?, ?, 'ready', ?, ?, ?, ?, ?, ?, 0, ?)
            ON CONFLICT(worker_id) DO UPDATE SET
                worker_kind = excluded.worker_kind, status = 'ready', hostname = excluded.hostname,
                process_id = excluded.process_id, version = excluded.version, started_at = excluded.started_at,
                heartbeat_at = excluded.heartbeat_at, lease_expires_at = excluded.lease_expires_at,
                current_job_id = NULL, jobs_completed = 0, last_error_code = NULL,
                metadata_json = excluded.metadata_json
            """,
            (worker_id, worker_kind, socket.gethostname()[:160], os.getpid(), WORLDPULSE_VERSION,
             now, now, expires, dumps(metadata or {})),
        )
    return get_worker(worker_id)


def heartbeat_worker(
    worker_id: str,
    *,
    status: str = "ready",
    current_job_id: str | None = None,
    lease_seconds: int = 30,
    completed_increment: int = 0,
    error_code: str | None = None,
) -> WorkerNode:
    if status not in {"ready", "busy", "draining", "failed"}:
        raise ValueError(f"Unsupported heartbeat status: {status}")
    now = _now()
    with connect() as conn:
        row = conn.execute("SELECT status FROM worker_nodes WHERE worker_id = ?", (worker_id,)).fetchone()
        if row is None:
            raise RuntimeError(f"Worker is not registered: {worker_id}")
        next_status = "draining" if row["status"] == "draining" and status in {"ready", "busy"} else status
        conn.execute(
            """
            UPDATE worker_nodes
            SET status = ?, heartbeat_at = ?, lease_expires_at = ?, current_job_id = ?,
                jobs_completed = jobs_completed + ?, last_error_code = ?
            WHERE worker_id = ?
            """,
            (next_status, now, _after(lease_seconds), current_job_id, max(0, completed_increment), error_code, worker_id),
        )
    return get_worker(worker_id)


def heartbeat_registered_worker(
    worker_id: str,
    *,
    status: str = "ready",
    current_job_id: str | None = None,
    lease_seconds: int = 30,
    completed_increment: int = 0,
    error_code: str | None = None,
) -> WorkerNode | None:
    """Heartbeat a process only when it opted into the V1.7 registry.

    Service-level executors remain callable by tests and bounded API execution,
    so an unregistered legacy worker id is intentionally a no-op.
    """
    try:
        return heartbeat_worker(
            worker_id,
            status=status,
            current_job_id=current_job_id,
            lease_seconds=lease_seconds,
            completed_increment=completed_increment,
            error_code=error_code,
        )
    except RuntimeError:
        return None


def request_worker_drain(worker_id: str) -> WorkerNode:
    worker = get_worker(worker_id)
    if worker.status in {"stopped", "failed", "stale"}:
        raise HTTPException(status_code=409, detail=f"Worker cannot drain from status {worker.status}")
    with connect() as conn:
        conn.execute("UPDATE worker_nodes SET status = 'draining', heartbeat_at = ? WHERE worker_id = ?", (_now(), worker_id))
    return get_worker(worker_id)


def worker_should_drain(worker_id: str) -> bool:
    with connect() as conn:
        row = conn.execute("SELECT status FROM worker_nodes WHERE worker_id = ?", (worker_id,)).fetchone()
    return row is not None and row["status"] == "draining"


def stop_worker(worker_id: str, *, failed: bool = False, error_code: str | None = None) -> WorkerNode:
    now = _now()
    with connect() as conn:
        conn.execute(
            "UPDATE worker_nodes SET status = ?, heartbeat_at = ?, lease_expires_at = ?, current_job_id = NULL, last_error_code = ? WHERE worker_id = ?",
            ("failed" if failed else "stopped", now, now, error_code, worker_id),
        )
    return get_worker(worker_id)


def get_worker(worker_id: str) -> WorkerNode:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM worker_nodes WHERE worker_id = ?", (worker_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown worker: {worker_id}")
    return _worker(row)


def list_workers(*, include_stopped: bool = True) -> list[WorkerNode]:
    init_db()
    where = "" if include_stopped else " WHERE status NOT IN ('stopped','failed')"
    with connect() as conn:
        rows = conn.execute(f"SELECT * FROM worker_nodes{where} ORDER BY worker_kind, started_at DESC").fetchall()
    return [_worker(row) for row in rows]


def get_quota(organization_id: str) -> OrganizationQuota:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM organization_quotas WHERE organization_id = ?", (organization_id,)).fetchone()
        if row is None:
            organization = conn.execute("SELECT organization_id FROM organizations WHERE organization_id = ?", (organization_id,)).fetchone()
            if organization is None:
                raise HTTPException(status_code=404, detail=f"Unknown organization: {organization_id}")
            conn.execute(
                """
                INSERT INTO organization_quotas
                (organization_id, max_projects, max_active_runs, max_ingestion_jobs_per_day, max_evidence_snapshots, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(organization_id) DO NOTHING
                """,
                (organization_id, DEFAULT_QUOTA["max_projects"], DEFAULT_QUOTA["max_active_runs"],
                 DEFAULT_QUOTA["max_ingestion_jobs_per_day"], DEFAULT_QUOTA["max_evidence_snapshots"], _now()),
            )
            row = conn.execute("SELECT * FROM organization_quotas WHERE organization_id = ?", (organization_id,)).fetchone()
    return _quota(row)


def update_quota(organization_id: str, payload: OrganizationQuotaUpdate, actor: UserIdentity) -> OrganizationQuota:
    require_organization_role(organization_id, actor, {"owner", "admin"})
    now = _now()
    current = payload.model_dump(mode="json")
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        previous = lock_organization_quota(organization_id, conn)
        conn.execute(
            """
            UPDATE organization_quotas
            SET max_projects = ?, max_active_runs = ?, max_ingestion_jobs_per_day = ?,
                max_evidence_snapshots = ?, updated_by_user_id = ?, updated_at = ?
            WHERE organization_id = ?
            """,
            (payload.max_projects, payload.max_active_runs, payload.max_ingestion_jobs_per_day,
             payload.max_evidence_snapshots, actor.user_id, now, organization_id),
        )
        conn.execute(
            """
            INSERT INTO organization_quota_events
            (event_id, organization_id, previous_json, current_json, actor_user_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (f"oqe_{uuid4().hex[:20]}", organization_id, dumps(previous.model_dump(mode="json")),
             dumps(current), actor.user_id, now),
        )
    return get_quota(organization_id)


def organization_usage(organization_id: str) -> OrganizationUsage:
    init_db()
    cutoff = (datetime.now() - timedelta(days=1)).isoformat(timespec="milliseconds")
    with connect() as conn:
        row = conn.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM organization_resources WHERE organization_id = ? AND resource_type = 'project') AS projects,
              (SELECT COUNT(*) FROM run_jobs j JOIN organization_resources r ON r.resource_id = j.project_id
                 WHERE r.organization_id = ? AND r.resource_type = 'project'
                   AND j.status NOT IN ('completed','cancelled','failed')) AS active_runs,
              (SELECT COUNT(*) FROM ingestion_jobs WHERE organization_id = ? AND created_at >= ?) AS ingestion_jobs_today,
              (SELECT COUNT(*) FROM organization_resources WHERE organization_id = ? AND resource_type = 'evidence_snapshot') AS evidence_snapshots
            """,
            (organization_id, organization_id, organization_id, cutoff, organization_id),
        ).fetchone()
    return OrganizationUsage(
        organization_id=organization_id,
        projects=int(row["projects"] or 0),
        active_runs=int(row["active_runs"] or 0),
        ingestion_jobs_today=int(row["ingestion_jobs_today"] or 0),
        evidence_snapshots=int(row["evidence_snapshots"] or 0),
        generated_at=_now(),
    )


def lock_organization_quota(organization_id: str, connection) -> OrganizationQuota:
    connection.execute(
        """
        INSERT INTO organization_quotas
        (organization_id, max_projects, max_active_runs, max_ingestion_jobs_per_day, max_evidence_snapshots, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(organization_id) DO NOTHING
        """,
        (organization_id, DEFAULT_QUOTA["max_projects"], DEFAULT_QUOTA["max_active_runs"],
         DEFAULT_QUOTA["max_ingestion_jobs_per_day"], DEFAULT_QUOTA["max_evidence_snapshots"], _now()),
    )
    suffix = " FOR UPDATE" if is_postgres_url() else ""
    row = connection.execute(
        f"SELECT * FROM organization_quotas WHERE organization_id = ?{suffix}",
        (organization_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown organization: {organization_id}")
    return _quota(row)


def enforce_quota(organization_id: str, resource: str, *, requested: int = 1, connection=None) -> None:
    if requested < 1:
        raise ValueError("requested quota amount must be positive")

    def check(conn) -> None:
        quota = lock_organization_quota(organization_id, conn)
        cutoff = (datetime.now() - timedelta(days=1)).isoformat(timespec="milliseconds")
        queries = {
            "project": (
                "SELECT COUNT(*) FROM organization_resources WHERE organization_id = ? AND resource_type = 'project'",
                (organization_id,), quota.max_projects,
            ),
            "active_run": (
                """SELECT COUNT(*) FROM run_jobs j JOIN organization_resources r
                   ON r.resource_id = j.project_id AND r.resource_type = 'project'
                   WHERE r.organization_id = ? AND j.status NOT IN ('completed','cancelled','failed')""",
                (organization_id,), quota.max_active_runs,
            ),
            "ingestion_job": (
                "SELECT COUNT(*) FROM ingestion_jobs WHERE organization_id = ? AND created_at >= ?",
                (organization_id, cutoff), quota.max_ingestion_jobs_per_day,
            ),
            "evidence_snapshot": (
                """SELECT
                     (SELECT COUNT(*) FROM organization_resources
                      WHERE organization_id = ? AND resource_type = 'evidence_snapshot')
                     + COALESCE((SELECT SUM(record_count) FROM ingestion_jobs
                                 WHERE organization_id = ? AND status IN ('queued','running')), 0)""",
                (organization_id, organization_id), quota.max_evidence_snapshots,
            ),
        }
        if resource not in queries:
            raise ValueError(f"Unknown quota resource: {resource}")
        statement, params, limit = queries[resource]
        current = int(conn.execute(statement, params).fetchone()[0])
        if current + requested > limit:
            raise HTTPException(
                status_code=429,
                detail=f"Organization quota exceeded: {resource} {current}+{requested}/{limit}",
            )

    if connection is not None:
        check(connection)
        return
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        check(conn)


def enforce_project_run_quota(project_id: str, *, connection=None) -> str:
    def check(conn) -> str:
        row = conn.execute(
            "SELECT organization_id FROM organization_resources WHERE resource_type = 'project' AND resource_id = ? ORDER BY organization_id LIMIT 1",
            (project_id,),
        ).fetchone()
        organization_id = row["organization_id"] if row else "org_default"
        quota = lock_organization_quota(organization_id, conn)
        active = conn.execute(
            """
            SELECT COUNT(*) FROM run_jobs j
            JOIN organization_resources r ON r.resource_id = j.project_id AND r.resource_type = 'project'
            WHERE r.organization_id = ? AND j.status NOT IN ('completed','cancelled','failed')
            """,
            (organization_id,),
        ).fetchone()[0]
        limit = quota.max_active_runs
        if int(active) + 1 > limit:
            raise HTTPException(status_code=429, detail=f"Organization quota exceeded: active_run {active}+1/{limit}")
        return organization_id

    if connection is not None:
        return check(connection)
    with connect() as conn:
        if not is_postgres_url():
            conn.execute("BEGIN IMMEDIATE")
        return check(conn)


def platform_readiness() -> PlatformReadiness:
    reasons: list[str] = []
    schema_ok = False
    rule_pack_ok = False
    try:
        init_db()
        from app.services.rule_packs import active_rule_pack

        active_rule_pack()
        with connect() as conn:
            conn.execute("SELECT 1").fetchone()
            active = conn.execute("SELECT 1 FROM rule_packs WHERE status = 'active' LIMIT 1").fetchone()
            counts = conn.execute(
                """
                SELECT
                  (SELECT COUNT(*) FROM run_jobs WHERE status = 'queued') AS queued_runs,
                  (SELECT COUNT(*) FROM ingestion_jobs WHERE status = 'queued') AS queued_ingestion
                """
            ).fetchone()
        schema_ok = True
        rule_pack_ok = active is not None
        if not rule_pack_ok:
            reasons.append("no_active_rule_pack")
    except Exception as exc:
        reasons.append(f"database:{type(exc).__name__}")
        counts = {"queued_runs": 0, "queued_ingestion": 0}
    workers = list_workers() if schema_ok else []
    lifecycle = sum(1 for item in workers if item.worker_kind == "lifecycle" and item.fresh and item.status in {"ready", "busy", "draining"})
    ingestion = sum(1 for item in workers if item.worker_kind == "ingestion" and item.fresh and item.status in {"ready", "busy", "draining"})
    require_workers = os.getenv("WORLDPULSE_REQUIRE_WORKERS", "0").strip().lower() in {"1", "true", "yes", "on"}
    workers_met = lifecycle > 0 and ingestion > 0
    if require_workers and not workers_met:
        reasons.append("required_workers_unavailable")
    ready = schema_ok and rule_pack_ok and (workers_met or not require_workers)
    status = "ready" if ready and workers_met else "degraded" if ready else "not_ready"
    return PlatformReadiness(
        status=status,
        database_backend="postgresql" if is_postgres_url() else "sqlite",
        schema_ok=schema_ok,
        rule_pack_ok=rule_pack_ok,
        worker_requirement_enabled=require_workers,
        worker_requirement_met=workers_met,
        lifecycle_workers_fresh=lifecycle,
        ingestion_workers_fresh=ingestion,
        queued_runs=int(counts["queued_runs"] or 0),
        queued_ingestion_jobs=int(counts["queued_ingestion"] or 0),
        checked_at=_now(),
        reasons=reasons,
    )


def organization_operations(organization_id: str, actor: UserIdentity) -> OrganizationOperationsSummary:
    require_organization_role(organization_id, actor, {"owner", "admin", "analyst", "reviewer", "viewer"})
    return OrganizationOperationsSummary(
        organization_id=organization_id,
        quota=get_quota(organization_id),
        usage=organization_usage(organization_id),
        workers=list_workers(),
        readiness=platform_readiness(),
        generated_at=_now(),
    )


def _worker(row) -> WorkerNode:
    fresh = row["lease_expires_at"] > _now()
    status = row["status"] if fresh or row["status"] in {"stopped", "failed"} else "stale"
    return WorkerNode(
        worker_id=row["worker_id"], worker_kind=row["worker_kind"], status=status,
        hostname=row["hostname"], process_id=int(row["process_id"]), version=row["version"],
        started_at=row["started_at"], heartbeat_at=row["heartbeat_at"], lease_expires_at=row["lease_expires_at"],
        current_job_id=row["current_job_id"], jobs_completed=int(row["jobs_completed"] or 0),
        last_error_code=row["last_error_code"], metadata=loads(row["metadata_json"], {}), fresh=fresh,
    )


def _quota(row) -> OrganizationQuota:
    return OrganizationQuota(
        organization_id=row["organization_id"], max_projects=int(row["max_projects"]),
        max_active_runs=int(row["max_active_runs"]), max_ingestion_jobs_per_day=int(row["max_ingestion_jobs_per_day"]),
        max_evidence_snapshots=int(row["max_evidence_snapshots"]), updated_by_user_id=row["updated_by_user_id"],
        updated_at=row["updated_at"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


def _after(seconds: int) -> str:
    return (datetime.now() + timedelta(seconds=max(5, seconds))).isoformat(timespec="milliseconds")
