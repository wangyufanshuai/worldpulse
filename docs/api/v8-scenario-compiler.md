# WorldPulse API Contract v8

V8 adds organization/project-scoped source document import, extraction lifecycle, candidate decisions, Scenario Draft governance and approved-Draft run creation. All v1-v7 URLs and field meanings remain unchanged.

## Routes

- `POST/GET /api/v8/organizations/{organization_id}/projects/{project_id}/documents`
- `GET /api/v8/organizations/{organization_id}/projects/{project_id}/documents/{document_id}`
- `GET /api/v8/organizations/{organization_id}/projects/{project_id}/documents/{document_id}/download`
- `POST /api/v8/organizations/{organization_id}/projects/{project_id}/documents/{document_id}/extract`
- `GET /api/v8/organizations/{organization_id}/projects/{project_id}/extraction-jobs`
- `GET /api/v8/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}`
- `GET /api/v8/organizations/{organization_id}/projects/{project_id}/extraction-jobs/{job_id}/events?after_seq=0`
- `POST .../cancel` and `POST .../retry`
- `GET/POST .../scenario-candidates` and `.../{candidate_id}/decision`
- `GET/POST .../scenario-drafts`, `.../{draft_id}`, `.../submit`, `.../review`, `.../clone`, `.../runs`

Write errors are fail-closed: `413` for size, `415` for unsupported media/signature, `403` for role or self-review, `409` for hash/status/blob conflicts and `422` for invalid cutoff, candidates or compiler mappings.
