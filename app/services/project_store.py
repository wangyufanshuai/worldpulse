from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


DB_PATH = Path(os.getenv("WORLDPULSE_DB_PATH", "data/worldpulse.db"))


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS research_projects (
                project_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                question TEXT NOT NULL,
                region TEXT NOT NULL,
                asset_scope TEXT NOT NULL,
                event_window_days INTEGER NOT NULL,
                event_types TEXT NOT NULL,
                mode TEXT NOT NULL DEFAULT 'research',
                scenario_config TEXT NOT NULL DEFAULT '{}',
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_runs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                summary TEXT NOT NULL,
                data_snapshot TEXT NOT NULL,
                risk_snapshot TEXT NOT NULL,
                event_snapshot TEXT NOT NULL,
                simulation_snapshot TEXT NOT NULL,
                backtest_snapshot TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS causal_graph_snapshots (
                graph_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                nodes TEXT NOT NULL,
                edges TEXT NOT NULL,
                confidence REAL NOT NULL,
                evidence_sources TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
                FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS ai_reports (
                report_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                generated_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                key_findings TEXT NOT NULL,
                evidence TEXT NOT NULL,
                uncertainties TEXT NOT NULL,
                watch_signals TEXT NOT NULL,
                scenario_suggestions TEXT NOT NULL,
                citations TEXT NOT NULL DEFAULT '[]',
                markdown TEXT NOT NULL,
                disclaimer TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id),
                FOREIGN KEY(run_id) REFERENCES research_runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS run_jobs (
                run_id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                engine_mode TEXT NOT NULL,
                status TEXT NOT NULL,
                current_phase TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                seed INTEGER,
                parent_run_id TEXT,
                scenario_json TEXT NOT NULL,
                result_run_id TEXT,
                error_code TEXT,
                error_message TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                cancel_requested_at TEXT,
                pause_requested_at TEXT,
                FOREIGN KEY(project_id) REFERENCES research_projects(project_id)
            );

            CREATE TABLE IF NOT EXISTS run_events (
                run_id TEXT NOT NULL,
                seq INTEGER NOT NULL,
                event_type TEXT NOT NULL,
                phase TEXT NOT NULL,
                tick INTEGER,
                title TEXT NOT NULL,
                detail TEXT NOT NULL,
                payload TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                PRIMARY KEY(run_id, seq),
                FOREIGN KEY(run_id) REFERENCES run_jobs(run_id)
            );

            CREATE TABLE IF NOT EXISTS run_artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                artifact_type TEXT NOT NULL,
                schema_version TEXT NOT NULL,
                content_json TEXT NOT NULL,
                sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES run_jobs(run_id)
            );
            """
        )
        _ensure_column(conn, "ai_reports", "citations", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(conn, "research_projects", "mode", "TEXT NOT NULL DEFAULT 'research'")
        _ensure_column(conn, "research_projects", "scenario_config", "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, "run_jobs", "result_run_id", "TEXT")
        _ensure_column(conn, "run_jobs", "pause_requested_at", "TEXT")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
