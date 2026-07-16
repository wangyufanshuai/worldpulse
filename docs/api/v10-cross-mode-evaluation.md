# API Contract v10

V1.11 adds read/control endpoints under `/api/v10` for immutable evaluation suites, batches, members, metrics, append-only events and reports. Standard batches accept only `provider=mock`; live providers are observation-only and restricted to administrators. Pause, resume, cancel and retry operate at batch boundaries and never mutate completed members.

The report exposes safety gates and per-mode eligibility. It does not expose prompts, provider responses or model reasoning.
