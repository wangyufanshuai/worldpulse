from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.db.migrations import apply_migrations, auto_migrate_enabled, verify_schema
from app.db.postgres import apply_postgres_migrations, connect_postgres, database_url, is_postgres_url, verify_postgres_schema


DB_PATH = Path(os.getenv("WORLDPULSE_DB_PATH", "data/worldpulse.db"))
_POSTGRES_INITIALIZED_URL: str | None = None


def init_db() -> None:
    global _POSTGRES_INITIALIZED_URL
    if is_postgres_url():
        url = database_url()
        if _POSTGRES_INITIALIZED_URL == url:
            return
        if auto_migrate_enabled():
            apply_postgres_migrations()
        else:
            verify_postgres_schema()
        _POSTGRES_INITIALIZED_URL = url
        return
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    if auto_migrate_enabled():
        apply_migrations(DB_PATH)
    else:
        verify_schema(DB_PATH)


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    if is_postgres_url():
        conn = connect_postgres(database_url())
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)
