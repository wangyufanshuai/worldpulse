import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'

import { buildGuidedExperimentMatrixProjection } from '../src/composables/guidedExperimentMatrixProjection'

const DRAFT_HASH = 'd'.repeat(64)
const PACK_HASH = 'e'.repeat(64)

function draft(overrides = {}) {
  return {
    draft_id: 'draft-approved', project_id: 'project-1', organization_id: 'org-1',
    status: 'approved', draft_hash: DRAFT_HASH, evidence_pack_id: 'pack-1', evidence_pack_hash: PACK_HASH,
    ...overrides,
  }
}

function verification(overrides = {}) {
  return {
    draft_id: 'draft-approved', pack_id: 'pack-1', expected_manifest_hash: PACK_HASH,
    status: 'verified', reason: 'verified',
    pack: { pack_id: 'pack-1', project_id: 'project-1', manifest_hash: PACK_HASH },
    ...overrides,
  }
}

function batch(overrides = {}) {
  return {
    batch_id: 'eval-project-1', organization_id: 'org-1', project_id: 'project-1',
    scenario_draft_id: 'draft-approved', scenario_draft_hash: DRAFT_HASH,
    evidence_pack_hash: PACK_HASH, suite_id: 'project-experiment.v1', suite_hash: 's'.repeat(64),
    rule_pack_id: 'rules-1', rule_pack_hash: 'r'.repeat(64), runtime_profile: {},
    runtime_profile_hash: 'p'.repeat(64), provider_mode: 'mock', source_type: 'project',
    status: 'completed', total_members: 7, completed_members: 7, failed_members: 0,
    safety_status: 'passed', quality_status: 'observed', metrics: {}, report_hash: 'q'.repeat(64),
    gate_manifest_hash: 'g'.repeat(64), root_batch_id: 'eval-project-1',
    created_at: '2026-08-10', updated_at: '2026-08-10', completed_at: '2026-08-10',
    evaluation_track: 'project_experiment', ...overrides,
  }
}

const MEMBER_SPECS = [
  ['deterministic', 1],
  ['hybrid', 11],
  ['hybrid', 29],
  ['hybrid', 47],
  ['negotiation', 11],
  ['negotiation', 29],
  ['negotiation', 47],
]

function member(index, overrides = {}) {
  const [engineMode, seed] = MEMBER_SPECS[index]
  const parameterHash = seed === 1 ? 'parameters-deterministic' : `parameters-seed-${seed}`
  return {
    member_id: `member-${index}`, batch_id: 'eval-project-1', case_id: 'case-1',
    engine_mode: engineMode, seed, run_id: `run-${index}`, status: 'completed',
    baseline_result_hash: `baseline-${index}`, expected_baseline_hash: 'baseline-0',
    result_hash: `result-${index}`,
    metrics: { provider_calls: 0 }, artifact_refs: ['war_room_result'],
    created_at: '2026-08-10', updated_at: '2026-08-10', completed_at: '2026-08-10',
    input_hash: parameterHash, verification_status: 'passed',
    verification_hash: `verification-${index}`, ...overrides,
  }
}

function state(overrides = {}) {
  return {
    projectId: 'project-1', organizationId: 'org-1', approvedDraft: draft(),
    approvedPackVerification: verification(), phase4BGateReasons: [], batch: batch(),
    members: Array.from({ length: 7 }, (_, index) => member(index)), metrics: [],
    loading: false, error: '', ...overrides,
  }
}

