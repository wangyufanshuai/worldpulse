from __future__ import annotations

from pathlib import Path
import hashlib
import hmac

from fastapi import HTTPException
from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services import project_store
from app.services.continuous_intelligence import feed
from app.services.continuous_intelligence.feed import FeedFetchResult
from app.workers.ingestion_worker import process_once


ORG = "org_default"


def _setup(monkeypatch, tmp_path):
    monkeypatch.setattr(project_store, "DB_PATH", tmp_path / "v110.db")
    monkeypatch.setenv("WORLDPULSE_UPLOAD_ROOT", str(tmp_path / "uploads"))
    monkeypatch.setenv("WORLDPULSE_CONTINUOUS_INTELLIGENCE", "1")
    monkeypatch.setenv("WORLDPULSE_FEED_ALLOW_HTTP", "0")
    client = TestClient(app)
    project = client.post("/api/projects", json={"title": "Continuous intelligence", "question": "Watch public feeds", "mode": "war_room"})
    assert project.status_code == 200, project.text
    return client, project.json()["project_id"]


def test_feed_parser_is_deterministic_and_private_urls_fail():
    content = b"<rss><channel><item><guid>x1</guid><title>China sanctions</title><link>https://example.com/x1</link><pubDate>Wed, 01 Jan 2025 00:00:00 GMT</pubDate><description>China discusses sanctions.</description></item></channel></rss>"
    first = feed.parse_feed(content, "rss_atom", cutoff_at="2025-01-02T00:00:00+00:00")
    second = feed.parse_feed(content, "rss_atom", cutoff_at="2025-01-02T00:00:00+00:00")
    assert first == second
    assert first[0]["stable_key"] == "x1"
    with pytest.raises(HTTPException):
        feed.validate_remote_url("https://127.0.0.1/feed.xml", resolve_dns=False)


def test_json_feed_parser_rejects_future_entries_and_keeps_stable_revision_hash():
    content = b'{"version":"https://jsonfeed.org/version/1.1","items":[{"id":"j1","title":"Energy shipping","url":"https://example.com/j1","date_published":"2025-01-01T00:00:00Z","content_text":"Energy and shipping update"}]}'
    first = feed.parse_feed(content, "json_feed", cutoff_at="2025-01-02T00:00:00+00:00")
    second = feed.parse_feed(content, "json_feed", cutoff_at="2025-01-02T00:00:00+00:00")
    assert first == second
    assert first[0]["stable_key"] == "j1"
    with pytest.raises(HTTPException):
        feed.parse_feed(content, "json_feed", cutoff_at="2024-12-31T00:00:00+00:00")


def test_monitoring_poll_materializes_governed_candidate(monkeypatch, tmp_path):
    client, project_id = _setup(monkeypatch, tmp_path)

    def fake_fetch(url, *, etag=None, last_modified=None):
        return FeedFetchResult(
            status_code=200,
            content=b"<rss><channel><item><guid>x1</guid><title>China sanctions update</title><link>https://example.com/x1</link><pubDate>Wed, 01 Jan 2025 00:00:00 GMT</pubDate><description>China and sanctions are discussed.</description></item></channel></rss>",
            content_type="application/rss+xml", etag='"one"', last_modified=None, final_url=url,
        )

    monkeypatch.setattr("app.services.continuous_intelligence.service.fetch_feed", fake_fetch)
    source = client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/monitoring/sources", json={
        "name": "Public Feed", "source_type": "rss_atom", "feed_url": "https://example.com/feed.xml",
        "publisher": "Example", "license_name": "Public", "category": "conflict",
    })
    assert source.status_code == 200, source.text
    source_id = source.json()["source_id"]
    assert client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/monitoring/sources/{source_id}/status", json={"status": "active"}).status_code == 200
    watchlist = client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/watchlists", json={
        "name": "China watch", "rules": [{"candidate_type": "country", "canonical_value": "CHN", "severity": "high"}],
    })
    assert watchlist.status_code == 200, watchlist.text
    watchlist_id = watchlist.json()["watchlist_id"]
    assert client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/watchlists/{watchlist_id}/activate").status_code == 200
    queued = client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/monitoring/sources/{source_id}/poll")
    assert queued.status_code == 200, queued.text
    assert process_once("v110-test") is True
    assert process_once("v110-test") is True
    alerts = client.get(f"/api/v9/organizations/{ORG}/projects/{project_id}/alerts").json()
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "high"
    assert alerts[0]["lineage"]["pipeline_status"] == "ready"
    candidates = client.get(f"/api/v8/organizations/{ORG}/projects/{project_id}/scenario-candidates").json()
    assert any(
        item["canonical_value"] == "CHN"
        and item["latest_decision"] is None
        and item["origin"]["kind"] == "continuous_intelligence"
        for item in candidates
    )
    notifications = client.get("/api/v9/notifications").json()
    assert notifications
    assert [item["seq"] for item in notifications] == sorted({item["seq"] for item in notifications})
    notification_count = len(notifications)

    monkeypatch.setenv("WORLDPULSE_WEBHOOK_HOST_ALLOWLIST", "hooks.example.com")
    monkeypatch.setenv("WORLDPULSE_WEBHOOK_SECRET_TEST", "governed-test-secret")
    subscription = client.post("/api/v9/notification-subscriptions", json={
        "channel": "webhook", "project_id": project_id, "endpoint_url": "https://hooks.example.com/worldpulse",
        "secret_ref": "TEST", "min_severity": "warning",
    })
    assert subscription.status_code == 200, subscription.text
    queued_delivery = client.post(f"/api/v9/notification-subscriptions/{subscription.json()['subscription_id']}/test")
    assert queued_delivery.status_code == 200, queued_delivery.text
    captured = {}

    class _Response:
        status_code = 204

    def fake_post(_session, url, *, data, headers, timeout, allow_redirects):
        captured.update(url=url, data=data, headers=headers, timeout=timeout, allow_redirects=allow_redirects)
        return _Response()

    monkeypatch.setattr("app.services.continuous_intelligence.service.validate_remote_url", lambda url, **_kwargs: url)
    monkeypatch.setattr("app.services.continuous_intelligence.service.requests.Session.post", fake_post)
    assert process_once("v110-test") is True
    timestamp = captured["headers"]["X-WorldPulse-Timestamp"]
    expected_signature = hmac.new(b"governed-test-secret", timestamp.encode("ascii") + b"." + captured["data"], hashlib.sha256).hexdigest()
    assert captured["headers"]["X-WorldPulse-Signature"] == f"v1={expected_signature}"
    assert captured["allow_redirects"] is False

    repeat = client.post(f"/api/v9/organizations/{ORG}/projects/{project_id}/monitoring/sources/{source_id}/poll")
    assert repeat.status_code == 200
    assert process_once("v110-test") is True
    assert len(client.get(f"/api/v9/organizations/{ORG}/projects/{project_id}/alerts").json()) == 1
    repeated_notifications = client.get("/api/v9/notifications").json()
    assert len(repeated_notifications) == notification_count, [item["event_type"] for item in repeated_notifications]
