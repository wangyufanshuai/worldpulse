from __future__ import annotations

from datetime import datetime
import hashlib
import sqlite3
from uuid import uuid4

from fastapi import HTTPException

from app.core.trust_models import RulePackCreateRequest, RulePackManifest, RulePackReview, UserIdentity
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads


V12_MANIFEST = {
    "name": "WorldPulse V1.2 deterministic governance",
    "version": "1.2.0",
    "war_room_rule_version": "war-room-rules.v1.1",
    "consistency_rule_version": "worldpulse-consistency.v1.2",
    "action_adapter_version": "deterministic-action-modifier.v1",
    "scoring_weights_version": "war-room-scoring.v1",
    "evidence_policy_version": "evidence-policy.v1",
}


def ensure_v12_active_rule_pack() -> RulePackManifest:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM rule_packs WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1").fetchone()
        if row is None:
            now = _now()
            manifest_hash = stable_hash(V12_MANIFEST)
            conn.execute(
                """
                INSERT OR IGNORE INTO rule_packs
                (rule_pack_id, name, version, war_room_rule_version, consistency_rule_version,
                 action_adapter_version, scoring_weights_version, evidence_policy_version,
                 manifest_json, manifest_hash, status, created_at, submitted_at, activated_at)
                VALUES ('rp_v12_active', ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?)
                """,
                (
                    V12_MANIFEST["name"], V12_MANIFEST["version"], V12_MANIFEST["war_room_rule_version"],
                    V12_MANIFEST["consistency_rule_version"], V12_MANIFEST["action_adapter_version"],
                    V12_MANIFEST["scoring_weights_version"], V12_MANIFEST["evidence_policy_version"],
                    dumps(V12_MANIFEST), manifest_hash, now, now, now,
                ),
            )
            row = conn.execute("SELECT * FROM rule_packs WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1").fetchone()
    if row is None:  # pragma: no cover - defensive conflict path
        raise RuntimeError("Unable to initialize the V1.2 active Rule Pack")
    return _from_row(row)


def active_rule_pack() -> RulePackManifest:
    return ensure_v12_active_rule_pack()


def list_rule_packs() -> list[RulePackManifest]:
    ensure_v12_active_rule_pack()
    with connect() as conn:
        rows = conn.execute("SELECT * FROM rule_packs ORDER BY created_at DESC, rowid DESC").fetchall()
    return [_from_row(row) for row in rows]


