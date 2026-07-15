from __future__ import annotations

import argparse
import time
from uuid import uuid4

from app.services.run_lifecycle import process_one_queued_job
from app.services.run_lifecycle import repository


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse local run lifecycle worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued lifecycle run and exit.")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Seconds to sleep when no queued job is available.")
    args = parser.parse_args()
    worker_id = f"worker_{uuid4().hex[:12]}"

    while True:
        repository.recover_stale_jobs(recovered_by=worker_id)
        job = process_one_queued_job(worker_id=worker_id)
        if args.once:
            return 0
        if job is None:
            time.sleep(max(0.1, args.idle_sleep))


if __name__ == "__main__":
    raise SystemExit(main())
