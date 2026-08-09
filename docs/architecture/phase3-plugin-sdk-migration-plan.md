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

Status: completed by local checkpoint `cc1f7b9`; production world-data routing
remains on the V1 compatibility path.

Wrap three existing read-only data paths behind the connector/extractor ports:
FRED, World Bank and NOAA/NASA. The adapters keep current cache, timeout,
SSRF, cutoff and fallback behavior. Each output carries source identity,
observed/cutoff timestamps, content hash and plugin manifest/configuration hash.
No connector may write an Evidence Snapshot directly; it must use the Evidence
application port and existing organization quota gates.

Exit evidence: three contract fixtures, cache/retry/SSRF tests, evidence
lineage tests and a provider-free stored replay test.

## Slice 3C — controlled Agent Provider adapter

Status: completed by local checkpoint `a28145a`; production lifecycle routing
continues to call the V1-compatible Agent Runtime façade.

Expose the existing mock and allowlisted live providers through the
`agent_provider` port. The adapter preserves budgets, timeout, fallback,
action parsing, capability checks, Consistency and Action Adapter semantics.
The manifest identifies provider/model configuration without storing secrets or
raw prompts. Replay reads the stored action envelope and must prove zero
provider calls.

Exit evidence: mock implementation, disabled-provider fail-closed test, action
contract tests, tamper tests and existing hybrid/negotiation suites.

## Slice 3D — Rule Pack and Evaluator adapters

Status: completed by local checkpoint `1f253ad`; production activation,
evaluation scheduling and benchmark curation remain on existing governed paths.

Wrap the existing active Rule Pack resolver and Evaluation application behind
`rule_pack` and `evaluator` ports. Rule Pack activation remains human-reviewed
and calibration-gated. Evaluators may observe and score Artifacts but may not
rewrite risk values, benchmark labels or blind labels. Their manifests and
configuration hashes join the existing report/replay lineage.

Exit evidence: one real active Rule Pack and one real evaluator fixture,
historical benchmark gate tests, organization-scope tests and OpenAPI hash
stability.

## Slice 3E — renderer and lineage completion

Status: completed by local checkpoint `4f27bea`; Renderer execution remains a
built-in application adapter and does not authorize dynamic third-party plugin
loading.

Wrap the Chinese War Room Markdown renderer as a `report_renderer` plugin while
preserving all existing routes, Chinese semantics and `data-testid` values.
Reports must display evidence, deterministic derivation, Agent observation and
uncertainty as distinct typed sections. Report and Replay Pack verification
must reject missing or mismatched plugin manifest/configuration hashes.

The installed `report_renderer.markdown` adapter injects the existing Project
and War Room Replay renderers behind one closed request/output envelope. It
records manifest, configuration, input, invocation, output and content hashes
with `provider_calls = 0`. New Project and War Room reports persist identical
Renderer lineage in both a typed citation and the owning Run snapshot. Report
reads join the Run lineage and fail closed on downgrade, duplicate, malformed,
mismatched or content-tampered lineage; reports created before Slice 3E remain
readable only when both the report and Run lack Renderer lineage.

Replay Pack rendering uses the same adapter from stored state. The renderer
receives the pre-lineage manifest, then its output lineage is added and the
final Replay manifest hash is computed, avoiding a circular digest. Stored
verification authenticates the final manifest, installed Renderer identity,
Markdown content and output payload without executing a Renderer or Provider.

Rollback: revert `4f27bea`. Slice 3E adds no migration, route or public model;
the V1-compatible render functions remain intact, so rollback restores direct
rendering without rewriting stored reports or runs.

Exit evidence: Renderer byte-compatibility and Chinese-semantics tests,
Report/Run lineage and database tamper tests, Replay manifest/Markdown/provider
tamper tests, Plugin SDK Ruff/Mypy/contract ratchet, boundary verification and
the complete backend/frontend/E2E/security/release gates.

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

Slice 3A was the pure contract checkpoint `5d7a51a`; Slice 3B is the first
real built-in implementation checkpoint `cc1f7b9`; Slice 3C wraps the existing
controlled Agent Runtime in `a28145a`; Slice 3D adds governed Rule Pack and
Evaluator adapters in `1f253ad`; Slice 3E binds the existing report and Replay
renderers into formal lineage in `4f27bea`. Phase 3 is complete. The next
authorized program phase is Phase 4 Research Workspace V2; production
world-data and Agent lifecycle routing remain unchanged until their plugin
lineage is adopted by explicit application ports and replay/organization gates.
