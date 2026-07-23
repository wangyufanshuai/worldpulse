# V1.12 工作波次（未激活）

This directory is reserved for `pilot` and `wave` source plans, acquisition
locks, preflight reports and partial manifests. Nothing under this directory
is an active Benchmark Suite.

The repository intentionally does not generate historical labels or invent
official evidence. A curator may place a reviewed `source-plan.json` here after
confirming publisher, license, hashed rights review, cutoff, input/outcome separation, locator
coverage and the fixed WorldPulse scenario contract.

The tracked `pilot-curation-dossier.json` and `pilot-review.pilot.json` are
intentionally drafts: all rights decisions, labels and label confidence values
are empty. The reviewer fills the offline Worksheet, runs
`validate-pilot-review`, then authenticates as the exact local
`benchmark-reviewer` account with `apply-pilot-review`. `finalize-pilot` only
accepts the resulting reviewed Dossier. Source acquisition is not authorized
before that finalization succeeds.

Before any release import:

```text
python -m app.manage benchmark source-status --file acquisition-lock.json
python -m app.manage benchmark preflight --file manifest.json --profile pilot
```

Only a complete `release` profile can be imported into the database. Raw
materials belong in the content-addressed `data/benchmarks/sha256/` store and
must not be committed.
