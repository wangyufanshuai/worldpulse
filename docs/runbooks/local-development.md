# Local Development Runbook

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- SQLite (provided by Python)

## Start

```powershell
cd E:\xuexi\worldpulse
python -m pip install -r requirements.txt
npm --prefix frontend install
$env:WORLDPULSE_DB_PATH="data/worldpulse.db"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8010
```

In two additional terminals:

```powershell
python -m app.workers.run_worker
npm --prefix frontend run dev
```

Use `AGENT_PROVIDER=mock` for deterministic local development. Live providers require an explicit provider allowlist value and the matching server-side API key. Never place keys in frontend variables, URLs, screenshots, logs, or Replay Packs.

## Verification

```powershell
python -m pytest -q
npm --prefix frontend run build
npm --prefix frontend run test:e2e
git diff --check
```

E2E uses a unique SQLite database and Mock Provider. Test output, database files, logs, screenshots, and browser dumps are ignored and must not be committed.

## One-job worker

`python -m app.workers.run_worker --once` claims at most one queued job and exits. This is useful for tests and manual lifecycle inspection.
