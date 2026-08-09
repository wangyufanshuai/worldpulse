# ADR-0009: governed Research Workspace V2 Guided Flow

Status: accepted for Phase 4 bounded planning; Slice 4A code is not yet
committed

## Context

Phase 3 completed the Plugin SDK and formal Report/Replay lineage without
changing the V1-v11 HTTP/database contracts. The next V2 problem is not a new
simulation engine. It is that the current Research Workspace route still
combines ordinary research, War Room navigation, D3 rendering, lifecycle
control, evidence governance, scenario compilation, evaluation, chat and Replay
actions in one 1,238-line page.

The target user journey is already defined in the V2 program:

```text
research question
  → evidence and world model
  → scenario revision
  → bounded experiment matrix
  → stored runs and Run Diff
  → uncertainty-aware cited brief
```

The repository already has useful pieces, but it does not have a public
checkpoint-fork API, a generic arbitrary experiment-matrix DTO, a saved Diff
resource or a persisted Replay Pack resource. Treating internal Kernel
`ExperimentBranch`, lifecycle recovery checkpoints, or a projected
`clone_run` command as public capabilities would create false contracts.

External projects offer useful clean-room ideas with different licenses and
semantics:

- MiroFish's five-step Graph → Environment → Simulation → Report → Interaction
  flow is a useful page information architecture only. Its repository is
  AGPL-3.0; WorldPulse must not copy its code, prompts, provider wiring or
  OASIS/social-platform runtime.
- OpenCTI's draft workspace, review diff, approval gate, context banner and
  frozen approved revision are the primary governance reference. Community
  Edition code is Apache-2.0 while Enterprise files have separate terms;
  WorldPulse borrows concepts, not STIX/GraphQL/Elastic implementation.
- OpenBB's Widget/Dashboard/App metadata is a clean-room reference for typed
  surface descriptors and linked parameters. Its main repository is AGPL-3.0;
  the MIT `backends-for-openbb` hello-world example is not the Workspace UI.
- LEAN's `ParameterSet` and row identity are a useful clean-room reference for
  a finite experiment matrix. Concordia and OASIS provide a useful researcher-
  initiated questionnaire/interview boundary; both are Apache-2.0, but their
  implementations remain outside WorldPulse.

## Decision

### 1. Preserve route and authority boundaries

Keep `/projects/:projectId`, `/projects/:projectId/war-room/:section`, the
`/studio/` router base, existing Chinese semantics and all existing
`data-testid` values. The Guided Flow is a separate research-mode host on the
same route façade; it is not a new top-level product or a replacement War Room
route.

The deterministic engine remains the sole writer of risk, supply-chain
pressure and country capability. Guided Flow projections may display and
organize those fields but may not derive replacement values. Agent and
interview surfaces are observation-only and cannot bypass Consistency,
Action Adapter, Commitment Ledger or Projection Audit.

All new frontend network calls go through the existing `api.js` transport so
the organization header, credentials and CSRF interceptor remain in force.
All backend orchestration goes through `ResearchWorkspaceApplicationPort`,
`EvidenceApplicationPort`, Scenario Compiler and Run Control ports. No Guided
Flow code reads another bounded context's SQL tables directly.

### 2. Use a five-stage visible flow with explicit gates

The visible rail is:

1. **问题定义** — question, scope, horizon, organization and research
   template.
2. **证据与世界模型** — stored Evidence sources/claims/packs and the causal
   graph projection; extracted candidates remain draft until approved.
3. **场景与实验矩阵** — an approved Scenario Draft plus a finite, explicit
   matrix of parameter sets; no automatic optimizer in the first slice.
4. **运行与比较** — stored Run Control status, generic Run Diff, War Room
   counterfactual diff where available and provider-free Replay Pack.
5. **引证简报与追问** — Report Renderer output, typed uncertainty/evidence
   sections, citation drill-down and later an explicitly triggered interview
   artifact.

Each stage has `ready`, `blocked`, `in_progress` and `complete` projection
states. A blocked state must show the exact missing evidence, approval,
permission, lineage or run condition; it may not silently fabricate fallback
numbers.

### 3. Introduce typed surface metadata before adding new backend resources

The first implementation uses a frontend `GuidedResearchProjection` and
`GuidedSurfaceDescriptor` contract. A surface descriptor contains:

