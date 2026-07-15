# WorldPulse V1 Hybrid Engine

## Authority boundary

WorldPulse V1 is an auditable hybrid simulation platform. The deterministic War Room engine is the only numeric authority for country risk, global risk, supply-chain pressure, timeline values, and causal weights.

Controlled Agents may propose actions in nine schema-defined categories. They cannot write numeric-authority fields, call tools, alter storage, or bypass the consistency evaluator. Accepted proposals enter a versioned deterministic adapter; rejected, needs-revision, and not-evaluated proposals remain audit records only.

## Runtime flow

```text
Scenario
  -> deterministic baseline
  -> controlled Agent proposals
  -> consistency admission decisions
  -> bounded deterministic modifiers
  -> deterministic final result
  -> v1 workspace / Run Diff / Replay Pack
```

Lifecycle state, events, artifacts, worker leases, and hashes are stored in SQLite. The API remains FastAPI, the UI remains Vue, and a separate local Python worker executes queued jobs.

## Modes

- `deterministic`: one authoritative deterministic run plus read-only result audit.
- `mock_agent`: repeatable proposals and admission decisions; no proposal is applied to numeric results.
- `controlled_agent`: allowlisted provider runtime with budgets and safe Mock fallback; no proposal is applied.
- `hybrid`: controlled runtime, consistency admission, deterministic adaptation, deterministic rerun, and offline replay evidence.

Live provider use is opt-in. An absent or unsupported provider configuration falls back to deterministic Mock behavior unless fallback is explicitly set to `skip`.

## Compatibility

The v1 synchronous War Room API remains unchanged. V2 lifecycle fields added for ownership, leases, attempts, integrity, metrics, and hybrid evidence are optional/additive. Replay Pack and Run Diff continue to operate on completed `research_runs` and never require a new model call.

## Failure semantics

Pause and cancellation take effect at phase boundaries. Incomplete jobs are never projected to `research_runs`. A worker renews its lease at each stage; another worker can requeue an expired preparing/running job, pause an expired pausing job, or finalize an expired cancelling job. Completed runs are immutable from lifecycle controls.

See [Agent Action Contract](agent-action-contract.md), [Consistency Evaluator](consistency-evaluator.md), [Agent Runtime](agent-runtime.md), and [Replay and Audit](replay-and-audit.md).
