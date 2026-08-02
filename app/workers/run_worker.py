from __future__ import annotations

import argparse
import signal
import time
from uuid import uuid4

from app.services.run_lifecycle import RunControlApplicationPort, run_control_service
from app.services import operations
from app.services.evaluation import EvaluationApplicationPort, EvaluationService


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse local run lifecycle worker")
    parser.add_argument("--once", action="store_true", help="Process at most one queued lifecycle run and exit.")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Seconds to sleep when no queued job is available.")
    args = parser.parse_args()
    worker_id = f"worker_{uuid4().hex[:12]}"
    lifecycle_service: RunControlApplicationPort = run_control_service
    evaluation_service: EvaluationApplicationPort = EvaluationService()
    stop_requested = False
    scheduling_turn = 0

    def request_stop(_signum=None, _frame=None):
        nonlocal stop_requested
        stop_requested = True

    operations.register_worker(worker_id, "lifecycle", metadata={"mode": "once" if args.once else "loop"})
    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    try:
        while True:
            if stop_requested and not operations.worker_should_drain(worker_id):
                operations.request_worker_drain(worker_id)
            if operations.worker_should_drain(worker_id):
                operations.stop_worker(worker_id)
                return 0
            operations.heartbeat_worker(worker_id, status="ready")
            lifecycle_service.recover_stale_jobs(recovered_by=worker_id)
            evaluation_service.reconcile(worker_id=worker_id)
            # Three ordinary project runs receive priority for every evaluation
            # run. Either class may still proceed when the preferred queue is empty.
            prefer_evaluation = scheduling_turn % 4 == 3
            job = lifecycle_service.process_one_queued_job(worker_id=worker_id, prefer_evaluation=prefer_evaluation)
            scheduling_turn = (scheduling_turn + 1) % 4
            evaluation_service.reconcile(worker_id=worker_id)
            if stop_requested and not operations.worker_should_drain(worker_id):
                operations.request_worker_drain(worker_id)
            if operations.worker_should_drain(worker_id):
                operations.stop_worker(worker_id)
                return 0
            operations.heartbeat_worker(
                worker_id,
                status="ready",
                completed_increment=1 if job is not None and job.status == "completed" else 0,
            )
            if args.once:
                operations.stop_worker(worker_id)
                return 0
            if job is None:
                time.sleep(max(0.1, args.idle_sleep))
    except Exception as exc:
        operations.stop_worker(worker_id, failed=True, error_code=type(exc).__name__)
        raise


if __name__ == "__main__":
    raise SystemExit(main())
