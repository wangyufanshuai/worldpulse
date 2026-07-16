from __future__ import annotations

import base64
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from app.db.migrations import verify_schema
from app.db.postgres import apply_postgres_migrations, connect_postgres, verify_postgres_schema


# Foreign-key-safe order. schema_migrations is intentionally excluded because the
# PostgreSQL target owns its canonical migration ledger.
TABLE_ORDER = (
    "users",
    "organizations",
    "organization_members",
    "organization_quotas",
    "organization_quota_events",
    "worker_nodes",
    "research_projects",
    "organization_resources",
    "research_runs",
    "causal_graph_snapshots",
    "ai_reports",
    "chat_messages",
    "rule_packs",
    "rule_pack_reviews",
    "evaluation_suites",
    "evaluation_cases",
    "evaluation_batches",
    "historical_benchmark_suites",
    "historical_benchmark_cases",
    "historical_benchmark_evidence",
    "run_jobs",
    "source_documents",
    "document_extraction_jobs",
    "document_extraction_event_counters",
    "document_extraction_events",
    "document_extractions",
    "agent_packs",
    "negotiation_sessions",
    "run_event_counters",
    "run_events",
    "run_attempts",
    "run_steps",
    "run_artifacts",
    "negotiation_rounds",
    "negotiation_messages",
    "negotiation_commitments",
    "negotiation_commitment_events",
    "calibration_cases",
    "calibration_runs",
    "calibration_results",
    "review_cases",
    "review_decisions",
    "security_audit_events",
    "auth_sessions",
    "evidence_sources",
    "evidence_snapshots",
    "evidence_claims",
    "evidence_links",
    "evidence_packs",
    "evidence_pack_items",
    "scenario_candidates",
    "scenario_candidate_decisions",
    "scenario_drafts",
    "scenario_draft_items",
    "scenario_draft_reviews",
    "ingestion_policies",
    "data_connectors",
    "ingestion_jobs",
    "ingestion_event_counters",
    "ingestion_events",
    "ingestion_records",
    "monitoring_sources",
    "monitoring_poll_jobs",
    "monitoring_poll_event_counters",
    "monitoring_poll_events",
    "monitoring_entries",
    "monitoring_watchlists",
    "monitoring_watch_rules",
    "intelligence_alerts",
    "intelligence_alert_events",
    "alert_subscriptions",
    "organization_notification_counters",
    "in_app_notifications",
    "webhook_deliveries",
    "evaluation_members",
    "evaluation_metrics",
    "evaluation_event_counters",
    "evaluation_events",
    "historical_label_packs",
    "historical_label_pack_reviews",
    "evaluation_gate_manifests",
    "evaluation_verification_results",
)


def copy_sqlite_to_postgres(
    source: str | Path,
    target_url: str,
    *,
    verify_only: bool = False,
) -> dict[str, Any]:
    source_path = Path(source).resolve()
    verify_schema(source_path)
    apply_postgres_migrations(target_url)
    verify_postgres_schema(target_url)

    sqlite_connection = sqlite3.connect(f"file:{source_path.as_posix()}?mode=ro", uri=True)
    sqlite_connection.row_factory = sqlite3.Row
    target = connect_postgres(target_url)
    copied: dict[str, int] = {}
    try:
        source_tables = _sqlite_tables(sqlite_connection)
        missing = [table for table in TABLE_ORDER if table not in source_tables]
        if missing:
            raise RuntimeError(f"SQLite source is missing required tables: {', '.join(missing)}")

        if not verify_only:
            for table in TABLE_ORDER:
                rows = _source_rows(sqlite_connection, table)
                if rows:
                    columns = list(rows[0].keys())
                    placeholders = ", ".join("?" for _ in columns)
                    statement = (
                        f"INSERT INTO {table} ({', '.join(columns)}) "
                        f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
                    )
                    for row in rows:
                        target.execute(statement, tuple(row[column] for column in columns))
                copied[table] = len(rows)

        verification = _verify_all_tables(sqlite_connection, target)
        if not verification["verified"]:
            failures = [item["table"] for item in verification["tables"] if not item["matches"]]
            raise RuntimeError(f"Database transfer verification failed for: {', '.join(failures)}")
        target.commit()
        return {
            "status": "ok",
            "source": str(source_path),
            "target_backend": "postgresql",
            "mode": "verify-only" if verify_only else "copy-and-verify",
            "tables": len(TABLE_ORDER),
            "rows": sum(item["source_count"] for item in verification["tables"]),
            "copied": copied,
            "verification": verification,
        }
    except Exception:
        target.rollback()
        raise
    finally:
        sqlite_connection.close()
        target.close()


def _sqlite_tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    }


def _source_rows(connection: sqlite3.Connection, table: str) -> list[sqlite3.Row]:
    return connection.execute(f"SELECT * FROM {table}").fetchall()


def _verify_all_tables(source: sqlite3.Connection, target) -> dict[str, Any]:
    tables: list[dict[str, Any]] = []
    for table in TABLE_ORDER:
        source_rows = _source_rows(source, table)
        target_rows = target.execute(f"SELECT * FROM {table}").fetchall()
        source_digest = rows_digest(source_rows)
        target_digest = rows_digest(target_rows)
        matches = len(source_rows) == len(target_rows) and source_digest == target_digest
        tables.append(
            {
                "table": table,
                "source_count": len(source_rows),
                "target_count": len(target_rows),
                "sha256": source_digest,
                "matches": matches,
            }
        )
    return {"verified": all(item["matches"] for item in tables), "tables": tables}


def rows_digest(rows: Iterable[Any]) -> str:
    encoded_rows = []
    for row in rows:
        keys = list(row.keys())
        payload = {key: _normalise(row[key]) for key in sorted(keys)}
        encoded_rows.append(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
    encoded_rows.sort()
    return hashlib.sha256("\n".join(encoded_rows).encode("utf-8")).hexdigest()


def _normalise(value: Any) -> Any:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, bytes):
        return {"$binary": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float):
        return {"$float": format(value, ".17g")}
    return value
