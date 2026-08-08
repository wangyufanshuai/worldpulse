from __future__ import annotations

import argparse
import os
import signal
import time
from uuid import uuid4

from app.services.run_lifecycle import RunControlApplicationPort, run_control_service
from app.services import operations
from app.services.evaluation import EvaluationApplicationPort, EvaluationService
from app.services.run_lifecycle.worker_trust import (
    WORKER_ID_ENV,
    worker_execution_capability_from_env,
)
from app.services.run_lifecycle.execution_contract import (
    expected_postgres_worker_principal,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse local run lifecycle worker")
    parser.add_argument("--worker-id", help=f"Stable worker identity (or {WORKER_ID_ENV}).")
    parser.add_argument(
        "--print-database-principal",
        action="store_true",
        help="Print the PostgreSQL login role required by the configured V2 worker and exit.",
    )
    parser.add_argument("--once", action="store_true", help="Process at most one queued lifecycle run and exit.")
    parser.add_argument("--idle-sleep", type=float, default=1.0, help="Seconds to sleep when no queued job is available.")
    args = parser.parse_args()
    configured_worker_id = (args.worker_id or os.getenv(WORKER_ID_ENV, "")).strip()
    worker_id = configured_worker_id or f"worker_{uuid4().hex[:12]}"
    execution_capability = worker_execution_capability_from_env(worker_id)
    if execution_capability is not None and not configured_worker_id:
        parser.error(
            f"V2 workers require a stable --worker-id or {WORKER_ID_ENV}"
        )
    if args.print_database_principal:
        if execution_capability is None:
            parser.error("database-principal calculation requires complete V2 worker configuration")
        print(
            expected_postgres_worker_principal(
                worker_id=execution_capability.worker_id,
                worker_generation=execution_capability.worker_generation,
            )
        )
        return 0
    lifecycle_service: RunControlApplicationPort = run_control_service
    evaluation_service: EvaluationApplicationPort = EvaluationService()
    stop_requested = False
    scheduling_turn = 0

    def request_stop(_signum=None, _frame=None):
        nonlocal stop_requested
        stop_requested = True

    operations.register_worker(
        worker_id,
        "lifecycle",
        metadata={"mode": "once" if args.once else "loop"},
        execution_capability=execution_capability,
    )
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
