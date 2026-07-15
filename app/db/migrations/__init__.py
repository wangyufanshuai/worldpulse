from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
import os
from pathlib import Path
import shutil
import sqlite3


MIGRATIONS_DIR = Path(__file__).parent
BASELINE_TABLES = {
    "research_projects", "research_runs", "causal_graph_snapshots", "ai_reports",
    "chat_messages", "run_jobs", "run_events", "run_artifacts", "run_event_counters",
    "run_steps", "run_attempts",
}
V13_TABLES = {
    "users", "auth_sessions", "security_audit_events", "rule_packs", "rule_pack_reviews",
    "calibration_cases", "calibration_runs", "calibration_results", "review_cases", "review_decisions",
}


@dataclass(frozen=True)
class MigrationState:
    version: str
    checksum: str
    applied: bool
    applied_at: str | None = None


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _ensure_registry(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )


def _tables(conn: sqlite3.Connection) -> set[str]:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _validate_baseline(conn: sqlite3.Connection) -> None:
    missing = BASELINE_TABLES - _tables(conn)
    if missing:
        raise RuntimeError(f"Existing database is not a valid V1.2 baseline; missing tables: {sorted(missing)}")
    required_columns = {
        "run_jobs": {"worker_id", "lease_expires_at", "attempt_count", "current_attempt_id", "max_attempts", "request_hash", "idempotency_key"},
        "run_artifacts": {"attempt_id", "step_id", "artifact_version", "supersedes_artifact_id"},
    }
    for table, expected in required_columns.items():
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        missing_columns = expected - actual
        if missing_columns:
            raise RuntimeError(f"Existing V1.2 table {table} is missing columns: {sorted(missing_columns)}")


def _register_existing_baseline(conn: sqlite3.Connection, migration: Path) -> None:
    tables = _tables(conn)
    if not tables.intersection(BASELINE_TABLES):
        return
    if not BASELINE_TABLES.issubset(tables):
        _import_known_legacy_schema(conn, migration)
    _validate_baseline(conn)
    conn.execute(
        "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
        (migration.stem, _checksum(migration), datetime.now().isoformat(timespec="milliseconds")),
    )


def _import_known_legacy_schema(conn: sqlite3.Connection, migration: Path) -> None:
    """Upgrade known pre-V1.2 partial schemas before registering the baseline.

    This is deliberately bounded to the tables and additive columns that the old
    startup initializer supported. Unknown structures still fail baseline checks.
    """
    sql = migration.read_text(encoding="utf-8")
    sql = sql.replace("CREATE TABLE ", "CREATE TABLE IF NOT EXISTS ")
    sql = sql.replace("CREATE UNIQUE INDEX ", "CREATE UNIQUE INDEX IF NOT EXISTS ")
    sql = sql.replace("CREATE INDEX ", "CREATE INDEX IF NOT EXISTS ")
    conn.executescript(sql)
    additions = {
        "ai_reports": {"citations": "TEXT NOT NULL DEFAULT '[]'"},
        "research_projects": {
            "mode": "TEXT NOT NULL DEFAULT 'research'",
            "scenario_config": "TEXT NOT NULL DEFAULT '{}'",
        },
        "run_jobs": {
            "result_run_id": "TEXT", "pause_requested_at": "TEXT", "worker_id": "TEXT",
            "lease_expires_at": "TEXT", "attempt_count": "INTEGER NOT NULL DEFAULT 0",
            "current_attempt_id": "TEXT", "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_attempt_at": "TEXT", "terminal_reason": "TEXT", "request_hash": "TEXT",
            "idempotency_key": "TEXT",
        },
        "run_artifacts": {
            "attempt_id": "TEXT", "step_id": "TEXT", "artifact_version": "INTEGER NOT NULL DEFAULT 1",
            "supersedes_artifact_id": "TEXT",
        },
    }
    for table, columns in additions.items():
        actual = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column, definition in columns.items():
            if column not in actual:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.execute(
        "INSERT OR IGNORE INTO run_event_counters(run_id, next_seq) "
        "SELECT run_id, COALESCE(MAX(seq), 0) + 1 FROM run_events GROUP BY run_id"
    )


