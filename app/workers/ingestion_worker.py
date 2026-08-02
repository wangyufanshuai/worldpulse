from __future__ import annotations

import argparse
from datetime import datetime, timezone
import signal
import time
from uuid import uuid4

from app.services.ingestion import claim_next_job, execute_claimed_job
from app.services import operations
from app.services.project_store import connect
from app.services.scenario_compiler import ScenarioCompilerApplicationPort, scenario_compiler_service
from app.services.continuous_intelligence import ContinuousIntelligenceService


scenario_compiler: ScenarioCompilerApplicationPort = scenario_compiler_service
continuous_intelligence = ContinuousIntelligenceService()


def process_once(worker_id: str) -> bool:
    continuous_intelligence.enqueue_due_polls()
    with connect() as conn:
        ingestion = conn.execute("SELECT created_at FROM ingestion_jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1").fetchone()
        document = conn.execute("SELECT created_at FROM document_extraction_jobs WHERE status = 'queued' ORDER BY created_at, job_id LIMIT 1").fetchone()
        poll = conn.execute("SELECT scheduled_for AS created_at FROM monitoring_poll_jobs WHERE status = 'queued' AND scheduled_for <= ? ORDER BY scheduled_for, poll_id LIMIT 1", (datetime.now(timezone.utc).isoformat(),)).fetchone()
        webhook = conn.execute("SELECT next_attempt_at AS created_at FROM webhook_deliveries WHERE status IN ('queued','retrying') AND next_attempt_at <= ? ORDER BY next_attempt_at, delivery_id LIMIT 1", (datetime.now(timezone.utc).isoformat(),)).fetchone()
    candidates = [(row["created_at"], kind) for row, kind in ((ingestion, "ingestion"), (document, "document"), (poll, "poll"), (webhook, "webhook")) if row is not None]
    first_kind = min(candidates)[1] if candidates else None
    if first_kind == "poll":
        claimed_poll = continuous_intelligence.claim_next_poll(worker_id)
        if claimed_poll is not None:
            organization_id, project_id, poll_id = claimed_poll
            operations.heartbeat_registered_worker(worker_id, status="busy", current_job_id=poll_id)
            continuous_intelligence.execute_claimed_poll(organization_id, project_id, poll_id, worker_id)
            return True
    if first_kind == "webhook":
        delivery_id = continuous_intelligence.claim_next_webhook(worker_id)
        if delivery_id is not None:
            operations.heartbeat_registered_worker(worker_id, status="busy", current_job_id=delivery_id)
            continuous_intelligence.execute_claimed_webhook(delivery_id, worker_id)
            return True
    document_first = document is not None and (ingestion is None or document["created_at"] <= ingestion["created_at"])
    if document_first:
        claimed_document = scenario_compiler.claim_next_extraction_job(worker_id)
        if claimed_document is not None:
            organization_id, project_id, job_id = claimed_document
            operations.heartbeat_registered_worker(worker_id, status="busy", current_job_id=job_id)
            scenario_compiler.execute_claimed_extraction(organization_id, project_id, job_id, worker_id)
            continuous_intelligence.finalize_extraction(job_id)
            return True
    claimed = claim_next_job(worker_id)
    if claimed is None:
        claimed_document = scenario_compiler.claim_next_extraction_job(worker_id)
        if claimed_document is None:
            return False
        organization_id, project_id, job_id = claimed_document
        operations.heartbeat_registered_worker(worker_id, status="busy", current_job_id=job_id)
        scenario_compiler.execute_claimed_extraction(organization_id, project_id, job_id, worker_id)
        continuous_intelligence.finalize_extraction(job_id)
        return True
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
            try:
                processed = process_once(args.worker_id)
            except Exception as exc:
                # Individual untrusted documents/feeds fail closed inside their
                # service and are marked failed. Keep the shared worker alive so
                # one poisoned job cannot block unrelated ingestion work.
                processed = True
                operations.heartbeat_worker(
                    args.worker_id,
                    status="ready",
                    error_code=type(exc).__name__,
                )
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
