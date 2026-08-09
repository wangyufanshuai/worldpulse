# ADR-0008: versioned, fail-closed Plugin SDK manifests

Status: accepted for Phase 3 contract design; no production plugin dispatch yet

## Context

WorldPulse already has several extension-shaped modules: data-source loaders,
the controlled Agent Provider runtime, database-backed Rule Packs and
Evaluation services. They currently expose useful compatibility functions, but
their version, capability, permission and configuration identity are not one
closed contract. Copying those modules into a generic registry would make
replay and organization isolation less trustworthy, and importing provider code
into the deterministic Kernel would violate the V2 authority boundary.

Phase 3 therefore needs a small SDK contract before any connector or provider
is migrated. It must be usable inside the modular monolith and must not require
a new service, queue or database table.

## Decision

Introduce a pure `app.services.plugin_sdk` contract and registry layer. A
plugin is an installed implementation descriptor, not an arbitrary import or
runtime-discovered module. Every descriptor is a closed, canonical
`plugin-manifest.v1` payload containing:

- `plugin_id`, `kind`, `version` and `implementation_id`;
- declared capabilities and permission scopes;
- input and output schema identifiers plus their versions;
- a canonical configuration hash;
- the manifest hash over the complete payload.

The initial `kind` set is `connector`, `extractor`, `agent_provider`,
`rule_pack`, `evaluator` and `report_renderer`. Unknown kinds, duplicate IDs,
unsupported schema versions, missing capabilities, permission escalation and
manifest/configuration hash mismatches fail closed before invocation.

The registry is deterministic and provider-free. It resolves only explicitly
registered descriptors and verifies the descriptor hash on every resolution.
An adapter may call a plugin only after validating the public input contract;
the adapter owns provider/network/storage details and returns a versioned,
schema-validated output envelope. Raw provider text, secrets and network
responses are never promoted to numeric authority or silently inserted into a
Replay Pack.

The SDK does not change the V1 API, database schema, Rule Pack activation
workflow or Agent runtime semantics. Existing modules remain compatibility
facades while callers migrate to public plugin ports. No plugin may write
deterministic risk, supply-chain pressure or country capability fields. Rule
Pack and Evaluator plugins remain subject to their existing human review,
calibration and fail-closed governance gates.

## Required contract gates

1. Manifest canonicalization is stable across processes and Python versions;
   changing any field changes `manifest_hash`.
2. Registry resolution is allowlisted and deterministic; no entry-point scan,
   arbitrary import path or implicit network fetch is permitted.
3. Configuration identity is pinned in the invocation envelope and in every
   produced Artifact/Report lineage record.
4. Plugin input/output schemas reject unknown or malformed fields before
   persistence or downstream projection.
5. Provider-free replay uses stored plugin output and never invokes a Provider,
   Connector or Extractor.
6. Organization and permission scope is checked by the application adapter,
   not delegated to plugin code.
7. A failed integrity, permission, schema or hash check leaves the run blocked;
   it must not fall back to another plugin version.

## Consequences

Positive:

- built-in and future external integrations share one auditable identity;
- plugin replacement can be version-pinned and rolled back independently;
- the deterministic Kernel remains free of provider and connector dependencies;
- compatibility facades allow incremental migration without API or schema churn.

Costs:

- each adapter needs explicit schema and permission declarations;
- existing loaders need mapping code while their legacy functions remain;
- plugin manifests add verification work to reports and replay paths.

## Rejected alternatives

- Python entry-point auto-discovery: it is not reproducible or sufficiently
  allowlisted for an auditable research run;
- a single `Plugin` class with untyped `dict` input/output: it hides schema and
  authority violations until after persistence;
- putting plugin registry logic in the Kernel: this couples numeric authority to
  external I/O and provider behavior;
- adding a new plugin database table in the first slice: generic Artifact and
  existing manifest lineage are sufficient until measured query pressure exists.

## Rollback

Disable plugin adapters and use the existing V1 compatibility facades. The pure
SDK contracts and descriptors are additive and require no migration rollback.
Any plugin-produced Artifact remains immutable history and is ignored by an
older worker that does not recognize the descriptor kind.
