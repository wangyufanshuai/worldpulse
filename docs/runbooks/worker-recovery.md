# Worker Recovery Runbook

## Automatic recovery

Each worker has a generated ID. Claiming a job writes ownership, lease expiry, and increments `attempt_count`. The executor renews its lease at phase boundaries. Every worker startup scans for expired leases:

- expired `preparing`/`running` -> `queued`;
- expired `pausing` -> `paused`;
- expired `cancelling` -> `cancelled`.

Recovery appends a `Stale worker lease recovered` event. A requeued job may repeat deterministic stages and append replacement artifacts, but only a successfully completed execution is projected to `research_runs`.

If a worker dies after the v1 projection was committed but before the job status was finalized, the replacement worker discovers the existing `lifecycle_job_id` projection and marks the job completed without inserting a duplicate research run.

## Operator steps

1. Check `GET /api/v2/runs/{run_id}` for status, `worker_id`, `lease_expires_at`, and `attempt_count`.
2. Check the event stream for lease recovery or failure events.
3. Start one worker with `python -m app.workers.run_worker --once` or the continuous worker command.
4. Verify the run reaches `completed` and has a `lifecycle_metrics` artifact.
5. Verify `GET /api/v2/runs/{run_id}/audit` reports integrity `verified`.

Do not manually mark an incomplete job completed or insert a projection artifact. If integrity fails, preserve the database for investigation and retry from a known scenario rather than editing hashes.
