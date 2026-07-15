# Changelog

## 1.1.0-dev - Unreleased

- Added versioned six-stage lifecycle step contracts and verified checkpoint recovery.
- Added attempt lineage, idempotent run creation, exponential retry/backoff, terminal reasons, atomic SQLite event sequencing, and artifact lineage.
- Added fault-injection, security corpus, Vitest composable coverage, Chromium E2E map/lifecycle coverage, and 10 Golden Scenario fixtures.
- Added lifecycle health summary, phase P50/P95, stale/recovery and integrity metrics, plus step/attempt/artifact UI audit tables.
- V1.1 remains an internal trial: deterministic War Room values are authoritative; Agent/LLM actions remain bounded proposals and Replay remains offline.

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