def get_rule_pack(rule_pack_id: str) -> RulePackManifest:
    ensure_v12_active_rule_pack()
    with connect() as conn:
        row = conn.execute("SELECT * FROM rule_packs WHERE rule_pack_id = ?", (rule_pack_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown Rule Pack: {rule_pack_id}")
    return _from_row(row)


def create_rule_pack(payload: RulePackCreateRequest, actor: UserIdentity) -> RulePackManifest:
    ensure_v12_active_rule_pack()
    manifest = payload.model_dump(mode="json", exclude={"supersedes_rule_pack_id"})
    rule_pack_id = f"rp_{uuid4().hex[:16]}"
    try:
        with connect() as conn:
            conn.execute(
                """
                INSERT INTO rule_packs
                (rule_pack_id, name, version, war_room_rule_version, consistency_rule_version,
                 action_adapter_version, scoring_weights_version, evidence_policy_version,
                 manifest_json, manifest_hash, status, creator_user_id, created_at, supersedes_rule_pack_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?)
                """,
                (
                    rule_pack_id, payload.name, payload.version, payload.war_room_rule_version,
                    payload.consistency_rule_version, payload.action_adapter_version,
                    payload.scoring_weights_version, payload.evidence_policy_version,
                    dumps(manifest), stable_hash(manifest), actor.user_id, _now(), payload.supersedes_rule_pack_id,
                ),
            )
    except sqlite3.IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Rule Pack version or manifest already exists") from exc
    return get_rule_pack(rule_pack_id)


def submit_rule_pack(rule_pack_id: str, actor: UserIdentity) -> RulePackManifest:
    pack = get_rule_pack(rule_pack_id)
    if pack.status != "draft" or pack.submitted_at:
        raise HTTPException(status_code=409, detail="Only an unsubmitted draft Rule Pack can be submitted")
    now = _now()
    with connect() as conn:
        conn.execute("UPDATE rule_packs SET submitted_at = ? WHERE rule_pack_id = ? AND status = 'draft'", (now, rule_pack_id))
        conn.execute(
            """
            INSERT INTO review_cases(review_id, review_type, resource_type, resource_id, severity, status, reason, payload_json, created_at)
            VALUES (?, 'rule_pack_promotion', 'rule_pack', ?, 'high', 'open', 'Rule Pack submitted for calibration and independent review', ?, ?)
            """,
            (f"rev_{uuid4().hex[:16]}", rule_pack_id, dumps({"submitted_by": actor.user_id, "manifest_hash": pack.manifest_hash}), now),
        )
    return get_rule_pack(rule_pack_id)


def approve_rule_pack(rule_pack_id: str, actor: UserIdentity, comment: str = "") -> RulePackManifest:
    pack = get_rule_pack(rule_pack_id)
    if not pack.submitted_at or pack.status != "draft":
        raise HTTPException(status_code=409, detail="Rule Pack is not awaiting approval")
    if pack.creator_user_id == actor.user_id:
        raise HTTPException(status_code=403, detail="Rule Pack creators cannot approve their own submission")
    if not _calibration_passed(rule_pack_id):
        raise HTTPException(status_code=422, detail="Rule Pack has not passed calibration gates")
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "INSERT INTO rule_pack_reviews(review_id, rule_pack_id, reviewer_user_id, decision, comment, created_at) VALUES (?, ?, ?, 'approve', ?, ?)",
            (f"rpr_{uuid4().hex[:16]}", rule_pack_id, actor.user_id, comment, _now()),
        )
        updated = conn.execute("UPDATE rule_packs SET status = 'candidate' WHERE rule_pack_id = ? AND status = 'draft'", (rule_pack_id,)).rowcount
        if updated != 1:
            raise HTTPException(status_code=409, detail="Rule Pack state changed concurrently")
    return get_rule_pack(rule_pack_id)


def activate_rule_pack(rule_pack_id: str, actor: UserIdentity) -> RulePackManifest:
    pack = get_rule_pack(rule_pack_id)
    if pack.status != "candidate":
        raise HTTPException(status_code=409, detail="Only a candidate Rule Pack can be activated")
    if not _calibration_passed(rule_pack_id):
        raise HTTPException(status_code=422, detail="Rule Pack no longer satisfies calibration gates")
    now = _now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("UPDATE rule_packs SET status = 'retired' WHERE status = 'active'")
        updated = conn.execute(
            "UPDATE rule_packs SET status = 'active', activated_at = ? WHERE rule_pack_id = ? AND status = 'candidate'",
            (now, rule_pack_id),
        ).rowcount
        if updated != 1:
            raise HTTPException(status_code=409, detail="Rule Pack activation conflict")
    return get_rule_pack(rule_pack_id)


def list_rule_pack_reviews(rule_pack_id: str) -> list[RulePackReview]:
    get_rule_pack(rule_pack_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM rule_pack_reviews WHERE rule_pack_id = ? ORDER BY created_at", (rule_pack_id,)).fetchall()
    return [RulePackReview(**dict(row)) for row in rows]


def trust_manifest_for_job(lifecycle_job_id: str | None = None) -> dict:
    if lifecycle_job_id:
        with connect() as conn:
            row = conn.execute("SELECT rule_pack_id, rule_pack_hash FROM run_jobs WHERE run_id = ?", (lifecycle_job_id,)).fetchone()
        if row and row["rule_pack_id"]:
            pack = get_rule_pack(row["rule_pack_id"])
            return {"rule_pack_id": pack.rule_pack_id, "rule_pack_version": pack.version, "rule_pack_hash": row["rule_pack_hash"], "status_at_export": pack.status}
    pack = active_rule_pack()
    return {"rule_pack_id": pack.rule_pack_id, "rule_pack_version": pack.version, "rule_pack_hash": pack.manifest_hash, "status_at_export": pack.status}


def _calibration_passed(rule_pack_id: str) -> bool:
    with connect() as conn:
        row = conn.execute(
            "SELECT gate_status, lifecycle_run_id, metrics_json FROM calibration_runs WHERE rule_pack_id = ? AND status = 'completed' ORDER BY completed_at DESC LIMIT 1",
            (rule_pack_id,),
        ).fetchone()
        artifact = conn.execute(
            "SELECT content_json, sha256 FROM run_artifacts WHERE run_id = ? AND artifact_type = 'calibration_metrics' ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (row["lifecycle_run_id"],),
        ).fetchone() if row else None
    if not row or row["gate_status"] != "passed" or not artifact:
        return False
    if hashlib.sha256(artifact["content_json"].encode("utf-8")).hexdigest() != artifact["sha256"]:
        return False
    metrics = loads(artifact["content_json"], {})
    return metrics == loads(row["metrics_json"], {}) and metrics.get("gate_status") == "passed" and all(metrics.get("gates", {}).values())


def _from_row(row) -> RulePackManifest:
    return RulePackManifest(
        rule_pack_id=row["rule_pack_id"], name=row["name"], version=row["version"],
        war_room_rule_version=row["war_room_rule_version"], consistency_rule_version=row["consistency_rule_version"],
        action_adapter_version=row["action_adapter_version"], scoring_weights_version=row["scoring_weights_version"],
        evidence_policy_version=row["evidence_policy_version"], manifest=loads(row["manifest_json"], {}),
        manifest_hash=row["manifest_hash"], status=row["status"], creator_user_id=row["creator_user_id"],
        created_at=row["created_at"], submitted_at=row["submitted_at"], activated_at=row["activated_at"],
        supersedes_rule_pack_id=row["supersedes_rule_pack_id"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