def apply_migrations(db_path: str | Path, *, backup: bool = True) -> list[MigrationState]:
    target = Path(db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    existed = target.exists() and target.stat().st_size > 0
    if existed:
        statuses = migration_status(target)
        if statuses and all(item["applied"] for item in statuses):
            with _connect(target) as conn:
                stored = {row["version"]: row["checksum"] for row in conn.execute("SELECT version, checksum FROM schema_migrations")}
            mismatched = [item["version"] for item in statuses if stored.get(item["version"]) != item["checksum"]]
            if mismatched:
                raise RuntimeError(f"Migration checksum mismatch: {mismatched}")
            return []
    backup_path = target.with_suffix(target.suffix + ".pre-migrate.bak")
    if existed and backup:
        shutil.copy2(target, backup_path)
    applied_now: list[MigrationState] = []
    try:
        with _connect(target) as conn:
            _ensure_registry(conn)
            conn.commit()
            files = _files()
            if existed and files:
                row = conn.execute("SELECT 1 FROM schema_migrations WHERE version = ?", (files[0].stem,)).fetchone()
                if row is None:
                    _register_existing_baseline(conn, files[0])
                    conn.commit()
            for migration in files:
                version = migration.stem
                checksum = _checksum(migration)
                existing = conn.execute(
                    "SELECT checksum, applied_at FROM schema_migrations WHERE version = ?", (version,)
                ).fetchone()
                if existing:
                    if existing["checksum"] != checksum:
                        raise RuntimeError(f"Migration checksum mismatch: {version}")
                    continue
                sql = migration.read_text(encoding="utf-8")
                applied_at = datetime.now().isoformat(timespec="milliseconds")
                values = tuple(value.replace("'", "''") for value in (version, checksum, applied_at))
                registry_sql = (
                    "INSERT INTO schema_migrations(version, checksum, applied_at) "
                    f"VALUES ('{values[0]}', '{values[1]}', '{values[2]}');"
                )
                conn.executescript("BEGIN IMMEDIATE;\n" + sql + "\n" + registry_sql + "\nCOMMIT;")
                applied_now.append(MigrationState(version, checksum, True, applied_at))
        if backup_path.exists():
            backup_path.unlink()
        return applied_now
    except Exception:
        if existed and backup_path.exists():
            shutil.copy2(backup_path, target)
            backup_path.unlink(missing_ok=True)
        elif not existed:
            target.unlink(missing_ok=True)
        raise


def migration_status(db_path: str | Path) -> list[dict]:
    target = Path(db_path)
    applied: dict[str, sqlite3.Row] = {}
    if target.exists():
        with _connect(target) as conn:
            if "schema_migrations" in _tables(conn):
                applied = {row["version"]: row for row in conn.execute("SELECT * FROM schema_migrations")}
    result = []
    for migration in _files():
        row = applied.get(migration.stem)
        result.append(asdict(MigrationState(migration.stem, _checksum(migration), bool(row), row["applied_at"] if row else None)))
    return result


def verify_schema(db_path: str | Path) -> dict:
    target = Path(db_path)
    if not target.exists():
        raise RuntimeError(f"Database does not exist: {target}")
    statuses = migration_status(target)
    pending = [item["version"] for item in statuses if not item["applied"]]
    if pending:
        raise RuntimeError(f"Pending database migrations: {pending}")
    with _connect(target) as conn:
        tables = _tables(conn)
        missing = (BASELINE_TABLES | V13_TABLES | {"schema_migrations"}) - tables
        if missing:
            raise RuntimeError(f"Schema verification failed; missing tables: {sorted(missing)}")
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = conn.execute("PRAGMA foreign_key_check").fetchall()
    if integrity != "ok" or foreign_keys:
        raise RuntimeError(f"Database integrity failure: integrity={integrity}, foreign_keys={len(foreign_keys)}")
    return {"status": "ok", "migrations": len(statuses), "tables": len(tables)}


def auto_migrate_enabled() -> bool:
    configured = os.getenv("WORLDPULSE_AUTO_MIGRATE")
    if configured is not None:
        return configured.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("WORLDPULSE_ENV", "development").strip().lower() != "production"
