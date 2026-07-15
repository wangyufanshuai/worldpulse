# WorldPulse V1 Threat Model

## Protected assets

- deterministic risk and supply-chain outputs;
- scenario inputs and completed run snapshots;
- Agent provider credentials;
- proposal, consistency, modifier, invocation, and replay audit chains;
- lifecycle control and worker ownership state.

## Trust boundaries

The browser is untrusted input. FastAPI validates lifecycle requests. The worker is the only lifecycle executor. Provider text is untrusted and is enclosed as untrusted world state, parsed into a strict action schema, and never receives tools. SQLite is local trusted storage but every artifact content read is hash-verified.

## Primary threats and controls

- Prompt injection or tool abuse: no Agent tools; role/action allowlists; structured output parser; untrusted-state delimiters.
- Numeric authority takeover: proposal schema recursively forbids numeric-authority keys; the consistency gate and deterministic adapter are mandatory in hybrid mode.
- Excessive cost or denial of service: provider allowlist, turn/agent/call/token/input/output budgets, timeout, bounded request lists, and bounded scenario duration.
- Secret exposure: keys remain server-side; invocation audit stores hashes and metadata only; events and errors recursively redact common credential patterns; frontend settings never return keys.
- Artifact tampering: SHA-256 at write time, verification on listing/content access, Replay Pack verification, and offline hash-chain validation.
- Worker crash or duplicate execution: atomic queued claim, worker ID, expiring lease, phase heartbeat, attempt count, safe stale-state recovery, and idempotent detection of an already committed v1 projection.
- Replay calling a model: Replay Pack and offline hybrid replay read stored evidence and call only deterministic local code.

## Residual risks

SQLite is a single-host persistence layer and is not a multi-region queue. Lease heartbeat occurs at stage boundaries, so a stage longer than the lease could be recovered prematurely; production operators should keep stages bounded or extend the lease before enabling slower providers. Local users with database write access can modify both content and hash; filesystem access control and backups remain operator responsibilities.

WorldPulse is a strategy sandbox, not a real-world prediction, policy, military, or investment decision system.