describe('Guided V10 bounded experiment matrix projection', () => {
  it('keeps gate reasons as a semantic list inside a live region and scopes every column header', () => {
    const template = readFileSync(
      new URL('../src/components/research-workspace/GuidedExperimentMatrix.vue', import.meta.url),
      'utf8',
    )

    expect(template).toMatch(/<div v-if="matrix\.gate\.reasons\.length" role="status" aria-live="polite">\s*<ul class="matrix-gates"/)
    expect(template).not.toMatch(/<ul[^>]+role="status"/)
    expect(template.match(/<th scope="col">/g)).toHaveLength(6)
  })

  it('canonically orders all seven members before applying the six-row visibility cap', () => {
    const shuffled = [member(6), member(3), member(1), member(5), member(0), member(4), member(2)]
    const projection = buildGuidedExperimentMatrixProjection(state({ members: shuffled }))
    expect(projection.schema_version).toBe('guided-experiment-matrix.v1')
    expect(projection.fixed_population).toBe(7)
    expect(projection.visible_row_cap).toBe(6)
    expect(projection.total_rows).toBe(7)
    expect(projection.hidden_row_count).toBe(1)
    expect(projection.rows.map(row => row.row_id)).toEqual([
      'member-0', 'member-1', 'member-2', 'member-3', 'member-4', 'member-5',
    ])
    expect(projection.gate).toEqual({ verdict: 'pass', reasons: [] })
  })

  it('never infers roles, uncertainty, plugin lineage, or a V10-member Run Diff', () => {
    const source = state()
    source.members[0].metrics = {
      uncertainty: { guessed: true },
      plugin_lineage: { renderer: { manifest_hash: 'not-a-contract-field' } },
    }
    source.metrics = [{
      metric_id: 'metric-1', batch_id: 'eval-project-1', member_id: 'member-0', scope: 'quality',
      metric_key: 'confidence_interval_guess', value: 7.125, passed: true,
      metric_hash: 'metric-hash', created_at: '2026-08-10',
    }]
    const projection = buildGuidedExperimentMatrixProjection(source)
    const row = projection.rows[0]
    expect(row.role).toBeNull()
    expect(row.role_unavailable_reason).toContain('不得按数组顺序')
    expect(row.metrics_projection).toEqual(source.members[0].metrics)
    expect(row.evaluation_metrics).toEqual(source.metrics)
    expect(row.uncertainty_unavailable_reason).toContain('不从通用 metrics')
    expect(row.plugin_lineage_unavailable_reason).toContain('不从通用 metrics')
    expect(row).not.toHaveProperty('uncertainty_projection')
    expect(row.lineage).not.toHaveProperty('plugin_lineage')
    expect(projection).not.toHaveProperty('stored_run_diff')
    expect(projection.source_contracts.every(item => !item.includes('compare'))).toBe(true)
  })

  it.each([
    ['pending verification', { verification_status: 'pending' }, '精确为 passed'],
    ['failed verification', { verification_status: 'failed' }, '精确为 passed'],
    ['missing verification status', { verification_status: '' }, 'missing'],
    ['missing verification hash', { verification_hash: null }, 'verification_hash'],
  ])('marks a completed row non-comparable for %s', (_label, memberOverride, expectedReason) => {
    const source = state()
    source.batch = batch({ status: 'running', completed_members: 1, safety_status: 'pending', report_hash: null })
    source.members[0] = member(0, memberOverride)
    const projection = buildGuidedExperimentMatrixProjection(source)
    expect(projection.gate.verdict).toBe('pass')
    expect(projection.rows[0].comparable).toBe(false)
    expect(projection.rows[0].non_comparable_reasons.join(' ')).toContain(expectedReason)
  })

  it.each(['queued', 'running', 'failed', 'cancelled'])(
    'never exposes comparable rows while the whole batch status is %s',
    status => {
      const projection = buildGuidedExperimentMatrixProjection(state({
        batch: batch({
          status,
          completed_members: status === 'failed' ? 6 : 0,
          failed_members: status === 'failed' ? 1 : 0,
          safety_status: status === 'failed' ? 'failed' : 'pending',
          report_hash: null,
        }),
      }))
      expect(projection.rows.every(row => !row.comparable)).toBe(true)
      expect(projection.rows[0].non_comparable_reasons.join(' ')).toContain('必须精确为 completed')
    },
  )

  it.each([11, 29, 47])(
    'fails closed when seed %s members disagree on canonical input_hash identity',
    seed => {
      const source = state()
      const negotiationIndex = MEMBER_SPECS.findIndex(([mode, memberSeed]) => (
        mode === 'negotiation' && memberSeed === seed
      ))
      source.members[negotiationIndex] = member(negotiationIndex, { input_hash: `drift-${seed}` })
      const projection = buildGuidedExperimentMatrixProjection(source)
      expect(projection.gate.verdict).toBe('block')
      expect(projection.gate.reasons.join(' ')).toContain(`seed ${seed}`)
      expect(projection.rows.every(row => !row.comparable)).toBe(true)
    },
  )

  it('fails the completed batch when safety did not pass', () => {
    const projection = buildGuidedExperimentMatrixProjection(state({
      batch: batch({ safety_status: 'failed' }),
    }))
    expect(projection.gate.verdict).toBe('block')
    expect(projection.gate.reasons.join(' ')).toContain('safety_status 必须为 passed')
    expect(projection.rows.every(row => !row.comparable)).toBe(true)
  })

  it('aggregates lineage over the hidden seventh member instead of only visible rows', () => {
    const source = state()
    source.members[6] = member(6, { verification_hash: null })
    const projection = buildGuidedExperimentMatrixProjection(source)
    expect(projection.rows.map(row => row.row_id)).not.toContain('member-6')
    expect(projection.gate.verdict).toBe('block')
    expect(projection.gate.reasons.join(' ')).toContain('固定 7 成员中有 1 个')
    expect(projection.rows.every(row => !row.comparable)).toBe(true)
  })

  it('blocks every visible row when the hidden seventh member failed', () => {
    const source = state()
    source.members[6] = member(6, {
      status: 'failed', verification_status: 'failed', run_id: null,
      completed_at: null, result_hash: null, verification_hash: null,
    })
    const projection = buildGuidedExperimentMatrixProjection(source)
    expect(projection.rows.map(row => row.row_id)).not.toContain('member-6')
    expect(projection.gate.verdict).toBe('block')
    expect(projection.rows.every(row => !row.comparable)).toBe(true)
    expect(projection.rows[0].non_comparable_reasons.join(' ')).toContain('固定 7 成员中有 1 个')
  })

  it('reuses the complete Phase 4B approved Draft and verified Pack binding', () => {
    const source = state({
      phase4BGateReasons: ['Evidence cutoff 校验未通过。'],
      approvedPackVerification: verification({
        pack: { pack_id: 'pack-1', project_id: 'foreign-project', manifest_hash: PACK_HASH },
      }),
    })
    const projection = buildGuidedExperimentMatrixProjection(source)
    expect(projection.gate.verdict).toBe('block')
    expect(projection.gate.reasons.join(' ')).toContain('Evidence cutoff')
    expect(projection.gate.reasons.join(' ')).toContain('project_id 与当前项目不一致')
  })

  it('requires all stored batch and member lineage before a row is comparable', () => {
    const source = state({ batch: batch({ gate_manifest_hash: null }) })
    source.members[0] = member(0, { baseline_result_hash: null, artifact_refs: [] })
    const projection = buildGuidedExperimentMatrixProjection(source)
    expect(projection.gate.verdict).toBe('block')
    expect(projection.gate.reasons.join(' ')).toContain('gate_manifest_hash')
    expect(projection.rows[0].non_comparable_reasons.join(' ')).toContain('baseline_result_hash')
    expect(projection.rows[0].non_comparable_reasons.join(' ')).toContain('artifact_refs')
  })
})
