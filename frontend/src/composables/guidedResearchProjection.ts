import type {
  GuidedGateVerdict,
  GuidedResearchProjection,
  GuidedStageStatus,
  GuidedSurfaceDescriptor,
  ProjectDetail,
  ReportCitation,
  ResearchRun,
  ResearchRunDiff,
} from '../contracts/researchWorkspace'

const RUN_IN_PROGRESS_STATUSES = new Set(['preparing', 'running', 'in_progress', 'pausing', 'cancelling'])
const TERMINAL_RUN_STATUSES = new Set(['completed', 'failed', 'cancelled', 'timed_out', 'timeout'])
const SUBSTANTIVE_CITATION_KINDS = new Set(['evidence', 'causal_edge', 'backtest'])

interface StageInput {
  key: string
  index: string
  title: string
  description: string
  status: GuidedStageStatus
  verdict: GuidedGateVerdict
  dependsOn?: string[]
  reasons?: string[]
  sourceContracts?: string[]
  lineage?: Record<string, string>
}

export interface GuidedResearchProjectionContext {
  runDiff?: ResearchRunDiff | null
}

function stage({
  key,
  index,
  title,
  description,
  status,
  verdict,
  dependsOn = [],
  reasons = [],
  sourceContracts = [],
  lineage = {},
}: StageInput): GuidedSurfaceDescriptor {
  return {
    surface_id: `guided.${key}`,
    stage_key: key,
    index,
    title,
    description,
    status,
    unavailable_reasons: reasons,
    source_contracts: sourceContracts,
    lineage,
    gate: {
      verdict,
      depends_on: dependsOn,
    },
  }
}

function isRunInProgress(run: ResearchRun | null): boolean {
  return Boolean(run && RUN_IN_PROGRESS_STATUSES.has(String(run.status || '').toLowerCase()))
}

function isTerminalRun(run: ResearchRun | null): boolean {
  return Boolean(run && TERMINAL_RUN_STATUSES.has(String(run.status || '').toLowerCase()))
}

function dependencyBlocked(
  stages: GuidedSurfaceDescriptor[],
  dependencies: string[],
): GuidedSurfaceDescriptor | undefined {
  return dependencies
    .map(stageKey => stages.find(item => item.stage_key === stageKey))
    .find(item => item?.gate.verdict !== 'pass')
}

function dependencyReason(stageDescriptor: GuidedSurfaceDescriptor): string {
  return `前置阶段“${stageDescriptor.title}”尚未通过（${stageDescriptor.gate.verdict}）。`
}

function hasMatchingRunDiff(
  detail: ProjectDetail,
  runDiff: ResearchRunDiff | null | undefined,
): runDiff is ResearchRunDiff {
  if (!runDiff || runDiff.project_id !== detail.project.project_id) return false
  if (!runDiff.base_run_id || !runDiff.target_run_id || runDiff.base_run_id === runDiff.target_run_id) return false
  const runIds = new Set((detail.runs || []).map(run => run.run_id))
  return runIds.has(runDiff.base_run_id) && runIds.has(runDiff.target_run_id)
}

export function citationsForFinding(
  citations: ReportCitation[] = [],
  findingIndex = 0,
): ReportCitation[] {
  return citations.filter(item => Number(item.finding_index) === Number(findingIndex))
}

export function citationKindLabel(kind: string): string {
  return ({
    evidence: '事实证据',
    causal_edge: '确定性推导',
    backtest: '历史回测',
    plugin_manifest: '渲染器血缘',
  } as Record<string, string>)[kind] || kind || '引用'
}

function hasSubstantiveCitation(citations: ReportCitation[]): boolean {
  return citations.some(citation => (
    SUBSTANTIVE_CITATION_KINDS.has(String(citation.kind || '').trim().toLowerCase())
  ))
}

