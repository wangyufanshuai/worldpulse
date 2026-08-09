# Phase 4 Research Workspace V2 migration plan

Status: planning checkpoint; no Phase 4 production code is authorized by this
document alone

This plan follows [ADR-0009](adr/0009-research-workspace-v2-guided-flow.md).
It is a progressive extraction and projection program, not a frontend rewrite,
new microservice boundary or permission to invent checkpoint/branch APIs.

## Phase 0 — documentation discovery and allowed seams

Completed for planning on 2026-08-09.

### Local sources and findings

- `frontend/src/views/research-workspace/ResearchWorkspacePage.vue:1-1238`
  is the current God Component: 18 War Room imports, 14 composable imports,
  23 refs, 33 computeds and 6 watchers. It renders both War Room and ordinary
  research branches.
- `frontend/src/views/ResearchWorkspaceView.vue:1-9` and
  `frontend/src/main.js:8-14` are the route façade. Preserve both existing
  routes and `/studio/` history base.
- `frontend/src/composables/useWorkspaceShell.js:8-68` is the section metadata
  and path pattern. `useScenarioCompiler.js:23-57` is the preferred scoped,
  parallel-read and quiet-reload pattern. `useRunLifecycle.js:41-107` is the
  preferred SSE/polling/cleanup pattern.
- `frontend/src/components/war-room/WarRoomOverviewConsole.vue:56-96` and
  `WarRoomLifecycleMap.vue:112-138` are the preferred explicit props/emits
  presentational boundaries. Existing War Room selectors must not be renamed.
- `frontend/src/api.js:3-31` owns organization header, credentials and CSRF;
  all new frontend API wrappers must use it.
- `app/services/project_app/ports.py:28-141`, `read_models.py:19-52`,
  `project_queries.py:17-57` and `run_queries.py:10-22` define the stable
  Research Workspace application/read seam.
- `app/api/routes.py:104-249` exposes the real Project, Run, Diff, Replay,
  Graph, Report and Chat routes. `app/api/v4.py:34-102`, `v8.py:94-126` and
  `v10.py:19-60` expose Evidence, Scenario Compiler and governed Evaluation
  contracts.
- `app/services/project_app/workspace.py:15-93` provides read-only Workspace
  projections including `compare_ready` and `replay_ready`.
- `app/services/run_lifecycle/checkpoints.py:49-167` proves that current
  checkpoints are internal recovery checkpoints, not a public fork resource.
  `app/services/simulation_kernel/branching.py:8-13` is an internal primitive
  whose `scenario_diff` is not applied by the helper.
- `app/services/evaluation/service.py:67-93,144-188` provides a governed,
  fixed seven-member project experiment; it is not an arbitrary matrix API.
- `app/services/evidence_registry.py:243-317,320-404,454-465` provides
  append-only Evidence sync/search/pack and provider-free report projection.

### External clean-room references

