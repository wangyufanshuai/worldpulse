# Changelog

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
