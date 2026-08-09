export type GuidedStageStatus = 'ready' | 'blocked' | 'in_progress' | 'complete'
export type GuidedGateVerdict = 'pass' | 'block' | 'unavailable'

export interface ResearchProject {
  project_id: string
  title: string
  question: string
  region: string
  asset_scope: string[]
  event_window_days: number
  event_types: string[]
  mode: string
  scenario_config: Record<string, unknown>
  status: string
  created_at: string
  updated_at: string
}

export interface ResearchRun {
  run_id: string
  project_id: string
  status: string
  started_at: string
  completed_at?: string | null
  summary: string
  data_snapshot: Record<string, unknown>
  risk_snapshot: Record<string, unknown>
  event_snapshot: Array<Record<string, unknown>>
  simulation_snapshot: Record<string, unknown>
  backtest_snapshot: Record<string, unknown>
}

export interface ReportCitation {
  citation_id: string
  finding_index: number
  kind: string
  target_id: string
  title: string
  summary: string
  source: string
  confidence: number
}

export interface ProjectAIReport {
  report_id: string
  project_id: string
  run_id: string
  generated_at: string
  mode: string
  title: string
  summary: string
  key_findings: string[]
  evidence: ReportEvidenceItem[]
  uncertainties: string[]
  watch_signals: ReportWatchSignal[]
  scenario_suggestions: ReportScenarioSuggestion[]
  citations: ReportCitation[]
  markdown: string
  disclaimer: string
}

export interface ReportEvidenceItem {
  title: string
  source: string
  value: string
  interpretation: string
}

export interface ReportWatchSignal {
  name: string
  direction: string
  why_it_matters: string
  current_status: string
}

export interface ReportScenarioSuggestion {
  name: string
  shock_type: string
  target_codes: string[]
  rationale: string
}

export interface CausalGraphNode {
  id: string
  label: string
  kind: string
  score: number
}

export interface CausalGraphEdge {
  source: string
  target: string
  relation: string
  weight: number
  confidence: number
  explanation: string
}

export interface CausalGraphSnapshot {
  graph_id: string
  project_id: string
  run_id: string
  generated_at: string
  nodes: CausalGraphNode[]
  edges: CausalGraphEdge[]
  confidence: number
  evidence_sources: string[]
}

export interface ProjectChatMessage {
  message_id: string
  project_id: string
  role: string
  content: string
  created_at: string
  mode: string
}

export interface ProjectDetail {
  project: ResearchProject
  latest_run?: ResearchRun | null
  runs: ResearchRun[]
  graph?: CausalGraphSnapshot | null
  report?: ProjectAIReport | null
  chat_messages: ProjectChatMessage[]
}

export interface ResearchRunDiff {
  project_id: string
  base_run_id: string
  target_run_id: string
  summary: string
  risk_delta?: number | null
  confidence_delta?: number | null
  event_count_delta: number
  evidence_source_delta: number
  added_events: string[]
  removed_events: string[]
  added_sources: string[]
  removed_sources: string[]
  changed_metrics: Record<string, unknown>
}

export interface GuidedSurfaceDescriptor {
  surface_id: string
  stage_key: string
  index: string
  status: GuidedStageStatus
  title: string
  description: string
  unavailable_reasons: string[]
  source_contracts: string[]
  lineage: Record<string, string>
  gate: {
    verdict: GuidedGateVerdict
    depends_on: string[]
  }
}

export interface GuidedReportSections {
  evidence: ReportEvidenceItem[]
  uncertainties: string[]
  watchSignals: ReportWatchSignal[]
  scenarioSuggestions: ReportScenarioSuggestion[]
}

export interface GuidedResearchProjection {
  schema_version: 'guided-research-projection.v1'
  project_id: string
  run_id: string
  stages: GuidedSurfaceDescriptor[]
  citationsByFinding: Record<number, ReportCitation[]>
  unboundCitations: ReportCitation[]
  citationContractIssues: Array<{
    code: 'citation_finding_out_of_range'
    citation_id: string
    message: string
  }>
  reportSections: GuidedReportSections
}

export interface GuidedCitationDrawerItem extends ReportCitation {
  kind_label: string
}

export interface GuidedCitationDrawer {
  finding: string
  summary: string
  citations: GuidedCitationDrawerItem[]
}

export interface GuidedResearchHostModel {
  detail: ProjectDetail
  projection: GuidedResearchProjection
  governance: GuidedGovernanceProjection
  statusText: string
  currentModeText: string
  runMode: string
  running: boolean
  chatting: boolean
  message: string
  prompts: string[]
  markdownUrl: string
  evidenceDrawer: GuidedCitationDrawer | null
}

