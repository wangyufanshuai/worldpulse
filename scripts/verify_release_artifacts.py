from __future__ import annotations

from pathlib import Path
import re
import subprocess


FORBIDDEN_SUFFIXES = (".log", ".out.log", ".err.log", ".db", ".sqlite", ".db-wal", ".db-shm", ".dom.txt")
FORBIDDEN_PARTS = ("frontend/dist/", "frontend/output/", ".playwright-cli/")
SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9_-]{24,}"),
    re.compile(r"(?:DEEPSEEK|SILICONFLOW|OPENAI)_API_KEY\s*=\s*(?!your[_-]|replace[_-]|\$\{)[^\s]+", re.I),
)


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode("utf-8").split("\0")
    violations: list[str] = []
    for relative in filter(None, tracked):
        normalized = relative.replace("\\", "/")
        lower = normalized.lower()
        if lower.endswith(FORBIDDEN_SUFFIXES) or any(part in lower for part in FORBIDDEN_PARTS):
            violations.append(f"forbidden artifact: {normalized}")
            continue
        path = root / relative
        if not path.is_file() or path.stat().st_size > 2_000_000:
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if any(pattern.search(content) for pattern in SECRET_PATTERNS):
            violations.append(f"possible secret: {normalized}")
    if violations:
        print("\n".join(violations))
        return 1
    print(f"release artifact scan ok ({len([item for item in tracked if item])} tracked files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
