from __future__ import annotations

import argparse
import time
from uuid import uuid4

from app.services.ingestion import claim_next_job, execute_claimed_job


def process_once(worker_id: str) -> bool:
    claimed = claim_next_job(worker_id)
    if claimed is None:
        return False
    organization_id, job_id = claimed
    execute_claimed_job(organization_id, job_id, worker_id)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse governed ingestion worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued ingestion job")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--worker-id", default=f"ingestion-worker-{uuid4().hex[:8]}")
    args = parser.parse_args()
    while True:
        processed = process_once(args.worker_id)
        if args.once:
            return 0
        if not processed:
            time.sleep(max(0.1, args.poll_seconds))


if __name__ == "__main__":
    raise SystemExit(main())
