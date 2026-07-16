from __future__ import annotations

from app.db.postgres import HybridRow, migration_plan, portability_report, render_postgres_schema, translate_migration, translate_query
from app.db.transfer import TABLE_ORDER, rows_digest


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
            "0005_v17_operations_control", "0006_v18_negotiation", "0007_v19_scenario_compiler", "0008_v110_continuous_intelligence",
    ]
    schema = render_postgres_schema()
    assert "CREATE TABLE ingestion_jobs" in schema
    assert "CREATE TABLE evidence_snapshots" in schema
    assert "CREATE TABLE worker_nodes" in schema
    assert "CREATE TABLE source_documents" in schema
    assert "CREATE TABLE scenario_drafts" in schema
    assert "max_document_bytes BIGINT" in schema
    assert "idx_users_username_lower" in schema
    assert "COLLATE NOCASE" not in schema


def test_migration_translation_removes_sqlite_only_types_and_collation():
    translated = translate_migration("name TEXT UNIQUE COLLATE NOCASE, score REAL, payload BLOB")
    assert translated == "name TEXT UNIQUE, score DOUBLE PRECISION, payload BYTEA"


def test_runtime_portability_gate_has_no_sqlite_query_blockers():
    report = portability_report()
    assert report["status"] == "ready"
    assert report["blocker_count"] == 0
    assert report["migration_count"] == 8


def test_database_transfer_order_covers_all_business_tables_and_dependencies():
    assert len(TABLE_ORDER) == 68
    assert TABLE_ORDER.index("users") < TABLE_ORDER.index("organizations")
    assert TABLE_ORDER.index("organizations") < TABLE_ORDER.index("organization_quotas")
    assert TABLE_ORDER.index("organization_quotas") < TABLE_ORDER.index("organization_quota_events")
    assert TABLE_ORDER.index("research_projects") < TABLE_ORDER.index("run_jobs")
    assert TABLE_ORDER.index("run_jobs") < TABLE_ORDER.index("run_events")
    assert TABLE_ORDER.index("evidence_snapshots") < TABLE_ORDER.index("ingestion_records")
    assert TABLE_ORDER.index("source_documents") < TABLE_ORDER.index("document_extraction_jobs")
    assert TABLE_ORDER.index("document_extractions") < TABLE_ORDER.index("scenario_candidates")
    assert TABLE_ORDER.index("scenario_drafts") < TABLE_ORDER.index("scenario_draft_reviews")


def test_transfer_digest_is_order_independent_and_binary_safe():
    first = [HybridRow(("b", memoryview(b"two")), ["id", "payload"]), HybridRow(("a", b"one"), ["id", "payload"])]
    second = list(reversed(first))
    assert rows_digest(first) == rows_digest(second)
    assert rows_digest(first) != rows_digest([HybridRow(("a", b"changed"), ["id", "payload"])])