export interface ResearchWorkspaceClient {
  getProject(projectId: string): Promise<ProjectDetail>
  getProjectRun(projectId: string, runId: string): Promise<ProjectDetail>
  listProjectRuns(projectId: string): Promise<ResearchRun[]>
  compareProjectRuns(
    projectId: string,
    baseRunId: string,
    targetRunId: string,
  ): Promise<ResearchRunDiff>
  runProject(projectId: string, mode?: string): Promise<ProjectDetail>
  chatWithProject(projectId: string, message: string): Promise<ProjectChatMessage>
}

export type OrganizationRole = 'owner' | 'admin' | 'analyst' | 'reviewer' | 'viewer'
export type EvidenceIntegrityStatus = 'verified' | 'failed' | 'empty'
export type ScenarioCandidateDecisionType = 'accepted' | 'rejected'
export type ScenarioDraftStatus =
  | 'draft'
  | 'submitted'
  | 'approved'
  | 'revision_requested'
  | 'rejected'
  | 'superseded'
export type ScenarioReviewDecision = 'approve' | 'request_revision' | 'reject'
export type GuidedGovernanceState = 'candidate' | 'draft' | 'review' | 'approved' | 'frozen'

export interface ResearchOrganization {
  organization_id: string
  slug: string
  name: string
  status: string
  member_role?: OrganizationRole | null
  created_by_user_id?: string | null
  created_at: string
  updated_at: string
}

export interface EvidenceSource {
  source_id: string
  source_type: string
  name: string
  locator: string
  publisher: string
  status: 'active' | 'degraded' | 'retired'
  trust_tier: string
  metadata: Record<string, unknown>
  created_by_user_id?: string | null
  created_at: string
  retired_at?: string | null
}

export interface EvidenceSnapshotSummary {
  snapshot_id: string
  source_id: string
  project_id?: string | null
  external_ref: string
  title: string
  category: string
  observed_at: string
  cutoff_at: string
  captured_at: string
  content_hash: string
  created_by_user_id?: string | null
  integrity_status: 'verified' | 'failed'
}

export interface EvidenceClaim {
  claim_id: string
  project_id?: string | null
  run_id?: string | null
  statement: string
  claim_type: string
  confidence: number
  valid_from?: string | null
  valid_to?: string | null
  cutoff_at: string
  claim_hash: string
  created_by_user_id?: string | null
  created_at: string
  links: Array<Record<string, unknown>>
}

export interface EvidencePack {
  pack_id: string
  project_id?: string | null
  run_id?: string | null
  name: string
  cutoff_at: string
  manifest: Record<string, unknown>
  manifest_hash: string
  created_by_user_id?: string | null
  created_at: string
}

export interface ProjectEvidenceSummary {
  project_id: string
  source_count: number
  snapshot_count: number
  claim_count: number
  linked_claim_count: number
  pack_count: number
  coverage: number
  integrity_status: EvidenceIntegrityStatus
  cutoff_safe: boolean
  latest_cutoff_at?: string | null
  latest_pack?: EvidencePack | null
  sources: EvidenceSource[]
  recent_snapshots: EvidenceSnapshotSummary[]
  recent_claims: EvidenceClaim[]
  generated_at: string
}

export interface EvidenceSearchResult {
  query: string
  cutoff_at?: string | null
  total: number
  snapshots: EvidenceSnapshotSummary[]
  claims: EvidenceClaim[]
}

export interface EvidenceSyncResult {
  project_id: string
  run_id?: string | null
  sources_created: number
  snapshots_created: number
  claims_created: number
  links_created: number
  summary: ProjectEvidenceSummary
}

export interface ScenarioCandidateDecision {
  decision_id: string
  candidate_id: string
  organization_id: string
  project_id: string
  decision: ScenarioCandidateDecisionType
  normalized_value?: string | null
  comment: string
  actor_user_id: string
  decision_hash: string
  created_at: string
}

export interface ScenarioCandidate {
  candidate_id: string
  extraction_id: string
  organization_id: string
  project_id: string
  candidate_type: 'scenario_preset' | 'country' | 'supply_chain' | 'policy_action' | 'relationship' | 'event_date'
  canonical_value: string
  display_value: string
  relation: Record<string, unknown>
  snapshot_id: string
  locator: Record<string, unknown>
  excerpt: string
  confidence: number
  extractor_source: string
  validation_status: 'valid' | 'invalid'
  validation_reason?: string | null
  candidate_hash: string
  created_at: string
  origin: Record<string, unknown>
  latest_decision?: ScenarioCandidateDecision | null
}

export interface ScenarioDraftReview {
  review_id: string
  draft_id: string
  decision: ScenarioReviewDecision
  comment: string
  reviewer_user_id: string
  review_hash: string
  created_at: string
}

