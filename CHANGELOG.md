# Changelog

## 1.7.0-rc1 - 2026-07-16

- Added a persisted worker registry for lifecycle and ingestion processes with leases, heartbeat freshness, current-job visibility, completion counters, graceful signal handling, and administrator-triggered draining.
- Added `/api/ready` and v6 platform readiness contracts that distinguish process liveness from database/schema, active Rule Pack, queue, and optional worker-capacity readiness.
- Added organization quotas for projects, active lifecycle runs, rolling 24-hour ingestion jobs, and evidence snapshots; enforcement lives in service creation paths and preserves idempotent retries.
- Added append-only organization quota change events and v6 organization operations APIs without changing v1-v5 contracts or deterministic result semantics.
- Added the Chinese War Room Operations Center for readiness, worker state, safe drain controls, organization usage, and administrator-only quota editing.
- Expanded gates to 174 backend tests plus 3 standard PostgreSQL skips, 50 Vitest tests, and 10 Playwright flows, with 3 additional live PostgreSQL gates.

## 1.6.0-rc1 - 2026-07-16

- Promoted PostgreSQL from a translation-only readiness target to a live-tested runtime with canonical migrations, deterministic worker completion, legacy workspace/Replay Pack projection, and row-lock concurrency gates.
- Added PostgreSQL-safe `SKIP LOCKED` job claiming and atomic event sequence allocation for both lifecycle and ingestion workers while preserving SQLite transaction semantics.
- Added `python -m app.manage db-copy` for foreign-key-ordered SQLite-to-PostgreSQL transfer with per-table row counts and order-independent SHA-256 verification.
- Added a PostgreSQL Compose overlay with API, lifecycle worker, ingestion worker, health checks, and persistent storage; the default Compose path remains SQLite-compatible.
- Added a persistent organization selector, organization header propagation, SSE organization context, stale-selection recovery, and backend-enforced V4 evidence source/snapshot/claim/pack isolation.
- Added live PostgreSQL CI gates and organization isolation regression coverage without changing the v1-v5 response contracts or deterministic risk authority.

## 1.5.0-rc1 - 2026-07-16

- Added organization membership and backend-enforced project/lifecycle resource scopes while preserving existing v1-v4 response contracts.
- Added v5 organization project, membership, immutable ingestion policy, versioned manual connector, ingestion job, event, retry, and summary APIs.
- Added fail-closed ingestion validation for license metadata, secret-like connector configuration, payload size, category allowlists, duplicate references, and future-data leakage.
- Connected accepted ingestion records to immutable V1.4 evidence sources/snapshots with connector, policy, record, manifest, and parent-retry hashes.
- Added an independent ingestion worker plus bounded API execution, idempotency, cancellation-before-write, retry lineage, and monotonic audit events.
- Added PostgreSQL connection/query adapters, canonical migration translation, schema verification/export, and a zero-blocker portability gate; SQLite remains the default backend.
- Added the Chinese War Room Ingestion Center and expanded release gates to 166 backend tests, 44 Vitest tests, and 9 Playwright flows.
- V1.5 supports `manual_json` only; scheduled network connectors, distributed workers, OIDC, and hard multi-tenant deployment are intentionally deferred.

## 1.4.0-rc1 - 2026-07-16

- Added an immutable Evidence Registry for sources, frozen snapshots, provenance claims, citation links, and hash-addressed evidence packs.
- Added cutoff-aware evidence search and fail-closed checks that reject future observations and surface content tampering.
- Added v4 Evidence APIs for source/snapshot/claim registration, project and calibration synchronization, evidence search, packs, and project summaries.
- Connected project report citations, deterministic runs, causal graphs, Trust Summary, and Replay Pack manifests to one evidence lineage without rerunning an LLM.
- Added the War Room Evidence Center with source health, snapshot hashes, claim coverage, cutoff search, project synchronization, and pack freezing.
- Expanded release gates to 154 backend tests, 33 Vitest tests, and 8 Playwright flows while preserving all v1/v2/v3 contracts and deterministic Golden Scenarios.
- External evidence acquisition remains explicit and source-governed; V1.4 does not silently browse, overwrite snapshots, or treat model-generated prose as ground truth.

## 1.3.0-rc1 - 2026-07-15

- Added checksum-verified numbered SQLite migrations, baseline import, backup/restore, and migration CLI verification.
- Added Argon2id local accounts, opaque server-side sessions, CSRF, CORS allowlists, rate limits, security audit events, and four-role RBAC.
- Added immutable Rule Pack manifests, two-person approval, calibration-gated candidate activation, and per-run Rule Pack pinning.
- Added a four-stage calibration lifecycle with 30 frozen V1.2 benchmark cases, deterministic metrics, checkpoint artifacts, tamper detection, and fail-closed promotion gates.
- Added append-only Review Cases/Decisions for action admission, calibration failure, Rule Pack promotion, artifact integrity, material Run Diff, and evidence coverage.
- Added the War Room Trust Center, overview trust summary, login/session UI, role-aware controls, and report/Replay trust manifests.
- Expanded release gates to 148 backend tests, 26 Vitest tests, 7 Playwright flows, migration/OpenAPI verification, dependency audit, artifact scan, and Docker Compose smoke test.
- The bundled calibration corpus is an internal frozen regression corpus, not independent real-world ground truth; external evidence ingestion remains a future milestone.

## 1.1.0-dev - Unreleased

- Added versioned six-stage lifecycle step contracts and verified checkpoint recovery.
- Added attempt lineage, idempotent run creation, exponential retry/backoff, terminal reasons, atomic SQLite event sequencing, and artifact lineage.
- Added fault-injection, security corpus, Vitest composable coverage, Chromium E2E map/lifecycle coverage, and 10 Golden Scenario fixtures.
- Added lifecycle health summary, phase P50/P95, stale/recovery and integrity metrics, plus step/attempt/artifact UI audit tables.
- V1.1 remains an internal trial: deterministic War Room values are authoritative; Agent/LLM actions remain bounded proposals and Replay remains offline.

## 1.2.0-dev - Unreleased

- Added versioned per-action governance audit fields for input hash, rule version, canonical outcome, rejection reason, and projection status.
- Added `agent-action-projection-audit.v1` artifacts for hybrid and audit-only runs, with checkpoint, replay, and Replay Pack integrity verification.
- Added constrained/expired action coverage and War Room visibility for pass rate, rule hits, and final projection status.
- Preserved legacy decision fields and all v1/v2 API contracts; deterministic War Room remains the sole numeric authority.

## 1.0.0 - 2026-07-15

- Preserved the deterministic War Room engine as the sole numeric authority.
- Added SQLite-backed v2 Run Lifecycle, SSE events, pause/resume/cancel/retry, separate worker, checkpoints, artifacts, and v1 result projection.
- Added read-only consistency evaluation and per-proposal admission decisions.
- Added strict Agent Action Contract, deterministic Mock Agent, controlled provider runtime, budgets, timeouts, fallback, and invocation audit.
- Added hybrid deterministic adaptation, bounded modifiers, baseline/final diff, hash chain, and offline replay without LLM calls.
- Added worker leases, stale-job recovery, artifact integrity verification, phase metrics, secret redaction, and bounded runtime configuration.
- Added lifecycle command UI, real event stream, Agent negotiation audit, baseline/final toggle, artifact/model-invocation data center, and runtime settings summary.
- Added architecture, API, recovery, local development, replay, and threat-model documentation.

## 0.7.0

- Established the behavior-preserving War Room, Run Diff, Replay Pack, Chinese command console, and modular project service baseline.
