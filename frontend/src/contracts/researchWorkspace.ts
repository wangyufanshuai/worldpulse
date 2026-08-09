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