- [MiroFish workflow](https://github.com/666ghj/MiroFish/blob/main/README-ZH.md#-%E5%B7%A5%E4%BD%9C%E6%B5%81)
  — five-stage flow and long-task progress only; AGPL-3.0, no code/prompt copy.
- [OpenCTI workbench](https://github.com/OpenCTI-Platform/opencti/blob/master/docs/docs/usage/workbench.md),
  [draft workspaces](https://github.com/OpenCTI-Platform/opencti/blob/master/docs/docs/usage/draftWorkspaces.md)
  and [investigation graph](https://github.com/OpenCTI-Platform/opencti/blob/master/opencti-platform/opencti-front/src/private/components/workspaces/investigations/InvestigationGraph.tsx)
  — draft banner, review diff, approve/freeze and source-linked navigation.
  Community Edition is Apache-2.0; Enterprise files have separate terms.
- [OpenBB Workspace model](https://github.com/OpenBB-finance/openbb-docs/blob/main/content/workspace/index.md)
  and [data integration metadata](https://github.com/OpenBB-finance/openbb-docs/blob/main/content/workspace/developers/data-integration.md)
  — Widget/Dashboard/App metadata and linked parameters only; main OpenBB is
  AGPL-3.0, while the MIT backends example is a separate project.
- [LEAN ParameterSet](https://github.com/QuantConnect/Lean/blob/master/Common/Optimizer/Parameters/ParameterSet.cs)
  and [OptimizationBacktest](https://github.com/QuantConnect/Lean/blob/master/Common/Api/OptimizationBacktest.cs)
  — canonical finite matrix row identity and status/metrics separation only;
  Apache-2.0, no optimizer or financial semantics copy.
- [Concordia interviewer](https://github.com/google-deepmind/concordia/blob/main/concordia/prefabs/game_master/interviewer.py)
  and [OASIS interview cookbook](https://github.com/camel-ai/oasis/blob/main/docs/cookbooks/twitter_interview.mdx)
  — researcher-triggered questionnaire/observation boundary only; Apache-2.0,
  no runtime implementation copy.

### Allowed API list

The first implementation may call only existing Project/Workspace, Evidence,
Scenario Compiler, Evaluation and Run Control endpoints through the current
organization/CSRF client. It may read `ProjectDetail`, `ResearchRun`,
`ResearchRunDiff`, `ProjectAIReport`, `WarRoomWorkspaceState`, Evidence summary,
Scenario Draft and Evaluation DTOs.

Do not describe these as implemented: `/branches`, `/experiments`, `/fork`,
`/checkpoints`, saved Diff/Replay Pack CRUD, arbitrary matrix creation or a
public Kernel branch/replay endpoint.

## Phase 4A — GuidedResearchProjection and ordinary-research host extraction

### What to implement

Copy the route façade from `ResearchWorkspaceView.vue:1-9` and the pure
projection style from `scenarioCompilerProjection.js:1-37` to create:

- a typed `GuidedResearchProjection`/`GuidedSurfaceDescriptor` contract;
- a `useGuidedResearchProjection` composable with explicit inputs and no
  arbitrary `ctx` object;
- a `GuidedResearchHost.vue` presentational host for the ordinary research
  branch currently embedded in `ResearchWorkspacePage.vue:399-501`;
- a five-stage rail with deterministic `ready/blocked/in_progress/complete`
  gates and explicit unavailable reasons;
- report panels for `evidence`, `uncertainties`, `watch_signals`,
  `scenario_suggestions` and all citations, preserving the existing Markdown
  download and Chinese labels;
- a typed domain API adapter over the existing `api.js` functions. Do not
  bypass organization/CSRF interception or convert the whole frontend to
  TypeScript in this slice.

The host may receive one cohesive view model and action callbacks. It must not
grow a 30-prop cross-context contract. Keep War Room section components and
selectors unchanged.

### Documentation references

- `frontend/src/views/ResearchWorkspaceView.vue:1-9` — route façade.
- `frontend/src/composables/scenarioCompilerProjection.js:1-37` — pure stage
  projection.
- `frontend/src/composables/useScenarioCompiler.js:23-57` — scoped async load.
- `frontend/src/components/war-room/WarRoomOverviewConsole.vue:56-96` —
  explicit props/emits boundary.
- `frontend/src/api.js:3-31,199-224,469-497` — transport and existing Project
  calls.
- `app/core/models.py:474-613` — backend DTO source of truth.

### Verification checklist

- ordinary research route renders with the same existing project/run/report
  behavior and Chinese semantics;
- new unit tests cover every stage gate, missing-run state, uncertainty/citation
  grouping and organization-scoped API call selection;
- a route-level test proves ordinary research and War Room choose separate
  hosts without changing route paths;
- all existing frontend unit/type/build and Playwright gates pass;
- `rg` confirms new host does not import `axios` directly, Provider names or
  database code;
- no existing `data-testid` is removed or repurposed.

### Anti-pattern guards

- Do not invent numeric fallback values for missing Agent/entity projections;
  render `unavailable` with a reason.
- Do not pass a giant `ctx` object or mirror all 30 governance actions into the
  Guided host.
- Do not make `ResearchWorkspacePage.vue` read SQL-shaped state or add a new
  route solely for the rail.

## Phase 4B — Evidence and Scenario Draft governance context

### What to implement

Copy the governed Evidence and Scenario Compiler module contracts to expose a
shared Guided context:

- Evidence summary/search/sync and citation coverage as read projections;
- Scenario candidate → draft → review → approved/frozen state;
- a persistent draft context banner and a side-by-side original/new diff;
- explicit permissions and gate reasons for write/review actions;
- read-only approved revision display; edits create a new revision through the
  existing governed Draft clone path.

No new Evidence table is needed. Evidence remains append-only and all writes
go through `EvidenceApplicationPort`; no Connector writes Evidence directly.

### Documentation references

- `frontend/src/components/war-room/WarRoomEvidenceCenter.vue:1-20,93-111`.
- `frontend/src/components/war-room/WarRoomScenarioCompiler.vue:1-181`.
- `frontend/src/composables/useScenarioCompiler.js:23-138` and
  `scenarioCompilerProjection.js:1-50`.
- `app/api/v4.py:34-102`, `app/api/v8.py:94-126`.
- `app/services/evidence_registry.py:243-317,320-404,454-465`.
- `app/services/scenario_compiler/service.py:492-584,687-696`.
- OpenCTI draft workspace/workbench links above.

### Verification checklist

- candidate/draft/approved/frozen projections have contract tests;
- unauthorized write/review controls are hidden in UI and rejected by backend
  route tests;
- approved revision cannot be edited in place; clone lineage and hashes are
  displayed;
- Evidence cutoff and Pack hash failures remain fail-closed;
- existing governance E2E selectors and tests pass.

### Anti-pattern guards

- Do not treat extraction as approval or display a draft as verified Evidence.
- Do not copy OpenCTI STIX/GraphQL/Elastic code or Enterprise-only behavior.
- Do not let frontend permission visibility replace backend organization/RBAC
  enforcement.

## Phase 4C — bounded Experiment Matrix read surface

### What to implement

Copy LEAN's parameter-set identity separation into a WorldPulse view model,
not an optimizer:

- project a finite matrix from stored runs and existing governed Evaluation
  members;
- display `parameter_set_hash`, scenario revision/hash, role, run ID, status,
  comparability and non-comparable reasons;
- expose baseline/control/treated labels only when backed by stored lineage;
- aggregate Run Diff metrics and uncertainty without recomputing numeric state;
- add the missing typed frontend wrapper for the existing governed V10 project
  experiment only if its route-level contract test is added first.

Any new matrix creation or arbitrary row count requires a follow-up backend ADR.
The initial UI cap is 2–6 displayed rows; it must not claim to replace the
existing fixed seven-member evaluation matrix.

### Documentation references

- `app/services/evaluation/service.py:67-93,144-188` and
  `app/core/evaluation_models.py:46-143`.
- `app/api/v10.py:19-60`.
- `app/services/project_app/diffing.py:20-71`.
- `tests/test_v2_kernel_contracts.py:303-322` and
  `tests/test_v2_war_room_projection.py:205-246`.
- LEAN `ParameterSet.cs` and `OptimizationBacktest.cs` links above.

### Verification checklist

- identical canonical parameter maps produce identical row identity hashes;
- matrix rows with missing lineage are marked non-comparable, never silently
  compared;
- baseline/control/treated labels cannot change deterministic numeric outputs;
- evaluation route, organization isolation and retry lineage contract tests
  pass;
- no `/branches`, `/fork`, `/checkpoints` or arbitrary matrix endpoint is
  introduced in this slice.

### Anti-pattern guards

- Do not call the matrix an optimizer, forecast or prediction engine.
- Do not expose internal `ExperimentBranch` as a public Project API.
- Do not infer a control group from array order or latest-run position.

## Phase 4D — Run Comparison, uncertainty and cited brief

### What to implement

Copy existing Run Diff/Replay/Report contracts into a cross-mode Workspace
surface:

- make generic `ResearchRunDiff` visible in ordinary research mode;
- show War Room-specific deltas only when `changed_metrics.war_room` exists;
- add scenario/run/time selectors as linked parameters;
- expose Report Renderer lineage, evidence citations, deterministic derivation,
  Agent observations and uncertainty as separate panels;
- keep Markdown/JSON Replay Pack downloads provider-free and preserve manifest
  verification;
- correct citation drill-down to show all citations for a finding, not merely
  `citations[findingIndex]`.

### Documentation references

- `frontend/src/composables/useWarRoomArtifacts.js:1-119`.
- `app/api/routes.py:210-249`.
- `app/services/project_app/service.py:401-470` and
  `app/services/project_app/replay_application.py:37-189`.
- `app/services/plugin_sdk/builtins/report_renderer.py` and
  `tests/test_plugin_report_renderer.py`.
- `docs/architecture/replay-and-audit.md:14-53`.

### Verification checklist

- ordinary and War Room Run Diff contract tests both render;
- citation selection shows all matching citations and never drops lineage;
- report/replay tamper tests remain fail-closed and provider-free;
- linked selector changes do not mutate stored Run or numeric fields;
- E2E covers the ordinary guided path and existing War Room smoke path.

### Anti-pattern guards

- Do not persist a new Diff/Replay resource without an ADR and migration plan.
- Do not render an uncertainty score as a deterministic probability.
- Do not re-run analysis or Provider calls when opening historical reports.

## Phase 4E — controlled Interview observation (deferred)

This phase is intentionally not part of the first Guided Flow checkpoint. If
authorized, first write a dedicated ADR and route-level contract for a
researcher-triggered, completed-Run-only `ResearchInterviewArtifact`. It must
use a separate observation store/Artifact lineage, explicit permission and
budget, and provider-free stored replay. Concordia/OASIS references are
conceptual only; no implementation or prompt is copied.

## Phase 4F — final Phase 4 gates and rollback

Before declaring Phase 4 complete:

- V1-v11 HTTP/database/OpenAPI contracts and all existing stable selectors are
  unchanged;
- backend, frontend unit/type/build, Playwright, migration, OpenAPI, boundary,
  dependency, security and release scans pass;
- no live PostgreSQL skip is described as PostgreSQL verification;
- ordinary research can complete question → evidence/world model → scenario →
  matrix/read comparison → uncertainty/cited brief using stored lineage;
- all hashes, permissions, organization scope and provider-free replay gates
  fail closed.

Each slice receives its own local commit and rollback note. No remote push,
formal Tag, deployment or release is allowed without explicit authorization.

## Decision gates requiring user confirmation before expansion

Pause and ask before any of the following:

1. Public checkpoint/branch/fork semantics or a new database migration.
2. Arbitrary experiment matrix creation, matrix size above six visible rows or
   changes to the fixed V10 evaluation population.
3. Agent Interview provider/model policy, storage of prompt/response or use of
   interview output in a report's numeric conclusions.
4. A new V2 public non-deterministic creation path, separate service, queue or
   deployment model.

The next execution slice is 4A only: typed GuidedResearchProjection, ordinary
research host extraction, stage gates and report uncertainty/citation display.
