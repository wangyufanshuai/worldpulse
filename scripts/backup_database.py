from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import sqlite3


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a consistent online backup of the WorldPulse SQLite database.")
    parser.add_argument("--source", default="data/worldpulse.db")
    parser.add_argument("--output", default=None)
    args = parser.parse_args()
    source = Path(args.source).resolve()
    if not source.exists():
        parser.error(f"database does not exist: {source}")
    target = Path(args.output).resolve() if args.output else source.with_name(f"{source.stem}-{datetime.now():%Y%m%d-%H%M%S}.backup.db")
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source) as src, sqlite3.connect(target) as dst:
        src.backup(dst)
    print(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
