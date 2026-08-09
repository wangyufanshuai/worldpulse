import { describe, expect, it } from 'vitest'

import {
  buildGuidedResearchProjection,
  citationKindLabel,
  citationsForFinding,
} from '../src/composables/guidedResearchProjection'

function projectDetail({
  withRun = true,
  runCount = 1,
  runStatus = 'completed',
  withGraph = withRun,
  withReport = withRun,
  question = '如何识别能源冲击的证据边界？',
  snapshotScenarioLineage = false,
} = {}) {
  const run = withRun ? {
    run_id: 'run-guided-1',
    status: runStatus,
    data_snapshot: {
      run_mode: 'fast',
      ...(snapshotScenarioLineage ? {
        scenario_draft_id: 'draft-1',
        scenario_draft_hash: 'a'.repeat(64),
      } : {}),
      plugin_lineage: { report_renderer: { plugin_manifest_hash: 'b'.repeat(64) } },
    },
  } : null
  return {
    project: { project_id: 'project-guided', question },
    latest_run: run,
    runs: withRun
      ? Array.from({ length: runCount }, (_, index) => ({ ...run, run_id: `run-guided-${index + 1}` }))
      : [],
    graph: withGraph ? {
      graph_id: 'graph-guided',
      run_id: 'run-guided-1',
      nodes: [{ id: 'event' }],
      edges: [{ source: 'event', target: 'risk' }],
      evidence_sources: ['WorldPulse deterministic fixture'],
    } : null,
    report: withReport ? {
      report_id: 'report-guided',
      run_id: 'run-guided-1',
      markdown: '# report',
      key_findings: ['结论一'],
      evidence: [{ title: '证据', source: 'fixture', interpretation: '可追溯证据。' }],
      uncertainties: ['样本窗口有限。'],
      watch_signals: [{ name: '能源压力' }],
      scenario_suggestions: [{ name: '低强度对照组' }],
      citations: [
        { citation_id: 'E1', finding_index: 0, kind: 'evidence', summary: '事实证据' },
        { citation_id: 'G1', finding_index: 0, kind: 'causal_edge', summary: '确定性推导' },
      ],
    } : null,
    chat_messages: [],
  }
}

function stageByKey(projection, stageKey) {
  return projection.stages.find(stage => stage.stage_key === stageKey)
}

