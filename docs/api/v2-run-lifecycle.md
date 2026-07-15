# V2 Run Lifecycle API

All paths are below `/api`. V1 War Room endpoints remain supported.

## Create and inspect

`POST /v2/projects/{project_id}/runs` creates a queued job. The body accepts `engine_mode`, `scenario`, `seed`, and optional `parent_run_id`. Supported modes are `deterministic`, `mock_agent`, `controlled_agent`, and `hybrid`; unknown modes safely normalize to deterministic behavior for backward compatibility.

`GET /v2/runs/{run_id}` returns status, current phase, progress, result run ID, timestamps, worker lease metadata, and attempt count.

Status values are `queued`, `preparing`, `running`, `pausing`, `paused`, `cancelling`, `cancelled`, `failed`, and `completed`.

Phase values are `scenario_compile`, `environment_prepare`, `deterministic_run`, `consistency_audit`, `report_generate`, and `replay_archive`.

## Events

`GET /v2/runs/{run_id}/events?after_seq=N` returns events with sequence greater than `N`.

`GET /v2/runs/{run_id}/events/stream?after_seq=N` streams Server-Sent Events. `Last-Event-ID` is also honored. Event types are `WORKER`, `ENGINE`, `AGENT`, `CONSISTENCY`, and `SNAPSHOT`; idle connections receive keepalive comments.

## Controls

- `POST /v2/runs/{run_id}/pause`
- `POST /v2/runs/{run_id}/resume`
- `POST /v2/runs/{run_id}/cancel`
- `POST /v2/runs/{run_id}/retry`

Controls return the run plus recorded events. Pause/cancel are cooperative at phase boundaries. Retry is available only for failed/cancelled jobs and creates a child job with `parent_run_id`.

## Evidence

`GET /v2/runs/{run_id}/artifacts` returns artifact IDs, types, schema versions, storage hashes, timestamps, and integrity status.

`GET /v2/runs/{run_id}/audit` returns lifecycle events, integrity summary, consistency report, runtime audit, lifecycle metrics, and optional hybrid baseline/final/replay evidence. Raw provider prompts, responses, and API keys are not returned.

If a requested artifact fails SHA-256 verification, content retrieval fails closed with HTTP 409.
