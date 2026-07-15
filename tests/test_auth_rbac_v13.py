from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from app.main import app
from app.services import project_store
from app.services.auth import PASSWORD_HASHER, create_user


def _login(client: TestClient, username: str, password: str) -> str:
    response = client.post("/api/v3/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    assert response.cookies.get("worldpulse_session")
    return response.json()["csrf_token"]


def test_argon2_session_csrf_and_role_matrix(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "auth.db")
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "local")
    admin = create_user("admin", "correct horse battery", "Admin", "admin")
    create_user("viewer", "viewer secret phrase", "Viewer", "viewer")
    with project_store.connect() as conn:
        password_hash = conn.execute("SELECT password_hash FROM users WHERE user_id = ?", (admin.user_id,)).fetchone()[0]
    assert password_hash.startswith("$argon2id$")
    assert PASSWORD_HASHER.verify(password_hash, "correct horse battery")

    with TestClient(app) as client:
        assert client.get("/api/projects").status_code == 401
        csrf = _login(client, "admin", "correct horse battery")
        assert client.get("/api/v3/auth/me").json()["user"]["role"] == "admin"
        payload = {"title": "Auth project", "question": "RBAC?", "mode": "war_room", "event_types": ["trade"]}
        assert client.post("/api/projects", json=payload).status_code == 403
        assert client.post("/api/projects", json=payload, headers={"X-CSRF-Token": csrf}).status_code == 200

        viewer_csrf = _login(client, "viewer", "viewer secret phrase")
        assert client.get("/api/projects").status_code == 200
        denied = client.post("/api/projects", json=payload, headers={"X-CSRF-Token": viewer_csrf})
        assert denied.status_code == 403


def test_session_expiry_logout_and_token_hashing(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "sessions.db")
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "local")
    create_user("analyst", "analyst secret phrase", "Analyst", "analyst")
    with TestClient(app) as client:
        csrf = _login(client, "analyst", "analyst secret phrase")
        raw_cookie = client.cookies.get("worldpulse_session")
        with project_store.connect() as conn:
            row = conn.execute("SELECT token_hash FROM auth_sessions").fetchone()
            assert row[0] != raw_cookie
            conn.execute("UPDATE auth_sessions SET idle_expires_at = ?", ((datetime.now() - timedelta(seconds=1)).isoformat(),))
        assert client.get("/api/projects").status_code == 401

        csrf = _login(client, "analyst", "analyst secret phrase")
        response = client.post("/api/v3/auth/logout", headers={"X-CSRF-Token": csrf})
        assert response.status_code == 200
        assert client.get("/api/projects").status_code == 401


def test_login_rate_limit_and_audit_redaction(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "rate.db")
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "local")
    create_user("admin", "correct horse battery", "Admin", "admin")
    with TestClient(app) as client:
        for _ in range(5):
            assert client.post("/api/v3/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 401
        assert client.post("/api/v3/auth/login", json={"username": "admin", "password": "wrong"}).status_code == 429
    with project_store.connect() as conn:
        audit = " ".join(row[0] for row in conn.execute("SELECT detail_json FROM security_audit_events"))
    assert "wrong" not in audit


def test_production_requires_local_auth(monkeypatch):
    from app.services.auth import validate_security_config
    monkeypatch.setenv("WORLDPULSE_ENV", "production")
    monkeypatch.setenv("WORLDPULSE_AUTH_MODE", "disabled")
    try:
        validate_security_config()
    except RuntimeError as exc:
        assert "requires" in str(exc)
    else:
        raise AssertionError("production must reject disabled authentication")