export function buildGuidedResearchProjection(
  detail: ProjectDetail | null | undefined,
  context: GuidedResearchProjectionContext = {},
): GuidedResearchProjection {
  const project = detail?.project || null
  const run = detail?.latest_run || null
  const graph = detail?.graph || null
  const report = detail?.report || null
  const citations = report?.citations || []
  const pluginLineage = run?.data_snapshot?.plugin_lineage
  const reportRenderer = pluginLineage && typeof pluginLineage === 'object'
    ? (pluginLineage as Record<string, unknown>).report_renderer
    : null
  const rendererManifestHash = reportRenderer && typeof reportRenderer === 'object'
    ? String((reportRenderer as Record<string, unknown>).plugin_manifest_hash || '')
    : ''
  const hasQuestion = Boolean(project?.question?.trim())
  const graphMatchesRun = Boolean(run && graph && graph.run_id === run.run_id)
  const reportMatchesRun = Boolean(run && report && report.run_id === run.run_id)
  const hasWorldModel = Boolean(graphMatchesRun && graph?.nodes?.length && graph?.edges?.length)
  const hasEvidence = Boolean(
    graphMatchesRun && (
      graph?.evidence_sources?.length
      || (reportMatchesRun && hasSubstantiveCitation(citations))
    ),
  )
  const hasBrief = Boolean(reportMatchesRun && report?.markdown?.trim() && report?.key_findings?.length)
  const runActive = isRunInProgress(run)
  const runTerminal = isTerminalRun(run)
  const stages: GuidedSurfaceDescriptor[] = []

  stages.push(stage({
    key: 'question',
    index: '01',
    title: '问题定义',
    description: '锁定研究问题、范围与时间窗口。',
    status: hasQuestion ? 'complete' : 'blocked',
    verdict: hasQuestion ? 'pass' : 'block',
    reasons: hasQuestion ? [] : ['研究问题尚未定义。'],
    sourceContracts: ['ResearchProject'],
    lineage: project ? { project_id: project.project_id } : {},
  }))

  const evidenceDependencies = ['question']
  const evidenceBlockedBy = dependencyBlocked(stages, evidenceDependencies)
  let evidenceStatus: GuidedStageStatus
  let evidenceVerdict: GuidedGateVerdict
  let evidenceReasons: string[]
  if (evidenceBlockedBy) {
    evidenceStatus = 'blocked'
    evidenceVerdict = 'block'
    evidenceReasons = [dependencyReason(evidenceBlockedBy)]
  } else if (hasWorldModel && hasEvidence) {
    evidenceStatus = 'complete'
    evidenceVerdict = 'pass'
    evidenceReasons = []
  } else if (runActive) {
    evidenceStatus = 'in_progress'
    evidenceVerdict = 'unavailable'
    evidenceReasons = ['研究运行正在执行，证据或世界模型尚未形成可验证投影。']
  } else if (runTerminal) {
    evidenceStatus = 'blocked'
    evidenceVerdict = 'unavailable'
    evidenceReasons = ['运行已结束，但缺少与该运行绑定的完整证据或世界模型投影。']
  } else if (run) {
    evidenceStatus = 'blocked'
    evidenceVerdict = 'unavailable'
    evidenceReasons = [`运行状态“${run.status || 'unknown'}”不是执行中状态，且证据或世界模型尚不可用。`]
  } else {
    evidenceStatus = 'blocked'
    evidenceVerdict = 'block'
    evidenceReasons = ['至少需要一次研究运行。']
  }
  stages.push(stage({
    key: 'evidence-world-model',
    index: '02',
    title: '证据与世界模型',
    description: '核对证据来源、因果节点与确定性推导边。',
    status: evidenceStatus,
    verdict: evidenceVerdict,
    dependsOn: evidenceDependencies,
    reasons: evidenceReasons,
    sourceContracts: ['CausalGraphSnapshot', 'ReportCitation'],
    lineage: graphMatchesRun && graph ? { graph_id: graph.graph_id, run_id: graph.run_id } : {},
  }))

  const scenarioDependencies = ['evidence-world-model']
  const scenarioBlockedBy = dependencyBlocked(stages, scenarioDependencies)
  stages.push(stage({
    key: 'scenario-matrix',
    index: '03',
    title: '场景与实验矩阵',
    description: '绑定受治理的场景修订；矩阵能力按显式合同逐步开放。',
    status: scenarioBlockedBy ? 'blocked' : 'ready',
    verdict: scenarioBlockedBy ? 'block' : 'unavailable',
    dependsOn: scenarioDependencies,
    reasons: scenarioBlockedBy
      ? [dependencyReason(scenarioBlockedBy)]
      : ['当前为兼容研究路径；4A 尚无真实场景治理投影，不能声明已批准场景修订。'],
    sourceContracts: ['ScenarioDraft', 'EvaluationBatch'],
  }))

  const compareDependencies = ['evidence-world-model']
  const compareBlockedBy = dependencyBlocked(stages, compareDependencies)
  const matchingRunDiff = detail ? hasMatchingRunDiff(detail, context.runDiff) : false
  let compareStatus: GuidedStageStatus
  let compareVerdict: GuidedGateVerdict
  let compareReasons: string[]
  if (compareBlockedBy) {
    compareStatus = 'blocked'
    compareVerdict = 'block'
    compareReasons = [dependencyReason(compareBlockedBy)]
  } else if (matchingRunDiff) {
    compareStatus = 'complete'
    compareVerdict = 'pass'
    compareReasons = []
  } else {
    compareStatus = 'ready'
    compareVerdict = 'unavailable'
    compareReasons = [(detail?.runs?.length || 0) > 1
      ? '已有可比较运行，但尚未加载真实 Run Diff 投影。'
      : '尚未加载真实 Run Diff 投影；至少选择两次运行后才能比较。']
  }
  stages.push(stage({
    key: 'runs-compare',
    index: '04',
    title: '运行与比较',
    description: '选择已存运行，查看 Run Diff 与可比性边界。',
    status: compareStatus,
    verdict: compareVerdict,
    dependsOn: compareDependencies,
    reasons: compareReasons,
    sourceContracts: ['ResearchRun', 'ResearchRunDiff'],
    lineage: matchingRunDiff && context.runDiff ? {
      base_run_id: context.runDiff.base_run_id,
      target_run_id: context.runDiff.target_run_id,
    } : (run ? { run_id: run.run_id } : {}),
  }))

  const briefDependencies = ['evidence-world-model']
  const briefBlockedBy = dependencyBlocked(stages, briefDependencies)
  let briefStatus: GuidedStageStatus
  let briefVerdict: GuidedGateVerdict
  let briefReasons: string[]
  if (briefBlockedBy) {
    briefStatus = 'blocked'
    briefVerdict = 'block'
    briefReasons = [dependencyReason(briefBlockedBy)]
  } else if (hasBrief) {
    briefStatus = 'complete'
    briefVerdict = 'pass'
    briefReasons = []
  } else if (runActive) {
    briefStatus = 'in_progress'
    briefVerdict = 'unavailable'
    briefReasons = ['研究运行正在执行，正式简报尚未形成可验证投影。']
  } else if (runTerminal) {
    briefStatus = 'blocked'
    briefVerdict = 'unavailable'
    briefReasons = ['运行已结束，但缺少与该运行绑定的正式简报投影。']
  } else {
    briefStatus = 'blocked'
    briefVerdict = run ? 'unavailable' : 'block'
    briefReasons = [run
      ? `运行状态“${run.status || 'unknown'}”不是执行中状态，且正式简报尚不可用。`
      : '尚无报告。']
  }
  stages.push(stage({
    key: 'cited-brief',
    index: '05',
    title: '引证简报与追问',
    description: '分开展示事实证据、确定性推导、观察与不确定性。',
    status: briefStatus,
    verdict: briefVerdict,
    dependsOn: briefDependencies,
    reasons: briefReasons,
    sourceContracts: ['ProjectAIReport', 'ReportCitation'],
    lineage: reportMatchesRun && report ? {
      report_id: report.report_id,
      run_id: report.run_id,
      ...(rendererManifestHash ? { renderer_manifest_hash: rendererManifestHash } : {}),
    } : {},
  }))

  const findingCount = report?.key_findings?.length || 0
  const citationsByFinding: Record<number, ReportCitation[]> = {}
  const unboundCitations: ReportCitation[] = []
  const contractIssues: GuidedResearchProjection['citationContractIssues'] = []
  citations.forEach((citation, citationIndex) => {
    const findingIndex = Number(citation.finding_index)
    if (!Number.isInteger(findingIndex) || findingIndex < 0 || findingIndex >= findingCount) {
      unboundCitations.push(citation)
      contractIssues.push({
        code: 'citation_finding_out_of_range',
        citation_id: citation.citation_id || `citation-${citationIndex}`,
        message: `引用 ${citation.citation_id || citationIndex} 的 finding_index=${String(citation.finding_index)} 未绑定到现有结论。`,
      })
      return
    }
    const findingCitations = citationsByFinding[findingIndex] || []
    findingCitations.push(citation)
    citationsByFinding[findingIndex] = findingCitations
  })

  return {
    schema_version: 'guided-research-projection.v1',
    project_id: project?.project_id || '',
    run_id: run?.run_id || '',
    stages,
    citationsByFinding,
    unboundCitations,
    citationContractIssues: contractIssues,
    reportSections: {
      evidence: report?.evidence || [],
      uncertainties: report?.uncertainties || [],
      watchSignals: report?.watch_signals || [],
      scenarioSuggestions: report?.scenario_suggestions || [],
    },
  }
}
