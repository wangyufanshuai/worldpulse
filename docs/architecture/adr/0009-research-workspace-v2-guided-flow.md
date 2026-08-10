# ADR-0009: governed Research Workspace V2 Guided Flow

Status: accepted; Slice 4A completed by local checkpoint
`98811eff4f2d113cbfba9a35226583dd4e0620e8`; Slice 4B completed by local
checkpoint `ad691ab7e0c529a77fac24278eed0e2b5add7d44`; Slice 4C completed by
local checkpoint `c1740422b13bcf70efec358f615b6d697c019916`; Phase 4 remains active

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

Guided write/review visibility uses the same two-layer authorization as the
HTTP middleware: the global account permission and current organization
membership role must both allow the action. Organization context not yet loaded
is denied. This is only a presentation projection; backend global permission,
organization role, resource scope and CSRF checks remain authoritative.

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

The Slice 4C read model carries only stored or explicitly unavailable fields:

```text
matrix_id
scenario_revision_id
parameter_set_hash
role = unavailable (V10 does not store role)
run_id
status
comparable
non_comparable_reasons[]
metrics_projection
artifact/evidence/plugin lineage
```

Rows use canonical parameter ordering and are capped at six visible entries,
while all seven fixed V10 members remain mandatory for batch comparability.
The stored `input_hash` is the parameter-set identity; identical canonical
maps for seeds `11`, `29` and `47` must share it. Every row is non-comparable
unless the whole batch is completed, safety passed, `7/7` complete, zero
failed, report-bound and fully verified with required lineage. The surface does
not imply that V10 is an arbitrary matrix and does not infer role,
control/treatment effects, uncertainty or plugin lineage.

Successfully loaded data is also bound to the complete organization, project,
approved Draft, Pack and manifest context. Context drift invalidates the
snapshot before rendering. Queued/running batches use one terminal-aware
polling timer and same-context callers share one in-flight request; terminal
state, error, context change and disposal stop further refresh or stale commit.

### 5. Defer Agent Interview to a separate observation artifact slice

Interview is not a deterministic action and is not part of an Agent's action
space. It may only be explicitly triggered against a completed stored Run (or
an approved checkpoint contract after a future ADR). Its output is a separate
`ResearchInterviewArtifact`/Agent Observation with prompt, provider/model
configuration, invocation and content hashes, citations and uncertainty. It
cannot write WorldState, risk fields, supply-chain pressure, country capability
or Commitment Ledger entries. Replay and retry read the stored artifact and
must use zero Provider calls.

## Allowed APIs and contracts for Slices 4A-4C

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
- Slice 4C exposes the governed finite Evaluation matrix without a new route,
  mutation, migration, Provider call or numeric authority.

Costs:

- A typed view model temporarily coexists with the permissive legacy JS API.
- Some stage surfaces remain read-only until backend contracts are approved.
- The first phase needs additional projection and route-level contract tests.

Slice 4C verification recorded on 2026-08-10: frontend unit `143 passed`,
Playwright `14 passed`, backend `703 passed, 5 skipped`, Pilot/Benchmark
contracts `26 passed`, boundary verification reported zero legacy/forbidden
imports and the release scan passed. The five skips remain explicit external
PostgreSQL and real 120-case Benchmark gates. Phase 4D and any
`v2.0.0-rc1` discussion remain blocked until the real reviewer workflow closes.

## Rollback

Revert the individual Phase 4 slice commit. The route façade, V1-v11 APIs,
database schema and existing War Room components remain usable. No database
migration is authorized for Slice 4A; any future migration must have its own
ADR and checkpoint.
