import { effectScope, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({
  listEvaluationBatches: vi.fn(),
  getEvaluation: vi.fn(),
  getEvaluationMembers: vi.fn(),
  getEvaluationMetrics: vi.fn(),
}))

vi.mock('../src/api/researchExperimentClient', () => ({ researchExperimentClient: client }))

import { useGuidedExperimentMatrix } from '../src/composables/useGuidedExperimentMatrix'

const draftHash = 'd'.repeat(64)
const packHash = 'p'.repeat(64)

function batch(overrides = {}) {
  return {
    batch_id: 'eval-1', organization_id: 'org-1', project_id: 'project-1',
    scenario_draft_id: 'draft-1', scenario_draft_hash: draftHash, evidence_pack_hash: packHash,
    suite_id: 'project-experiment.v1', suite_hash: 's'.repeat(64), rule_pack_id: 'rules-1',
    rule_pack_hash: 'r'.repeat(64), runtime_profile: {}, runtime_profile_hash: 'runtime',
    provider_mode: 'mock', source_type: 'project', status: 'completed', total_members: 7,
    completed_members: 7, failed_members: 0, safety_status: 'passed', quality_status: 'observed',
    metrics: {}, report_hash: 'report-hash', gate_manifest_hash: 'gate-hash', root_batch_id: 'eval-1',
    created_at: '2026-08-10', updated_at: '2026-08-10', evaluation_track: 'project_experiment',
    ...overrides,
  }
}

function members(overrides = {}) {
  const specs = [
    ['deterministic', 1], ['hybrid', 11], ['hybrid', 29], ['hybrid', 47],
    ['negotiation', 11], ['negotiation', 29], ['negotiation', 47],
  ]
  return specs.map(([engineMode, seed], index) => ({
    member_id: `member-${index}`, batch_id: 'eval-1', case_id: 'case-1',
    engine_mode: engineMode, seed, run_id: null, status: 'pending', metrics: {}, artifact_refs: [],
    created_at: '2026-08-10', updated_at: '2026-08-10',
    input_hash: seed === 1 ? 'input-deterministic' : `input-seed-${seed}`,
    verification_status: 'pending', ...overrides,
  }))
}

function sources() {
  return {
    projectId: ref('project-1'),
    organization: ref({ organization_id: 'org-1', member_role: 'viewer' }),
    approvedDraft: ref({
      draft_id: 'draft-1', project_id: 'project-1', organization_id: 'org-1', status: 'approved',
      draft_hash: draftHash, evidence_pack_id: 'pack-1', evidence_pack_hash: packHash,
    }),
    verification: ref({
      draft_id: 'draft-1', pack_id: 'pack-1', expected_manifest_hash: packHash,
      status: 'verified', reason: 'verified',
      pack: { pack_id: 'pack-1', project_id: 'project-1', manifest_hash: packHash },
    }),
    phase4BGates: ref([]),
  }
}

function matrixFor(source) {
  return useGuidedExperimentMatrix(
    source.projectId, source.organization, source.approvedDraft, source.verification, source.phase4BGates,
  )
}

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

