# V4 Evidence Registry API

All v4 writes require the same Session and CSRF controls as existing APIs when `WORLDPULSE_AUTH_MODE=local`. Timestamps accept ISO-8601 and are normalized before comparison.

## Register source and snapshot

```json
POST /api/v4/evidence/sources
{
  "source_type": "public_dataset",
  "name": "Example frozen dataset",
  "locator": "https://example.invalid/dataset/version-1",
  "publisher": "Example publisher",
  "trust_tier": "external_primary",
  "metadata": {"license": "documented separately"}
}
```

```json
POST /api/v4/evidence/snapshots
{
  "source_id": "src_...",
  "project_id": "project_...",
  "external_ref": "record-2026-06",
  "title": "June frozen snapshot",
  "category": "energy",
  "content": {"value": 72.5},
  "content_text": "Energy pressure 72.5",
  "observed_at": "2026-06-01",
  "cutoff_at": "2026-06-30"
}
```

The API returns 422 when `observed_at` is later than `cutoff_at`.

## Search with a cutoff

```text
GET /api/v4/evidence/search?project_id=project_...&query=energy&cutoff_at=2026-06-30&limit=50
```

The response includes snapshots and claims that are eligible at the requested cutoff. It never fetches new external data.

## Synchronize a project

```text
POST /api/v4/projects/{project_id}/evidence/sync?run_id={run_id}
```

This idempotently registers the stored deterministic run, graph, report, findings, and citation links. Repeating the call with unchanged storage creates no new snapshot or claim.

## Freeze a pack

```json
POST /api/v4/evidence/packs
{
  "project_id": "project_...",
  "run_id": "run_...",
  "name": "Decision package 2026-06-30",
  "cutoff_at": "2026-06-30",
  "snapshot_ids": [],
  "claim_ids": []
}
```

Empty item arrays select all eligible project evidence at or before the cutoff. The returned manifest is canonicalized and SHA-256 hashed. Reading a tampered pack returns 409.