export interface ScenarioDraft {
  draft_id: string
  organization_id: string
  project_id: string
  parent_draft_id?: string | null
  version: number
  status: ScenarioDraftStatus
  name: string
  scenario: Record<string, unknown>
  manual_assumptions: Record<string, unknown>
  compiler_version: string
  evidence_pack_id?: string | null
  evidence_pack_hash?: string | null
  draft_hash: string
  created_by_user_id: string
  submitted_by_user_id?: string | null
  approved_by_user_id?: string | null
  review_case_id?: string | null
  created_at: string
  submitted_at?: string | null
  approved_at?: string | null
  closed_at?: string | null
  candidate_ids: string[]
  reviews: ScenarioDraftReview[]
}

export interface ScenarioDraftReviewRequest {
  decision: ScenarioReviewDecision
  comment?: string
}

export interface ResearchGovernanceClient {
  getCurrentOrganization(): Promise<ResearchOrganization>
  getProjectEvidenceSummary(projectId: string): Promise<ProjectEvidenceSummary>
  getEvidencePack(packId: string): Promise<EvidencePack>
  syncProjectEvidence(projectId: string, runId?: string | null): Promise<EvidenceSyncResult>
  searchEvidence(params?: Record<string, unknown>): Promise<EvidenceSearchResult>
  listScenarioCandidates(organizationId: string, projectId: string): Promise<ScenarioCandidate[]>
  listScenarioDrafts(organizationId: string, projectId: string): Promise<ScenarioDraft[]>
  getScenarioDraft(organizationId: string, projectId: string, draftId: string): Promise<ScenarioDraft>
  submitScenarioDraft(organizationId: string, projectId: string, draftId: string): Promise<ScenarioDraft>
  reviewScenarioDraft(
    organizationId: string,
    projectId: string,
    draftId: string,
    payload: ScenarioDraftReviewRequest,
  ): Promise<ScenarioDraft>
  cloneScenarioDraft(organizationId: string, projectId: string, draftId: string): Promise<ScenarioDraft>
}

export interface GuidedGovernancePermission {
  allowed: boolean
  reason: string
}

export interface GuidedGovernancePermissions {
  write: GuidedGovernancePermission
  review: GuidedGovernancePermission
}

export interface GuidedGovernanceStep {
  key: GuidedGovernanceState
  label: string
  status: 'complete' | 'current' | 'pending' | 'unavailable'
  reason: string
}

export interface GuidedScenarioDiff {
  available: boolean
  unavailable_reason: string
  parent_draft_id: string
  current_draft_id: string
  original: {
    version: number
    draft_hash: string
    evidence_pack_id: string
    evidence_pack_hash: string
    scenario: Record<string, unknown>
    manual_assumptions: Record<string, unknown>
  } | null
  current: {
    version: number
    draft_hash: string
    evidence_pack_id: string
    evidence_pack_hash: string
    scenario: Record<string, unknown>
    manual_assumptions: Record<string, unknown>
  } | null
  changed_fields: string[]
}

export type EvidencePackVerificationStatus =
  | 'not_required'
  | 'verified'
  | 'missing'
  | 'unavailable'
  | 'mismatch'
  | 'project_mismatch'

export interface EvidencePackVerification {
  draft_id: string
  pack_id: string
  expected_manifest_hash: string
  status: EvidencePackVerificationStatus
  reason: string
  pack: EvidencePack | null
}

export interface GuidedGovernanceProjection {
  schema_version: 'guided-governance-projection.v1'
  loading: boolean
  busy: boolean
  error: string
  banner: {
    state: GuidedGovernanceState
    title: string
    detail: string
  }
  evidence: {
    summary: ProjectEvidenceSummary | null
    searchResult: EvidenceSearchResult
    gate_reasons: string[]
  }
  scenario: {
    candidates: ScenarioCandidate[]
    drafts: ScenarioDraft[]
    activeDraft: ScenarioDraft | null
    approvedDraft: ScenarioDraft | null
    parentDraft: ScenarioDraft | null
    activePackVerification: EvidencePackVerification
    approvedPackVerification: EvidencePackVerification
    state: GuidedGovernanceState
    steps: GuidedGovernanceStep[]
    gate_reasons: string[]
    diff: GuidedScenarioDiff
  }
  permissions: GuidedGovernancePermissions
}

export interface GuidedResearchGovernanceState {
  organization: ResearchOrganization | null
  evidenceSummary: ProjectEvidenceSummary | null
  searchResult: EvidenceSearchResult
  candidates: ScenarioCandidate[]
  drafts: ScenarioDraft[]
  activeDraft: ScenarioDraft | null
  approvedDraft: ScenarioDraft | null
  parentDraft: ScenarioDraft | null
  activePackVerification: EvidencePackVerification
  approvedPackVerification: EvidencePackVerification
  loading: boolean
  mutationBusy: boolean
  error: string
  actionError: string
  canWrite: boolean
  canReview: boolean
}
