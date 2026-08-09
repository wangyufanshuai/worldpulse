# Phase 3 Plugin SDK migration plan

This plan follows [ADR-0008](adr/0008-plugin-sdk-manifest-contract.md). It is
an incremental contract migration, not a provider marketplace and not a
permission to add data sources without governance review.

## Slice 3A — pure SDK and registry

Status: completed by local checkpoint `5d7a51a`; production dispatch remains
disabled.

Add a dependency-free contract package with closed Pydantic models, canonical
manifest hashing, permission/capability enums, input/output envelope models and
a deterministic in-memory registry. Add tests for hash mutation, duplicate
registration, unknown schema, permission escalation and provider-free
resolution. Do not touch the database or HTTP routes.

Exit evidence: registry tests, boundary verifier, Ruff/Mypy and unchanged V1
full suite.

## Slice 3B — connector and extractor adapters

Wrap three existing read-only data paths behind the connector/extractor ports:
FRED, World Bank and NOAA/NASA. The adapters keep current cache, timeout,
SSRF, cutoff and fallback behavior. Each output carries source identity,
observed/cutoff timestamps, content hash and plugin manifest/configuration hash.
No connector may write an Evidence Snapshot directly; it must use the Evidence
application port and existing organization quota gates.

Exit evidence: three contract fixtures, cache/retry/SSRF tests, evidence
lineage tests and a provider-free stored replay test.

## Slice 3C — controlled Agent Provider adapter

Expose the existing mock and allowlisted live providers through the
`agent_provider` port. The adapter preserves budgets, timeout, fallback,
action parsing, capability checks, Consistency and Action Adapter semantics.
The manifest identifies provider/model configuration without storing secrets or
raw prompts. Replay reads the stored action envelope and must prove zero
provider calls.

Exit evidence: mock implementation, disabled-provider fail-closed test, action
contract tests, tamper tests and existing hybrid/negotiation suites.

## Slice 3D — Rule Pack and Evaluator adapters

Wrap the existing active Rule Pack resolver and Evaluation application behind
`rule_pack` and `evaluator` ports. Rule Pack activation remains human-reviewed
and calibration-gated. Evaluators may observe and score Artifacts but may not
rewrite risk values, benchmark labels or blind labels. Their manifests and
configuration hashes join the existing report/replay lineage.

Exit evidence: one real active Rule Pack and one real evaluator fixture,
historical benchmark gate tests, organization-scope tests and OpenAPI hash
stability.

## Slice 3E — renderer and lineage completion

Wrap the Chinese War Room Markdown renderer as a `report_renderer` plugin while
preserving all existing routes, Chinese semantics and `data-testid` values.
Reports must display evidence, deterministic derivation, Agent observation and
uncertainty as distinct typed sections. Report and Replay Pack verification
must reject missing or mismatched plugin manifest/configuration hashes.

## Global migration rules

- Every slice lands as a separate local commit and has a rollback note.
- No production caller imports a plugin repository or private implementation.
- No plugin receives authority to write numeric world state.
- No live network call occurs during replay or retry.
- No real API keys, provider responses, benchmark labels or external source
  material are committed.
- A schema, permission, hash or lineage failure is fail-closed.
- The Phase 2 live PostgreSQL and transfer gates remain separate; their absence
  in a local environment is recorded, never replaced with fabricated evidence.

## First implementation checkpoint

The next code checkpoint is Slice 3A only. It should add contracts and tests,
not dispatch production connectors or alter runtime behavior. After 3A passes,
the implementation agent must re-run the full Phase 0/2 gate set before 3B.
