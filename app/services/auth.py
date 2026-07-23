from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import os
import secrets
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from fastapi import HTTPException, Request

from app.core.trust_models import SessionStatus, UserIdentity, UserRole
from app.services.project_store import connect, dumps, init_db, loads
from app.services.security import redact_structure


SESSION_COOKIE = "worldpulse_session"
CSRF_COOKIE = "worldpulse_csrf"
IDLE_MINUTES = 30
ABSOLUTE_HOURS = 8
PASSWORD_HASHER = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=4, hash_len=32, salt_len=16)
ROLE_PERMISSIONS = {
    "admin": {"read", "project_write", "run", "calibration", "review", "rule_submit", "rule_approve", "rule_activate", "users", "organization_admin", "ingestion_write", "operations", "monitoring_write", "notification_write"},
    "analyst": {"read", "project_write", "run", "calibration", "rule_submit", "ingestion_write", "monitoring_write", "notification_write"},
    "reviewer": {"read", "review", "rule_approve", "notification_write"},
    "viewer": {"read", "notification_write"},
}


def auth_mode() -> str:
    value = os.getenv("WORLDPULSE_AUTH_MODE", "disabled").strip().lower()
    if value not in {"disabled", "local"}:
        raise RuntimeError("WORLDPULSE_AUTH_MODE must be disabled or local")
    return value


def validate_security_config() -> None:
    environment = os.getenv("WORLDPULSE_ENV", "development").strip().lower()
    if environment == "production" and auth_mode() != "local":
        raise RuntimeError("Production requires WORLDPULSE_AUTH_MODE=local")
    origins = configured_cors_origins()
    if environment == "production" and "*" in origins:
        raise RuntimeError("Production CORS origins cannot contain '*'")


def configured_cors_origins() -> list[str]:
    raw = os.getenv("WORLDPULSE_CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173")
    return [item.strip().rstrip("/") for item in raw.split(",") if item.strip()]


def create_user(username: str, password: str, display_name: str, role: UserRole) -> UserIdentity:
    init_db()
    normalized = username.strip().lower()
    if not normalized or len(normalized) > 80:
        raise ValueError("Username must contain 1-80 characters")
    if len(password) < 12:
        raise ValueError("Password must contain at least 12 characters")
    if role not in ROLE_PERMISSIONS:
        raise ValueError(f"Unknown role: {role}")
    user_id = f"usr_{uuid4().hex[:16]}"
    now = _now()
    try:
        with connect() as conn:
            conn.execute(
                "INSERT INTO users(user_id, username, password_hash, display_name, role, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, normalized, PASSWORD_HASHER.hash(password), display_name.strip() or normalized, role, now, now),
            )
    except Exception as exc:
        if "UNIQUE" in str(exc).upper():
            raise ValueError("Username already exists") from exc
        raise
    identity = UserIdentity(user_id=user_id, username=normalized, display_name=display_name.strip() or normalized, role=role)
    from app.services.organizations import ensure_default_membership

    ensure_default_membership(identity)
    return identity


