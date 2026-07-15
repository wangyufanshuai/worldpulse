from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException

from app.core.trust_models import ReviewCase, ReviewDecision, ReviewDecisionType, UserIdentity
from app.services.project_store import connect, dumps, init_db, loads


def create_review_case(
    review_type: str, resource_type: str, resource_id: str, reason: str, *,
    severity: str = "warning", payload: dict | None = None,
) -> ReviewCase:
    init_db()
    with connect() as conn:
        existing = conn.execute(
            "SELECT * FROM review_cases WHERE review_type = ? AND resource_type = ? AND resource_id = ? AND status = 'open' ORDER BY created_at DESC LIMIT 1",
            (review_type, resource_type, resource_id),
        ).fetchone()
        if existing:
            return _case(existing)
        review_id = f"rev_{uuid4().hex[:16]}"
        conn.execute(
            """
            INSERT INTO review_cases(review_id, review_type, resource_type, resource_id, severity, status, reason, payload_json, created_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?, ?, ?)
            """,
            (review_id, review_type, resource_type, resource_id, severity, reason, dumps(payload or {}), _now()),
        )
        row = conn.execute("SELECT * FROM review_cases WHERE review_id = ?", (review_id,)).fetchone()
    return _case(row)


def list_reviews(*, status: str | None = None, limit: int = 200) -> list[ReviewCase]:
    init_db()
    sql = "SELECT * FROM review_cases"
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY CASE severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_case(row) for row in rows]


def get_review(review_id: str) -> ReviewCase:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM review_cases WHERE review_id = ?", (review_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Unknown review case: {review_id}")
    return _case(row)


def decide_review(review_id: str, decision: ReviewDecisionType, comment: str, actor: UserIdentity) -> ReviewDecision:
    review = get_review(review_id)
    if review.status != "open":
        raise HTTPException(status_code=409, detail="Review Case is already closed")
    if decision == "approve_promotion" and review.review_type != "rule_pack_promotion":
        raise HTTPException(status_code=409, detail="Human review cannot promote an action or bypass the consistency evaluator")
    decision_id = f"rvd_{uuid4().hex[:16]}"
    now = _now()
    with connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        current = conn.execute("SELECT status FROM review_cases WHERE review_id = ?", (review_id,)).fetchone()
        if current is None or current["status"] != "open":
            raise HTTPException(status_code=409, detail="Review Case state changed concurrently")
        conn.execute(
            "INSERT INTO review_decisions(decision_id, review_id, reviewer_user_id, decision, comment, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (decision_id, review_id, actor.user_id, decision, comment, now),
        )
        conn.execute("UPDATE review_cases SET status = 'closed', closed_at = ? WHERE review_id = ?", (now, review_id))
    return ReviewDecision(decision_id=decision_id, review_id=review_id, reviewer_user_id=actor.user_id, decision=decision, comment=comment, created_at=now)


def review_decisions(review_id: str) -> list[ReviewDecision]:
    get_review(review_id)
    with connect() as conn:
        rows = conn.execute("SELECT * FROM review_decisions WHERE review_id = ? ORDER BY created_at, rowid", (review_id,)).fetchall()
    return [ReviewDecision(**dict(row)) for row in rows]


def ensure_artifact_integrity_reviews() -> None:
    init_db()
    with connect() as conn:
        rows = conn.execute("SELECT artifact_id, run_id, artifact_type, content_json, sha256 FROM run_artifacts").fetchall()
    import hashlib
    for row in rows:
        actual = hashlib.sha256(row["content_json"].encode("utf-8")).hexdigest()
        if actual != row["sha256"]:
            create_review_case(
                "artifact_integrity", "run_artifact", row["artifact_id"], "Artifact SHA-256 verification failed",
                severity="critical", payload={"run_id": row["run_id"], "artifact_type": row["artifact_type"], "expected": row["sha256"], "actual": actual},
            )


def review_run_diff_if_material(project_id: str, diff: dict, *, threshold: float = 15.0) -> None:
    values = [abs(float(diff.get("risk_delta") or 0))]
    war_room = (diff.get("changed_metrics") or {}).get("war_room") or {}
    values.extend(
        abs(float(value or 0)) for value in (
            war_room.get("global_risk_delta"),
            (war_room.get("top_chain_pressure_delta") or {}).get("delta"),
            (war_room.get("top_country_risk_delta") or {}).get("delta"),
        )
    )
    if max(values, default=0) >= threshold:
        create_review_case(
            "material_run_diff", "project_run_diff", f"{project_id}:{diff.get('base_run_id')}:{diff.get('target_run_id')}",
            f"Run Diff exceeded the {threshold:.1f}-point review threshold", severity="high",
            payload={"threshold": threshold, "max_absolute_delta": max(values), "summary": diff.get("summary")},
        )


def _case(row) -> ReviewCase:
    return ReviewCase(
        review_id=row["review_id"], review_type=row["review_type"], resource_type=row["resource_type"],
        resource_id=row["resource_id"], severity=row["severity"], status=row["status"], reason=row["reason"],
        payload=loads(row["payload_json"], {}), assigned_to_user_id=row["assigned_to_user_id"],
        created_at=row["created_at"], closed_at=row["closed_at"],
    )


def _now() -> str:
    return datetime.now().isoformat(timespec="milliseconds")
