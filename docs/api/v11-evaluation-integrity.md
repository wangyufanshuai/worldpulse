# API Contract v11

V1.12 adds immutable historical benchmark suites, sealed blind label packs, historical release batches and per-member verification results under `/api/v11`.

Blind labels are never returned by an online API. Label packs must be AES-256-GCM encrypted, Ed25519 signed, approved by two different users (one reviewer and one administrator), and are consumed by a single release root batch. Historical quality metrics are observation-only in V1.12; safety, Artifact integrity, offline Replay and organization scope remain hard fail-closed gates.

The existing v10 Batch, Member, Event, SSE and control endpoints remain compatible and now enforce request-organization scope.
