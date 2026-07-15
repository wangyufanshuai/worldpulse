# Hybrid Replay and Audit Chain

## Purpose

WorldPulse hybrid mode lets controlled Agents propose diplomatic, alliance, narrative, sanction, and trade-routing actions without granting them authority over risk scores or supply-chain pressure. Every numeric result remains the output of the deterministic War Room engine.

## Execution chain

1. The deterministic engine creates the authoritative baseline (`war_room_result`).
2. The controlled runtime creates schema-validated `agent_action_proposals` under provider, timeout, call, and token budgets.
3. The consistency evaluator records an accept, reject, needs-revision, or not-evaluated decision for every proposal.
4. The deterministic adapter reads accepted proposals only. It maps them to the existing policy-action and bounded chain-override vocabulary.
5. The deterministic engine runs again with the adapted scenario and creates the final authoritative result.
6. The completed result is projected to the existing v1 `research_runs`, graph, report, workspace, Run Diff, and Replay Pack interfaces.

The adapter is deliberately small and versioned. Unsupported actions are retained as auditable no-ops rather than inventing a numeric effect.

## Stored artifacts

Hybrid lifecycle jobs preserve these append-only artifacts in SQLite:

- `war_room_result`: deterministic baseline.
- `agent_runtime_audit`: provider/model configuration and invocation hashes; raw prompts and raw model responses are not stored.
- `agent_action_proposals`: validated structured actions and the capability envelope.
- `consistency_audit`: deterministic findings and per-proposal admission decisions.
- `deterministic_action_modifiers`: fixed mappings, bounded scenario patch, per-modifier hashes, and bundle hash.
- `hybrid_war_room_result`: final result with `hybrid_trace` metadata.
- `hybrid_replay_record`: baseline/final/audit/modifier hashes and baseline-versus-hybrid diff.
- `projection`: the resulting v1 run identifier.

Each lifecycle artifact also has a storage SHA-256. Replay Pack verifies the stored JSON bytes against that hash before exposing the hybrid evidence chain.

## Hash scope

`baseline_result_hash` hashes the baseline `WarRoomRun`. `final_result_hash` hashes the deterministic final `WarRoomRun` before presentation-only `hybrid_trace` metadata is attached. `replay_hash` binds the baseline hash, final hash, consistency audit hash, modifier bundle hash, accepted proposal IDs, and numeric diff.

This separation avoids a self-referential final hash while making the UI trace independently inspectable.

## Offline replay

Offline replay loads the stored baseline, proposals, consistency audit, modifier bundle, and replay record. It verifies:

- the modifier bundle and each modifier hash;
- accepted proposal IDs against consistency decisions;
- proposal references;
- baseline, consistency, and modifier hashes;
- the newly computed final result hash.

It then calls only the local deterministic War Room engine. It never calls an Agent provider or an LLM. Missing or modified evidence fails replay instead of silently regenerating it.

## Compatibility

Hybrid is an additive v2 `engine_mode`. Existing deterministic, Mock Agent, and controlled Agent modes retain their behavior. The v1 War Room run, workspace, Run Diff, and Replay Pack URLs and required fields are unchanged; hybrid metadata is optional.