describe('Guided Research projection', () => {
  it('fails closed with explicit dependency verdicts before the first run', () => {
    const projection = buildGuidedResearchProjection(projectDetail({ withRun: false }))
    expect(projection.schema_version).toBe('guided-research-projection.v1')
    expect(projection.stages.map(stage => stage.status)).toEqual([
      'complete', 'blocked', 'blocked', 'blocked', 'blocked',
    ])
    expect(projection.stages[1].unavailable_reasons[0]).toContain('至少需要一次研究运行')
    expect(projection.stages[2].gate).toEqual({
      verdict: 'block',
      depends_on: ['evidence-world-model'],
    })
    expect(projection.stages[2].unavailable_reasons[0]).toContain('前置阶段')
  })

  it('projects completed evidence and brief without claiming an unloaded Run Diff', () => {
    const projection = buildGuidedResearchProjection(projectDetail({ runCount: 2 }))
    expect(projection.stages.map(stage => stage.status)).toEqual([
      'complete', 'complete', 'ready', 'ready', 'complete',
    ])
    expect(stageByKey(projection, 'scenario-matrix').gate.verdict).toBe('unavailable')
    expect(stageByKey(projection, 'runs-compare').unavailable_reasons[0]).toContain('尚未加载真实 Run Diff 投影')
    expect(projection.reportSections.uncertainties).toEqual(['样本窗口有限。'])
    expect(stageByKey(projection, 'cited-brief').lineage.renderer_manifest_hash).toMatch(/^b{64}$/)
  })

  it('fails closed when renderer lineage is the only citation and no graph evidence source exists', () => {
    const detail = projectDetail()
    detail.graph.evidence_sources = []
    detail.report.citations = [{
      citation_id: 'P1',
      finding_index: 0,
      kind: 'plugin_manifest',
      summary: 'Renderer lineage remains visible but is not substantive evidence.',
    }]

    const projection = buildGuidedResearchProjection(detail)

    expect(stageByKey(projection, 'evidence-world-model')).toMatchObject({
      status: 'blocked',
      gate: { verdict: 'unavailable' },
    })
    expect(stageByKey(projection, 'cited-brief').status).toBe('blocked')
    expect(projection.citationsByFinding[0].map(item => item.citation_id)).toEqual(['P1'])
  })

  it('passes evidence with a substantive citation while retaining renderer lineage in the ledger', () => {
    const detail = projectDetail()
    detail.graph.evidence_sources = []
    detail.report.citations = [
      { citation_id: 'P1', finding_index: 0, kind: 'plugin_manifest', summary: 'Renderer lineage' },
      { citation_id: 'B1', finding_index: 0, kind: 'backtest', summary: 'Historical backtest evidence' },
    ]

    const projection = buildGuidedResearchProjection(detail)

    expect(stageByKey(projection, 'evidence-world-model')).toMatchObject({
      status: 'complete',
      gate: { verdict: 'pass' },
    })
    expect(projection.citationsByFinding[0].map(item => item.citation_id)).toEqual(['P1', 'B1'])
  })

  it('never infers approved governance from compatibility snapshot scenario fields', () => {
    const detail = projectDetail({ snapshotScenarioLineage: true })
    detail.latest_run.data_snapshot.scenario_config = { scenario_key: 'compatibility-path' }
    const scenario = stageByKey(buildGuidedResearchProjection(detail), 'scenario-matrix')
    expect(scenario.status).toBe('ready')
    expect(scenario.gate.verdict).toBe('unavailable')
    expect(scenario.lineage).toEqual({})
    expect(scenario.unavailable_reasons[0]).toContain('4A 尚无真实场景治理投影')
  })

  it('uses in_progress only for an actually running run and blocks dependent stages', () => {
    const projection = buildGuidedResearchProjection(projectDetail({
      runStatus: 'running',
      withGraph: false,
      withReport: false,
    }))
    expect(stageByKey(projection, 'evidence-world-model').status).toBe('in_progress')
    expect(stageByKey(projection, 'scenario-matrix').status).toBe('blocked')
    expect(stageByKey(projection, 'runs-compare').status).toBe('blocked')
    expect(stageByKey(projection, 'cited-brief').status).toBe('blocked')
    expect(stageByKey(projection, 'cited-brief').unavailable_reasons[0]).toContain('前置阶段')
  })

  it('does not pass downstream evidence when the question gate is blocked', () => {
    const projection = buildGuidedResearchProjection(projectDetail({ question: '   ' }))
    expect(stageByKey(projection, 'question').gate.verdict).toBe('block')
    expect(stageByKey(projection, 'evidence-world-model')).toMatchObject({
      status: 'blocked',
      gate: { verdict: 'block', depends_on: ['question'] },
    })
    expect(stageByKey(projection, 'evidence-world-model').unavailable_reasons[0]).toContain('问题定义')
  })

  it('marks terminal runs with missing graph or report projections unavailable', () => {
    const missingGraph = buildGuidedResearchProjection(projectDetail({
      runStatus: 'completed',
      withGraph: false,
      withReport: false,
    }))
    expect(stageByKey(missingGraph, 'evidence-world-model')).toMatchObject({
      status: 'blocked',
      gate: { verdict: 'unavailable' },
    })
    expect(stageByKey(missingGraph, 'evidence-world-model').unavailable_reasons[0]).toContain('运行已结束')

    const missingReport = buildGuidedResearchProjection(projectDetail({
      runStatus: 'completed',
      withGraph: true,
      withReport: false,
    }))
    expect(stageByKey(missingReport, 'evidence-world-model').status).toBe('complete')
    expect(stageByKey(missingReport, 'cited-brief')).toMatchObject({
      status: 'blocked',
      gate: { verdict: 'unavailable' },
    })
    expect(stageByKey(missingReport, 'cited-brief').unavailable_reasons[0]).toContain('缺少与该运行绑定')
  })

  it('completes Run Diff only for a real, matching diff projection', () => {
    const detail = projectDetail({ runCount: 2 })
    const unloaded = stageByKey(buildGuidedResearchProjection(detail), 'runs-compare')
    expect(unloaded.status).toBe('ready')

    const runDiff = {
      project_id: 'project-guided',
      base_run_id: 'run-guided-1',
      target_run_id: 'run-guided-2',
      summary: '真实差异投影',
    }
    const loaded = stageByKey(buildGuidedResearchProjection(detail, { runDiff }), 'runs-compare')
    expect(loaded.status).toBe('complete')
    expect(loaded.gate.verdict).toBe('pass')
    expect(loaded.lineage).toEqual({
      base_run_id: 'run-guided-1',
      target_run_id: 'run-guided-2',
    })

    const mismatched = stageByKey(buildGuidedResearchProjection(detail, {
      runDiff: { ...runDiff, target_run_id: 'run-missing' },
    }), 'runs-compare')
    expect(mismatched.status).toBe('ready')
    expect(mismatched.gate.verdict).toBe('unavailable')
  })

  it('groups citations from the citation ledger and exposes unbound contract violations', () => {
    const detail = projectDetail()
    detail.report.citations.push(
      { citation_id: 'E2', finding_index: 3, kind: 'evidence', summary: '越界引用' },
      { citation_id: 'E3', finding_index: -1, kind: 'evidence', summary: '未绑定引用' },
    )
    const projection = buildGuidedResearchProjection(detail)
    expect(citationsForFinding(detail.report.citations, 0).map(item => item.citation_id)).toEqual(['E1', 'G1'])
    expect(projection.citationsByFinding[0].map(item => item.citation_id)).toEqual(['E1', 'G1'])
    expect(projection.unboundCitations.map(item => item.citation_id)).toEqual(['E2', 'E3'])
    expect(projection.citationContractIssues).toHaveLength(2)
    expect(projection.citationContractIssues[0].message).toContain('未绑定到现有结论')
    expect(citationKindLabel('evidence')).toBe('事实证据')
    expect(citationKindLabel('causal_edge')).toBe('确定性推导')
    expect(citationKindLabel('plugin_manifest')).toBe('渲染器血缘')
  })
})
