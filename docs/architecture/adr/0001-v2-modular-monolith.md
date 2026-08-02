# ADR-0001: V2.0 modular monolith before distributed services

Status: accepted for Phase 0

## Context

WorldPulse already contains eight strong domain areas, 83 tables, more than
200 HTTP operations and two worker classes. The current risk is boundary
coupling and moving dependency versions, not proven service-scale throughput.
Splitting now would multiply deployment, consistency, security and replay
failure modes before load evidence exists.

## Decision

V2.0 remains a modular monolith with explicit bounded contexts, public
application ports, repository/adapters, versioned events and compatibility
façades. PostgreSQL remains the production persistence boundary and existing
workers remain the execution boundary.

The runtime may later adopt a distributed queue, Ray, Temporal, Redis or
independent services only after a measured bottleneck, an ADR, a migration
plan, and replay/organization-isolation proof.

## Consequences

Positive:

- V1-v11 API and database compatibility is easier to preserve.
- Existing deterministic runs, evidence lineage and replay remain in one
  transactionally inspectable system.
- Refactors can land as small, reversible checkpoints.
- Local development remains zero-configuration with SQLite.

Costs:

- Context boundaries need automated import and contract checks.
- Some duplicate mapping code will exist during the strangler migration.
- Large-scale execution is deferred until measured evidence justifies it.

## Rejected alternatives

- Immediate microservices: no concurrency or latency evidence justifies the
  operational cost.
- Direct MiroFish/OASIS code import: licenses and numeric-governance boundaries
  are incompatible with an unreviewed copy-and-adapt approach.
- A second evaluation or simulation engine: production-path reuse is required
  for trustworthy results.
