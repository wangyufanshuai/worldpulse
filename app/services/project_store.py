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
            """
        )
        _ensure_column(conn, "ai_reports", "citations", "TEXT NOT NULL DEFAULT '[]'")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
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
