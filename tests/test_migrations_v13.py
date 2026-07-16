from __future__ import annotations

import sqlite3

import pytest

from app.db.migrations import MIGRATIONS_DIR, apply_migrations, migration_status, verify_schema


def test_fresh_database_applies_versioned_schema(tmp_path):
    database = tmp_path / "fresh.db"
    applied = apply_migrations(database)
    assert [item.version for item in applied] == [
        "0001_v12_baseline", "0002_v13_trust_governance", "0003_v14_evidence_registry",
        "0004_v15_organization_ingestion", "0005_v17_operations_control",
    ]
    assert verify_schema(database)["status"] == "ok"
    with sqlite3.connect(database) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(run_jobs)")}
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"job_kind", "rule_pack_id", "rule_pack_hash"} <= columns
    assert {"evidence_sources", "evidence_snapshots", "evidence_claims", "evidence_links", "evidence_packs"} <= tables
    assert {"organizations", "organization_members", "data_connectors", "ingestion_jobs", "ingestion_records"} <= tables
    assert {"worker_nodes", "organization_quotas", "organization_quota_events"} <= tables


def test_existing_v12_database_is_registered_without_rebuilding(tmp_path):
    database = tmp_path / "existing.db"
    marker = "project_keep_me"
    with sqlite3.connect(database) as conn:
        conn.executescript((MIGRATIONS_DIR / "0001_v12_baseline.sql").read_text(encoding="utf-8"))
        conn.execute(
            "INSERT INTO research_projects VALUES (?, 'title', 'question', 'global', 'all', 30, '[]', 'war_room', '{}', 'ready', 'now', 'now')",
            (marker,),
        )
    applied = apply_migrations(database)
    assert [item.version for item in applied] == [
        "0002_v13_trust_governance", "0003_v14_evidence_registry", "0004_v15_organization_ingestion",
        "0005_v17_operations_control",
    ]
    with sqlite3.connect(database) as conn:
        assert conn.execute("SELECT project_id FROM research_projects").fetchone()[0] == marker
    assert all(item["applied"] for item in migration_status(database))


def test_migrations_are_repeatable(tmp_path):
    database = tmp_path / "repeat.db"
    apply_migrations(database)
    assert apply_migrations(database) == []


def test_failed_migration_restores_database(monkeypatch, tmp_path):
    database = tmp_path / "restore.db"
    apply_migrations(database)
    before = database.read_bytes()
    bad = tmp_path / "9999_bad.sql"
    bad.write_text("CREATE TABLE partial_table(id TEXT); THIS IS INVALID;", encoding="utf-8")
    from app.db import migrations
    original = migrations._files
    monkeypatch.setattr(migrations, "_files", lambda: original() + [bad])
    with pytest.raises(Exception):
        apply_migrations(database)
    assert database.read_bytes() == before