- stable `surface_id` and stage key;
- required inputs and current projection state;
- required permissions and gate verdict;
- source route/API method;
- lineage references (Run, Evidence Pack, Scenario Draft, Rule Pack,
  Renderer/Artifact hashes when present);
- explicit `unavailable_reasons` and user-facing Chinese labels.

The contract is a view model, not a second database truth. It is assembled from
the existing `ProjectDetail`, `ResearchRun`, `ResearchRunDiff`,
`ProjectAIReport`, `WarRoomWorkspaceState`, Evidence summary/search, Scenario
Draft and Evaluation read contracts.

### 4. Keep experiment identity finite and auditable

Until a separate backend ADR approves public branching, the matrix surface is
read-only or invokes the existing governed Scenario Draft Evaluation endpoint.
It must not invent `/branches`, `/experiments`, `/checkpoints` or arbitrary
matrix routes.

When the backend matrix slice is authorized, each row must carry:

```text
matrix_id
scenario_revision_id
parameter_set_hash
role = baseline | control | treated
run_id
status
comparable
non_comparable_reasons[]
metrics_projection
artifact/evidence/plugin lineage
```

Rows are capped by an explicit budget and use canonical parameter ordering.
The first release may show 2–6 user-visible rows, but the implementation must
not imply that the current fixed seven-member V10 project evaluation is an
arbitrary matrix. Control/treatment effects are always computed by the
deterministic runtime and reported as deltas with uncertainty, never as a
forecast.

### 5. Defer Agent Interview to a separate observation artifact slice

Interview is not a deterministic action and is not part of an Agent's action
space. It may only be explicitly triggered against a completed stored Run (or
an approved checkpoint contract after a future ADR). Its output is a separate
`ResearchInterviewArtifact`/Agent Observation with prompt, provider/model
configuration, invocation and content hashes, citations and uncertainty. It
cannot write WorldState, risk fields, supply-chain pressure, country capability
or Commitment Ledger entries. Replay and retry read the stored artifact and
must use zero Provider calls.

## Allowed APIs and contracts for Slice 4A

The following are real, currently implemented contracts:

- `GET /api/projects/{project_id}` → `ProjectDetail`
- `GET /api/projects/{project_id}/runs` → `list[ResearchRun]`
- `GET /api/projects/{project_id}/runs/{run_id}` → `ProjectDetail`
- `GET /api/projects/{project_id}/runs/{run_id}/citations` →
  `list[ReportCitation]`
- `GET /api/projects/{project_id}/runs/compare` → `ResearchRunDiff`
- `GET /api/projects/{project_id}/war-room/workspace` →
  `WarRoomWorkspaceState`
- `GET /api/v4/projects/{project_id}/evidence-summary` and the `/api/v4`
  Evidence source/snapshot/claim/search/pack contracts
- `/api/v8` Scenario Document/Candidate/Draft contracts
- `/api/v10` governed Evaluation contracts
- `/api/v2` Run Control status/events/audit/artifacts contracts

The existing application ports and read models are the allowed backend seams:
`ResearchWorkspaceApplicationPort`, `ResearchWorkspaceReadPort`,
`EvidenceApplicationPort`, Scenario Compiler ports and
`RunControlApplicationPort`.

The following are explicitly not allowed to be assumed:

- Project branches, checkpoint CRUD, run fork/clone, saved Diff or Replay Pack
  resources;
- arbitrary matrix request DTOs or a new public V2 non-deterministic creation
  path;
- direct SQL reads from frontend/application projection code;
- provider calls during Replay/retry;
- frontend fallback values that resemble numeric authority;
- code, prompts or provider integrations copied from MiroFish, OpenCTI,
  OpenBB, Concordia, OASIS or LEAN.

## Consequences

Positive:

- The first slice reduces the God Component without API/database churn.
- Users can see where evidence, approval, Run, uncertainty and citation
  contracts stand instead of seeing an optimistic empty state.
- Later matrix/branch/interview APIs have explicit identity and governance
  requirements before they become UI affordances.
- Existing War Room selectors, organization isolation and lifecycle semantics
  remain stable.

Costs:

- A typed view model temporarily coexists with the permissive legacy JS API.
- Some stage surfaces remain read-only until backend contracts are approved.
- The first phase needs additional projection and route-level contract tests.

## Rollback

Revert the individual Phase 4 slice commit. The route façade, V1-v11 APIs,
database schema and existing War Room components remain usable. No database
migration is authorized for Slice 4A; any future migration must have its own
ADR and checkpoint.
