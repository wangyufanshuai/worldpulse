from __future__ import annotations

from app.db.postgres import HybridRow, migration_plan, portability_report, render_postgres_schema, translate_migration, translate_query


def test_runtime_query_translation_and_hybrid_rows_preserve_contract():
    assert translate_query("BEGIN IMMEDIATE") == "BEGIN"
    assert translate_query("SELECT * FROM jobs WHERE id = ? AND status = ?") == "SELECT * FROM jobs WHERE id = %s AND status = %s"
    row = HybridRow(("job-1", 3), ["job_id", "count"])
    assert row[0] == row["job_id"] == "job-1"
    assert row[1] == row["count"] == 3
    assert row.keys() == ["job_id", "count"]


def test_postgres_schema_is_generated_from_all_numbered_migrations():
    plans = migration_plan()
    assert [item.version for item in plans] == [
        "0001_v12_baseline", "0002_v13_trust_governance",
        "0003_v14_evidence_registry", "0004_v15_organization_ingestion",
    ]
    schema = render_postgres_schema()
    assert "CREATE TABLE ingestion_jobs" in schema
    assert "CREATE TABLE evidence_snapshots" in schema
    assert "idx_users_username_lower" in schema
    assert "COLLATE NOCASE" not in schema


def test_migration_translation_removes_sqlite_only_types_and_collation():
    translated = translate_migration("name TEXT UNIQUE COLLATE NOCASE, score REAL, payload BLOB")
    assert translated == "name TEXT UNIQUE, score DOUBLE PRECISION, payload BYTEA"


def test_runtime_portability_gate_has_no_sqlite_query_blockers():
    report = portability_report()
    assert report["status"] == "ready"
    assert report["blocker_count"] == 0
    assert report["migration_count"] == 4