def authenticate_local_user(username: str, password: str, *, required_role: UserRole | None = None) -> UserIdentity:
    """Authenticate a local account for an interactive offline governance command."""
    init_db()
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE LOWER(username) = LOWER(?)",
            (username.strip(),),
        ).fetchone()
    valid = False
    if row is not None and bool(row["is_active"]):
        try:
            valid = PASSWORD_HASHER.verify(row["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            valid = False
    if not valid:
        record_security_event(
            "benchmark.review.authentication",
            "denied",
            detail={"username": username.strip()[:80]},
        )
        raise HTTPException(status_code=401, detail="Invalid username or password")
    identity = _identity(row)
    if required_role is not None and identity.role != required_role:
        record_security_event(
            "benchmark.review.authorization",
            "denied",
            actor_user_id=identity.user_id,
            detail={"required_role": required_role, "actual_role": identity.role},
        )
        raise HTTPException(status_code=403, detail=f"Role {identity.role} cannot approve the pilot dossier")
    record_security_event(
        "benchmark.review.authentication",
        "allowed",
        actor_user_id=identity.user_id,
    )
    return identity


def ensure_system_user() -> UserIdentity:
    init_db()
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE user_id = 'usr_system'").fetchone()
        if row is None:
            now = _now()
            conn.execute(
                "INSERT INTO users(user_id, username, password_hash, display_name, role, is_active, created_at, updated_at) VALUES ('usr_system', '__system__', '!disabled', 'Local development', 'admin', 0, ?, ?)",
                (now, now),
            )
            row = conn.execute("SELECT * FROM users WHERE user_id = 'usr_system'").fetchone()
    identity = _identity(row, active_override=True)
    from app.services.organizations import ensure_default_membership

    ensure_default_membership(identity)
    return identity


def login(username: str, password: str, request: Request) -> tuple[SessionStatus, str, str]:
    init_db()
    ip = _client_ip(request)
    enforce_rate_limit("auth.login.failed", ip, limit=5, window_seconds=300)
    with connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE LOWER(username) = LOWER(?)", (username.strip(),)).fetchone()
    valid = False
    if row is not None and bool(row["is_active"]):
        try:
            valid = PASSWORD_HASHER.verify(row["password_hash"], password)
        except (VerifyMismatchError, InvalidHashError):
            valid = False
    if not valid:
        record_security_event("auth.login.failed", "denied", client_ip=ip, detail={"username": username.strip()[:80]})
        raise HTTPException(status_code=401, detail="Invalid username or password")
    now = datetime.now()
    idle = now + timedelta(minutes=IDLE_MINUTES)
    absolute = now + timedelta(hours=ABSOLUTE_HOURS)
    token = secrets.token_urlsafe(48)
    csrf = secrets.token_urlsafe(32)
    session_id = f"ses_{uuid4().hex[:20]}"
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO auth_sessions(session_id, user_id, token_hash, csrf_hash, created_at, last_seen_at,
                                      idle_expires_at, absolute_expires_at, client_ip, user_agent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, row["user_id"], _hash(token), _hash(csrf), _iso(now), _iso(now), _iso(idle), _iso(absolute), ip, request.headers.get("user-agent", "")[:300]),
        )
        conn.execute("UPDATE users SET last_login_at = ?, updated_at = ? WHERE user_id = ?", (_iso(now), _iso(now), row["user_id"]))
    identity = _identity(row)
    record_security_event("auth.login.succeeded", "allowed", actor_user_id=identity.user_id, client_ip=ip)
    return SessionStatus(authenticated=True, user=identity, csrf_token=csrf, idle_expires_at=_iso(idle), absolute_expires_at=_iso(absolute)), token, csrf


def authenticate_request(request: Request, *, touch: bool = True) -> UserIdentity:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise HTTPException(status_code=401, detail="Authentication required")
    init_db()
    with connect() as conn:
        row = conn.execute(
            """
            SELECT s.*, u.username, u.display_name, u.role, u.is_active
            FROM auth_sessions s JOIN users u ON u.user_id = s.user_id
            WHERE s.token_hash = ?
            """,
            (_hash(token),),
        ).fetchone()
        now = datetime.now()
        if row is None or row["revoked_at"] or not bool(row["is_active"]):
            raise HTTPException(status_code=401, detail="Session is invalid")
        if datetime.fromisoformat(row["idle_expires_at"]) <= now or datetime.fromisoformat(row["absolute_expires_at"]) <= now:
            conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?", (_iso(now), row["session_id"]))
            raise HTTPException(status_code=401, detail="Session expired")
        if touch:
            next_idle = min(now + timedelta(minutes=IDLE_MINUTES), datetime.fromisoformat(row["absolute_expires_at"]))
            conn.execute("UPDATE auth_sessions SET last_seen_at = ?, idle_expires_at = ? WHERE session_id = ?", (_iso(now), _iso(next_idle), row["session_id"]))
    request.state.session_id = row["session_id"]
    request.state.csrf_hash = row["csrf_hash"]
    return UserIdentity(user_id=row["user_id"], username=row["username"], display_name=row["display_name"], role=row["role"], is_active=True)


def require_csrf(request: Request) -> None:
    supplied = request.headers.get("x-csrf-token")
    cookie = request.cookies.get(CSRF_COOKIE)
    expected = getattr(request.state, "csrf_hash", None)
    if not supplied or not cookie or not expected or not secrets.compare_digest(supplied, cookie) or not secrets.compare_digest(_hash(supplied), expected):
        raise HTTPException(status_code=403, detail="CSRF validation failed")


def logout(request: Request) -> None:
    session_id = getattr(request.state, "session_id", None)
    if session_id:
        with connect() as conn:
            conn.execute("UPDATE auth_sessions SET revoked_at = ? WHERE session_id = ?", (_now(), session_id))


def permission_for_request(method: str, path: str) -> str:
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if path.startswith("/api/v6/workers"):
        return "operations"
    if path.startswith("/api/v6/organizations") and path.endswith("/quota"):
        return "organization_admin"
    if path.startswith("/api/v9/"):
        if "/notifications" in path or "/notification-subscriptions" in path:
            return "notification_write"
        return "monitoring_write"
    if path.startswith("/api/v10/"):
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        return "run"
    if path.startswith("/api/v11/"):
        if method.upper() in {"GET", "HEAD", "OPTIONS"}:
            return "read"
        if "/label-packs/" in path and path.endswith("/approve"):
            return "review"
        if path.endswith("/label-packs"):
            return "organization_admin"
        return "run"
    if path.startswith("/api/v8/") and path.endswith("/review"):
        return "review"
    if path.endswith("/activate"):
        return "rule_activate"
    if path.endswith("/approve"):
        return "rule_approve"
    if "/reviews" in path:
        return "review"
    if "/calibration" in path:
        return "calibration"
    if "/rule-packs" in path:
        return "rule_submit"
    if path.startswith("/api/v5/organizations"):
        if "/ingestion" in path:
            return "ingestion_write"
        if "/projects" in path:
            return "project_write"
        return "organization_admin"
    if "/runs" in path or "/war-room/run" in path:
        return "run"
    return "project_write"


def require_permission(identity: UserIdentity, permission: str) -> None:
    if permission not in ROLE_PERMISSIONS.get(identity.role, set()):
        raise HTTPException(status_code=403, detail=f"Role {identity.role} lacks permission: {permission}")


def enforce_rate_limit(event_type: str, key: str, *, limit: int, window_seconds: int) -> None:
    cutoff = _iso(datetime.now() - timedelta(seconds=window_seconds))
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM security_audit_events WHERE event_type = ? AND client_ip = ? AND created_at >= ?",
            (event_type, key, cutoff),
        ).fetchone()[0]
    if count >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def enforce_actor_rate_limit(event_type: str, actor_user_id: str, *, limit: int, window_seconds: int) -> None:
    cutoff = _iso(datetime.now() - timedelta(seconds=window_seconds))
    with connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM security_audit_events WHERE event_type = ? AND actor_user_id = ? AND created_at >= ?",
            (event_type, actor_user_id, cutoff),
        ).fetchone()[0]
    if count >= limit:
        raise HTTPException(status_code=429, detail="Rate limit exceeded")


def record_security_event(
    event_type: str, outcome: str, *, actor_user_id: str | None = None, resource_type: str | None = None,
    resource_id: str | None = None, detail: dict | None = None, client_ip: str | None = None,
) -> None:
    init_db()
    safe_detail = redact_structure(detail or {})
    with connect() as conn:
        conn.execute(
            "INSERT INTO security_audit_events(event_id, actor_user_id, event_type, outcome, resource_type, resource_id, detail_json, client_ip, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (f"sec_{uuid4().hex[:20]}", actor_user_id, event_type, outcome, resource_type, resource_id, dumps(safe_detail), client_ip, _now()),
        )


def _identity(row, *, active_override: bool | None = None) -> UserIdentity:
    return UserIdentity(
        user_id=row["user_id"], username=row["username"], display_name=row["display_name"], role=row["role"],
        is_active=bool(row["is_active"]) if active_override is None else active_override,
    )


def _hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="milliseconds")


def _now() -> str:
    return _iso(datetime.now())
