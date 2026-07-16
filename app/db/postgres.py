from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
from typing import Any, Iterator

from app.db.migrations import MIGRATIONS_DIR


POSTGRES_PREFIXES = ("postgresql://", "postgres://")


def database_url() -> str | None:
    value = os.getenv("WORLDPULSE_DATABASE_URL", "").strip()
    return value or None


def is_postgres_url(value: str | None = None) -> bool:
    return (value or database_url() or "").lower().startswith(POSTGRES_PREFIXES)


def translate_query(sql: str) -> str:
    translated = re.sub(r"\bBEGIN\s+IMMEDIATE\b", "BEGIN", sql, flags=re.IGNORECASE)
    return translated.replace("?", "%s")


def translate_migration(sql: str) -> str:
    translated = re.sub(r"\s+COLLATE\s+NOCASE\b", "", sql, flags=re.IGNORECASE)
    # SQLite INTEGER is arbitrary precision, while PostgreSQL INTEGER is 32-bit.
    # Document storage quotas default to 5 GiB and therefore require BIGINT in PostgreSQL.
    translated = re.sub(r"\bmax_document_bytes\s+INTEGER\b", "max_document_bytes BIGINT", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bREAL\b", "DOUBLE PRECISION", translated, flags=re.IGNORECASE)
    translated = re.sub(r"\bBLOB\b", "BYTEA", translated, flags=re.IGNORECASE)
    return translated


@dataclass(frozen=True)
class PostgresMigrationPlan:
    version: str
    checksum: str
    statement_count: int


def migration_plan() -> list[PostgresMigrationPlan]:
    return [
        PostgresMigrationPlan(path.stem, hashlib.sha256(path.read_bytes()).hexdigest(), len(_statements(translate_migration(path.read_text(encoding="utf-8")))))
        for path in _migration_files()
    ]


def render_postgres_schema() -> str:
    lines = [
        "-- WorldPulse PostgreSQL schema export",
        "-- Generated from the canonical numbered migrations; apply in version order.",
        "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL);",
        "",
    ]
    for path in _migration_files():
        lines.extend([f"-- {path.stem} / sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}", translate_migration(path.read_text(encoding="utf-8")).strip(), ""])
    lines.extend([
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users(LOWER(username));",
        "",
    ])
    return "\n".join(lines)


def export_postgres_schema(target: str | Path) -> Path:
    path = Path(target)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_postgres_schema(), encoding="utf-8")
    return path


class HybridRow:
    __slots__ = ("_values", "_keys", "_mapping")

    def __init__(self, values: tuple, keys: list[str]):
        self._values = values
        self._keys = keys
        self._mapping = dict(zip(keys, values))

    def __getitem__(self, key):
        return self._mapping[key] if isinstance(key, str) else self._values[key]

    def keys(self):
        return self._keys

    def __iter__(self):
        return iter(self._values)


class PostgresCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount

    def _keys(self) -> list[str]:
        return [item.name if hasattr(item, "name") else item[0] for item in (self._cursor.description or [])]

    def fetchone(self):
        row = self._cursor.fetchone()
        return HybridRow(tuple(row), self._keys()) if row is not None else None

    def fetchall(self):
        keys = self._keys()
        return [HybridRow(tuple(row), keys) for row in self._cursor.fetchall()]

    def __iter__(self) -> Iterator[HybridRow]:
        keys = self._keys()
        for row in self._cursor:
            yield HybridRow(tuple(row), keys)


class PostgresConnection:
    def __init__(self, connection):
        self._connection = connection

    def execute(self, sql: str, params: Any = None) -> PostgresCursor:
        cursor = self._connection.cursor()
        cursor.execute(translate_query(sql), params or ())
        return PostgresCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        self._connection.close()


def connect_postgres(url: str | None = None) -> PostgresConnection:
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - depends on optional runtime
        raise RuntimeError("PostgreSQL mode requires psycopg[binary]>=3.2") from exc
    return PostgresConnection(psycopg.connect(url or database_url()))


def apply_postgres_migrations(url: str | None = None) -> list[str]:
    connection = connect_postgres(url)
    applied: list[str] = []
    try:
        # Multiple API/worker processes may boot together. PostgreSQL advisory
        # locking serializes the migration ledger without introducing a service.
        connection.execute("SELECT pg_advisory_lock(112012)")
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
        connection.commit()
        for path in _migration_files():
            version = path.stem
            checksum = hashlib.sha256(path.read_bytes()).hexdigest()
            existing = connection.execute("SELECT checksum FROM schema_migrations WHERE version = ?", (version,)).fetchone()
            if existing:
                if existing["checksum"] != checksum:
                    raise RuntimeError(f"PostgreSQL migration checksum mismatch: {version}")
                continue
            try:
                for statement in _statements(translate_migration(path.read_text(encoding="utf-8"))):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, CURRENT_TIMESTAMP::TEXT)",
                    (version, checksum),
                )
                connection.commit()
                applied.append(version)
            except Exception:
                connection.rollback()
                raise
        connection.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username_lower ON users(LOWER(username))")
        connection.commit()
        return applied
    finally:
        try:
            connection.execute("SELECT pg_advisory_unlock(112012)")
            connection.commit()
        except Exception:
            pass
        connection.close()


def postgres_migration_status(url: str | None = None) -> list[dict]:
    connection = connect_postgres(url)
    try:
        connection.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)")
        connection.commit()
        rows = connection.execute("SELECT version, checksum, applied_at FROM schema_migrations").fetchall()
        stored = {row["version"]: row for row in rows}
        return [
            {
                "version": item.version, "checksum": item.checksum, "applied": item.version in stored,
                "applied_at": stored[item.version]["applied_at"] if item.version in stored else None,
            }
            for item in migration_plan()
        ]
    finally:
        connection.close()


def verify_postgres_schema(url: str | None = None) -> dict:
    statuses = postgres_migration_status(url)
    pending = [item["version"] for item in statuses if not item["applied"]]
    mismatched = [item["version"] for item in statuses if item["applied"] and item["checksum"] != next(plan.checksum for plan in migration_plan() if plan.version == item["version"])]
    if pending or mismatched:
        raise RuntimeError(f"PostgreSQL schema verification failed: pending={pending}, mismatched={mismatched}")
    connection = connect_postgres(url)
    try:
        count = connection.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = 'public'").fetchone()[0]
    finally:
        connection.close()
    return {"status": "ok", "backend": "postgresql", "migrations": len(statuses), "tables": int(count)}


def portability_report() -> dict:
    root = Path(__file__).resolve().parents[2]
    patterns = {
        "rowid": re.compile(r"\browid\b", re.IGNORECASE),
        "insert_or_ignore": re.compile(r"INSERT\s+OR\s+IGNORE", re.IGNORECASE),
        "insert_or_replace": re.compile(r"INSERT\s+OR\s+REPLACE", re.IGNORECASE),
        "collate_nocase": re.compile(r"COLLATE\s+NOCASE", re.IGNORECASE),
    }
    findings = {key: [] for key in patterns}
    for path in (root / "app" / "services").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for key, pattern in patterns.items():
            if pattern.search(text):
                findings[key].append(str(path.relative_to(root)).replace("\\", "/"))
    blockers = sum(len(items) for items in findings.values())
    return {
        "status": "ready" if blockers == 0 else "blocked", "runtime_query_adapter": "qmark-to-psycopg.v1",
        "migration_count": len(migration_plan()), "blocker_count": blockers, "findings": findings,
    }


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))


def _statements(sql: str) -> list[str]:
    return [statement.strip() for statement in sql.split(";") if statement.strip()]