describe('Guided experiment matrix loader', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    client.listEvaluationBatches.mockResolvedValue([batch()])
    client.getEvaluation.mockResolvedValue(batch())
    client.getEvaluationMembers.mockResolvedValue(members())
    client.getEvaluationMetrics.mockResolvedValue([])
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('loads only the exact organization/project/Draft/Pack V10 read contracts', async () => {
    const source = sources()
    const matrix = matrixFor(source)
    await matrix.load()
    expect(client.listEvaluationBatches).toHaveBeenCalledWith('org-1')
    expect(client.getEvaluation).toHaveBeenCalledWith('eval-1')
    expect(client.getEvaluationMembers).toHaveBeenCalledWith('eval-1')
    expect(client.getEvaluationMetrics).toHaveBeenCalledWith('eval-1')
    expect(matrix.projection.value.rows).toHaveLength(6)
    expect(matrix.projection.value.hidden_row_count).toBe(1)
  })

  it('deduplicates watcher, concurrent, and repeated loads for the same complete context', async () => {
    const listed = deferred()
    client.listEvaluationBatches.mockReturnValueOnce(listed.promise)
    const source = sources()
    const approvedDraft = source.approvedDraft.value
    source.approvedDraft.value = null
    const matrix = matrixFor(source)

    source.approvedDraft.value = approvedDraft
    const explicitLoad = matrix.load()
    const concurrentLoad = matrix.load()
    await vi.waitFor(() => expect(client.listEvaluationBatches).toHaveBeenCalledOnce())
    listed.resolve([batch()])
    await Promise.all([explicitLoad, concurrentLoad])
    await matrix.load()

    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(1)
    expect(client.getEvaluation).toHaveBeenCalledTimes(1)
    expect(client.getEvaluationMembers).toHaveBeenCalledTimes(1)
    expect(client.getEvaluationMetrics).toHaveBeenCalledTimes(1)
    expect(matrix.projection.value.matrix_id).toBe('eval-1')
  })

  it('fails closed when load is called after dispose and performs no V10 reads', async () => {
    vi.useFakeTimers()
    const matrix = matrixFor(sources())

    matrix.dispose()
    await matrix.load()
    await vi.advanceTimersByTimeAsync(4_000)

    expect(client.listEvaluationBatches).not.toHaveBeenCalled()
    expect(client.getEvaluation).not.toHaveBeenCalled()
    expect(client.getEvaluationMembers).not.toHaveBeenCalled()
    expect(client.getEvaluationMetrics).not.toHaveBeenCalled()
    expect(matrix.batch.value).toBeNull()
    expect(matrix.members.value).toEqual([])
    expect(matrix.metrics.value).toEqual([])
    expect(matrix.loading.value).toBe(false)
    expect(matrix.projection.value.rows).toEqual([])
  })

  it('does not commit an asynchronous continuation after dispose', async () => {
    vi.useFakeTimers()
    const listed = deferred()
    client.listEvaluationBatches.mockReturnValueOnce(listed.promise)
    const matrix = matrixFor(sources())
    const pendingLoad = matrix.load()
    await vi.waitFor(() => expect(client.listEvaluationBatches).toHaveBeenCalledOnce())

    matrix.dispose()
    listed.resolve([batch()])
    await pendingLoad
    await vi.advanceTimersByTimeAsync(4_000)

    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(1)
    expect(client.getEvaluation).not.toHaveBeenCalled()
    expect(matrix.batch.value).toBeNull()
    expect(matrix.members.value).toEqual([])
    expect(matrix.metrics.value).toEqual([])
    expect(matrix.loading.value).toBe(false)
  })

  it('does not fall back to a batch for another Scenario Draft', async () => {
    client.listEvaluationBatches.mockResolvedValue([batch({
      batch_id: 'eval-other', scenario_draft_id: 'draft-other', scenario_draft_hash: 'x'.repeat(64),
    })])
    const matrix = matrixFor(sources())
    await matrix.load()
    expect(client.getEvaluation).not.toHaveBeenCalled()
    expect(matrix.projection.value.rows).toEqual([])
    expect(matrix.projection.value.gate.verdict).toBe('block')
  })

  it('clears and resets loading for empty or incomplete Phase 4B context', async () => {
    const source = sources()
    const matrix = matrixFor(source)
    matrix.loading.value = true
    source.approvedDraft.value = null
    await matrix.load()
    expect(matrix.loading.value).toBe(false)
    expect(matrix.projection.value.rows).toEqual([])
    expect(client.listEvaluationBatches).not.toHaveBeenCalled()

    source.phase4BGates.value = ['Evidence cutoff 校验未通过。']
    source.approvedDraft.value = sources().approvedDraft.value
    matrix.loading.value = true
    await matrix.load()
    expect(matrix.loading.value).toBe(false)
    expect(client.listEvaluationBatches).not.toHaveBeenCalled()
  })

  it('prevents an older request from restoring rows after context becomes empty', async () => {
    const listed = deferred()
    client.listEvaluationBatches.mockReturnValueOnce(listed.promise)
    const source = sources()
    const matrix = matrixFor(source)
    const first = matrix.load()
    await vi.waitFor(() => expect(client.listEvaluationBatches).toHaveBeenCalledOnce())
    source.organization.value = null
    await matrix.load()
    expect(matrix.loading.value).toBe(false)
    listed.resolve([batch()])
    await first
    expect(matrix.projection.value.rows).toEqual([])
    expect(client.getEvaluation).not.toHaveBeenCalled()
  })

  it('invalidates immediately and does not read under an incoherent organization context', async () => {
    const listed = deferred()
    client.listEvaluationBatches.mockReturnValueOnce(listed.promise)
    const source = sources()
    const matrix = matrixFor(source)
    const loading = matrix.load()
    await vi.waitFor(() => expect(client.listEvaluationBatches).toHaveBeenCalledOnce())
    source.organization.value = { organization_id: 'org-2', member_role: 'viewer' }
    expect(matrix.projection.value.rows).toEqual([])
    listed.resolve([batch()])
    await loading
    expect(matrix.loading.value).toBe(false)
    expect(matrix.projection.value.rows).toEqual([])
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(1)
    expect(client.listEvaluationBatches).not.toHaveBeenCalledWith('org-2')
    expect(matrix.error.value).toBe('')
  })

  it('invalidates immediately and reloads when Draft/hash/Pack context changes between awaits', async () => {
    const memberResponse = deferred()
    client.getEvaluationMembers.mockReturnValueOnce(memberResponse.promise)
    const source = sources()
    const matrix = matrixFor(source)
    const loading = matrix.load()
    await vi.waitFor(() => expect(client.getEvaluationMembers).toHaveBeenCalledOnce())
    source.approvedDraft.value = {
      ...source.approvedDraft.value,
      draft_hash: 'z'.repeat(64),
    }
    expect(matrix.projection.value.rows).toEqual([])
    memberResponse.resolve(members())
    await loading
    expect(matrix.loading.value).toBe(false)
    expect(matrix.projection.value.rows).toEqual([])
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(2)
    expect(matrix.error.value).toBe('')
  })

  it('keeps successful rows bound to the complete context and loads a switched approved Draft exact batch', async () => {
    const source = sources()
    client.getEvaluationMetrics.mockResolvedValue([{
      metric_id: 'old-context-sentinel', batch_id: 'eval-1', member_id: 'member-0', scope: 'quality',
      metric_key: 'old-context-sentinel', value: 1, metric_hash: 'old-metric-hash', created_at: '2026-08-10',
    }])
    client.getEvaluationMembers.mockResolvedValue(members().map((item, index) => ({
      ...item, run_id: `old-run-${index}`, artifact_refs: [`old-artifact-${index}`],
    })))
    const matrix = matrixFor(source)
    await matrix.load()
    expect(matrix.projection.value.matrix_id).toBe('eval-1')
    expect(matrix.projection.value.rows.every(row => row.run_id.startsWith('old-run-'))).toBe(true)

    const nextDraftHash = 'n'.repeat(64)
    const nextPackHash = 'k'.repeat(64)
    const nextBatch = batch({
      batch_id: 'eval-2', scenario_draft_id: 'draft-2', scenario_draft_hash: nextDraftHash,
      evidence_pack_hash: nextPackHash, root_batch_id: 'eval-2',
    })
    client.listEvaluationBatches.mockResolvedValue([batch(), nextBatch])
    client.getEvaluation.mockResolvedValue(nextBatch)
    client.getEvaluationMembers.mockResolvedValue(members().map(item => ({
      ...item, member_id: item.member_id.replace('member-', 'next-member-'), batch_id: 'eval-2',
      run_id: item.member_id.replace('member-', 'next-run-'),
    })))
    client.getEvaluationMetrics.mockResolvedValue([])

    source.approvedDraft.value = {
      ...source.approvedDraft.value,
      draft_id: 'draft-2', draft_hash: nextDraftHash,
      evidence_pack_id: 'pack-2', evidence_pack_hash: nextPackHash,
    }
    expect(matrix.projection.value.rows).toEqual([])
    expect(matrix.projection.value.matrix_id).toBe('')
    expect(JSON.stringify(matrix.projection.value)).not.toContain('old-run-')
    expect(JSON.stringify(matrix.projection.value)).not.toContain('old-artifact-')
    expect(JSON.stringify(matrix.projection.value)).not.toContain('old-context-sentinel')
    source.verification.value = {
      draft_id: 'draft-2', pack_id: 'pack-2', expected_manifest_hash: nextPackHash,
      status: 'verified', reason: 'verified',
      pack: { pack_id: 'pack-2', project_id: 'project-1', manifest_hash: nextPackHash },
    }

    await vi.waitFor(() => expect(matrix.projection.value.matrix_id).toBe('eval-2'))
    expect(client.getEvaluation).toHaveBeenLastCalledWith('eval-2')
    expect(matrix.projection.value.rows.every(row => row.run_id.startsWith('next-run-'))).toBe(true)
  })

  it('polls queued/running batches with one timer and stops on terminal status', async () => {
    vi.useFakeTimers()
    const queued = batch({
      status: 'queued', completed_members: 0, safety_status: 'pending', report_hash: null,
    })
    const completed = batch()
    client.listEvaluationBatches.mockResolvedValue([queued])
    client.getEvaluation
      .mockResolvedValueOnce(queued)
      .mockResolvedValueOnce(queued)
      .mockResolvedValueOnce(completed)
    const matrix = matrixFor(sources())

    await matrix.load()
    await matrix.load()
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(2_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(2)
    expect(matrix.batch.value.status).toBe('queued')
    await vi.advanceTimersByTimeAsync(2_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(3)
    expect(matrix.batch.value.status).toBe('completed')
    await vi.advanceTimersByTimeAsync(4_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(3)
    matrix.dispose()
  })

  it('stops terminal polling on request error, context invalidation, and dispose', async () => {
    vi.useFakeTimers()
    const queued = batch({
      status: 'running', completed_members: 0, safety_status: 'pending', report_hash: null,
    })
    client.listEvaluationBatches.mockResolvedValueOnce([queued]).mockRejectedValueOnce(new Error('poll failed'))
    client.getEvaluation.mockResolvedValue(queued)
    const source = sources()
    const matrix = matrixFor(source)

    await matrix.load()
    await vi.advanceTimersByTimeAsync(2_000)
    expect(matrix.error.value).toContain('poll failed')
    await vi.advanceTimersByTimeAsync(4_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(2)

    client.listEvaluationBatches.mockResolvedValue([queued])
    await matrix.load()
    source.approvedDraft.value = null
    await vi.advanceTimersByTimeAsync(4_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(3)

    source.approvedDraft.value = sources().approvedDraft.value
    source.verification.value = sources().verification.value
    await vi.waitFor(() => expect(client.listEvaluationBatches).toHaveBeenCalledTimes(4))
    matrix.dispose()
    await vi.advanceTimersByTimeAsync(4_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledTimes(4)
  })

  it('stops the single polling timer when the owning Vue scope unmounts', async () => {
    vi.useFakeTimers()
    const queued = batch({
      status: 'queued', completed_members: 0, safety_status: 'pending', report_hash: null,
    })
    client.listEvaluationBatches.mockResolvedValue([queued])
    client.getEvaluation.mockResolvedValue(queued)
    const scope = effectScope()
    const matrix = scope.run(() => matrixFor(sources()))

    await matrix.load()
    expect(client.listEvaluationBatches).toHaveBeenCalledOnce()
    scope.stop()
    await vi.advanceTimersByTimeAsync(4_000)
    expect(client.listEvaluationBatches).toHaveBeenCalledOnce()
  })

  it.each([
    ['detail batch drift', () => client.getEvaluation.mockResolvedValue(batch({ batch_id: 'eval-foreign' })), 'detail.batch_id'],
    ['detail organization drift', () => client.getEvaluation.mockResolvedValue(batch({ organization_id: 'org-foreign' })), 'organization_id'],
    ['detail Draft hash drift', () => client.getEvaluation.mockResolvedValue(batch({ scenario_draft_hash: 'x'.repeat(64) })), 'scenario_draft_hash'],
    ['detail Pack hash drift', () => client.getEvaluation.mockResolvedValue(batch({ evidence_pack_hash: 'x'.repeat(64) })), 'evidence_pack_hash'],
    ['member batch drift', () => client.getEvaluationMembers.mockResolvedValue(members({ batch_id: 'eval-foreign' })), '成员响应包含跨批次'],
    ['metric batch drift', () => client.getEvaluationMetrics.mockResolvedValue([{
      metric_id: 'metric-1', batch_id: 'eval-foreign', member_id: null, scope: 'safety',
      metric_key: 'stored', value: 1, metric_hash: 'metric-hash', created_at: '2026-08-10',
    }]), '指标响应包含跨批次'],
    ['metric member drift', () => client.getEvaluationMetrics.mockResolvedValue([{
      metric_id: 'metric-1', batch_id: 'eval-1', member_id: 'foreign-member', scope: 'safety',
      metric_key: 'stored', value: 1, metric_hash: 'metric-hash', created_at: '2026-08-10',
    }]), '之外的 member_id'],
  ])('rejects and atomically clears %s', async (_label, arrange, expectedReason) => {
    arrange()
    const matrix = matrixFor(sources())
    await expect(matrix.load()).rejects.toThrow(expectedReason)
    expect(matrix.batch.value).toBeNull()
    expect(matrix.members.value).toEqual([])
    expect(matrix.metrics.value).toEqual([])
    expect(matrix.loading.value).toBe(false)
    expect(matrix.error.value).toContain(expectedReason)
  })

  it('clears rows and fails closed when the organization-scoped read is unauthorized', async () => {
    client.listEvaluationBatches.mockRejectedValue({ response: { status: 403, data: { detail: 'Forbidden' } } })
    const matrix = matrixFor(sources())
    await expect(matrix.load()).rejects.toBeTruthy()
    expect(matrix.projection.value.rows).toEqual([])
    expect(matrix.projection.value.gate.verdict).toBe('block')
    expect(matrix.projection.value.gate.reasons.join(' ')).toContain('Forbidden')
  })
})
