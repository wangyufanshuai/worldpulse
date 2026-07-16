from __future__ import annotations

import argparse
import signal
import time
from uuid import uuid4

from app.services.ingestion import claim_next_job, execute_claimed_job
from app.services import operations


def process_once(worker_id: str) -> bool:
    claimed = claim_next_job(worker_id)
    if claimed is None:
        return False
    organization_id, job_id = claimed
    operations.heartbeat_registered_worker(worker_id, status="busy", current_job_id=job_id)
    execute_claimed_job(organization_id, job_id, worker_id)
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse governed ingestion worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued ingestion job")
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    parser.add_argument("--worker-id", default=f"ingestion-worker-{uuid4().hex[:8]}")
    args = parser.parse_args()
    stop_requested = False

    def request_stop(_signum=None, _frame=None):
        nonlocal stop_requested
        stop_requested = True

    operations.register_worker(args.worker_id, "ingestion", metadata={"mode": "once" if args.once else "loop"})
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    try:
        while True:
            if stop_requested and not operations.worker_should_drain(args.worker_id):
                operations.request_worker_drain(args.worker_id)
            if operations.worker_should_drain(args.worker_id):
                operations.stop_worker(args.worker_id)
                return 0
            operations.heartbeat_worker(args.worker_id, status="ready")
            processed = process_once(args.worker_id)
            if stop_requested and not operations.worker_should_drain(args.worker_id):
                operations.request_worker_drain(args.worker_id)
            if operations.worker_should_drain(args.worker_id):
                operations.stop_worker(args.worker_id)
                return 0
            operations.heartbeat_worker(
                args.worker_id,
                status="ready",
                completed_increment=1 if processed else 0,
            )
            if args.once:
                operations.stop_worker(args.worker_id)
                return 0
            if not processed:
                time.sleep(max(0.1, args.poll_seconds))
    except Exception as exc:
        operations.stop_worker(args.worker_id, failed=True, error_code=type(exc).__name__)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
