import sqlite3
import sys

from scripts import backup_database, verify_database


def test_database_backup_and_integrity_commands(monkeypatch, tmp_path):
    source = tmp_path / "source.db"
    target = tmp_path / "backup.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE run_artifacts (artifact_id TEXT, content_json TEXT, sha256 TEXT)")
        conn.execute("CREATE TABLE sample (value TEXT)")
        conn.execute("INSERT INTO sample VALUES ('checkpoint')")

    monkeypatch.setattr(sys, "argv", ["backup_database.py", "--source", str(source), "--output", str(target)])
    assert backup_database.main() == 0
    with sqlite3.connect(target) as conn:
        assert conn.execute("SELECT value FROM sample").fetchone()[0] == "checkpoint"

    monkeypatch.setattr(sys, "argv", ["verify_database.py", "--database", str(target)])
    assert verify_database.main() == 0
