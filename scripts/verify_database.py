from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify SQLite and lifecycle artifact integrity without modifying storage.")
    parser.add_argument("--database", default="data/worldpulse.db")
    args = parser.parse_args()
    database = Path(args.database).resolve()
    if not database.exists():
        parser.error(f"database does not exist: {database}")
    invalid = []
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "run_artifacts" in tables:
            for row in conn.execute("SELECT artifact_id, content_json, sha256 FROM run_artifacts"):
                digest = hashlib.sha256(row["content_json"].encode("utf-8")).hexdigest()
                if digest != row["sha256"]:
                    invalid.append(row["artifact_id"])
    print(f"sqlite={integrity} artifacts_invalid={len(invalid)}")
    return 0 if integrity == "ok" and not invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
