# WorldPulse API Contract v9

V9 adds governed public-feed monitoring, deterministic watchlists, alert lineage, in-app notifications and signed webhook subscriptions. All v1-v8 contracts remain compatible.

## Project-scoped routes

- `GET/POST /api/v9/organizations/{organization_id}/projects/{project_id}/monitoring/sources`
- `GET .../sources/{source_id}` plus `poll`, `status` and `clone`
- `GET .../monitoring/polls` and `GET .../polls/{poll_id}` / `events`
- `GET/POST .../watchlists` plus `activate`, `pause` and `clone`
- `GET .../alerts`, `GET .../alerts/{alert_id}` / `events`
- `POST .../alerts/{alert_id}/acknowledge` and `dismiss`
- `GET .../monitoring/summary`

## Organization-scoped notification routes

- `GET /api/v9/notifications?after_seq=0&unread_only=false`
- `GET /api/v9/notifications/stream?after_seq=0`
- `POST /api/v9/notifications/{notification_id}/read`
- `POST /api/v9/notifications/read-all`
- `GET/POST /api/v9/notification-subscriptions`
- `POST /api/v9/notification-subscriptions/{subscription_id}/pause`
- `POST /api/v9/notification-subscriptions/{subscription_id}/test`

Unsafe URL, invalid feed or unknown canonical values return `422`; immutable state/hash conflicts return `409`; rate or quota limits return `429`; scope and role violations return `403`. Asynchronous poll failures are represented in Poll Job events without exposing raw response bodies.

Webhook bodies never include full source text, prompts or provider responses. Delivery headers include delivery ID, event type, timestamp and an HMAC-SHA256 signature so consumers can verify authenticity and deduplicate by delivery ID.
