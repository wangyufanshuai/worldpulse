import { beforeEach, describe, expect, it, vi } from 'vitest'

const client = vi.hoisted(() => ({
  getCurrentOrganization: vi.fn(),
  getProjectEvidenceSummary: vi.fn(),
  getEvidencePack: vi.fn(),
  syncProjectEvidence: vi.fn(),
  searchEvidence: vi.fn(),
  listScenarioCandidates: vi.fn(),
  listScenarioDrafts: vi.fn(),
  getScenarioDraft: vi.fn(),
  submitScenarioDraft: vi.fn(),
  reviewScenarioDraft: vi.fn(),
  cloneScenarioDraft: vi.fn(),
}))

vi.mock('../src/api/researchGovernanceClient', () => ({ researchGovernanceClient: client }))

import { useGuidedResearchGovernance } from '../src/composables/useGuidedResearchGovernance'

function deferred() {
  let resolve
  let reject
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, resolve, reject }
}

function organization(memberRole = 'analyst') {
  return {
    organization_id: 'org-1', slug: 'org-1', name: 'Org 1', status: 'active',
    member_role: memberRole, created_at: '2026-08-09T00:00:00Z', updated_at: '2026-08-09T00:00:00Z',
  }
}

function summary() {
  return {
    project_id: 'project-1', source_count: 1, snapshot_count: 1, claim_count: 1,
    linked_claim_count: 1, pack_count: 1, coverage: 1, integrity_status: 'verified', cutoff_safe: true,
    sources: [], recent_snapshots: [], recent_claims: [], generated_at: '2026-08-09T00:00:00Z',
  }
}

function draft(draftId, status = 'draft', overrides = {}) {
  return {
    draft_id: draftId,
    organization_id: 'org-1',
    project_id: 'project-1',
    parent_draft_id: null,
    version: 1,
    status,
    name: `Draft ${draftId}`,
    scenario: { duration_days: 14 },
    manual_assumptions: { source: 'fixture' },
    compiler_version: 'scenario-compiler.v1',
    evidence_pack_id: status === 'approved' ? 'pack-1' : null,
    evidence_pack_hash: status === 'approved' ? 'a'.repeat(64) : null,
    draft_hash: status === 'approved' ? 'd'.repeat(64) : '',
    created_by_user_id: 'analyst-1',
    created_at: '2026-08-09T00:00:00Z',
    candidate_ids: [],
    reviews: [],
    ...overrides,
  }
}

function configureLoad(drafts) {
  client.getCurrentOrganization.mockResolvedValue(organization())
  client.getProjectEvidenceSummary.mockResolvedValue(summary())
  client.listScenarioCandidates.mockResolvedValue([])
  client.listScenarioDrafts.mockResolvedValue(drafts)
  client.getScenarioDraft.mockImplementation((_orgId, _projectId, draftId) => (
    Promise.resolve(drafts.find(item => item.draft_id === draftId))
  ))
}

describe('Guided Research governance state', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    client.searchEvidence.mockResolvedValue({ query: '', cutoff_at: null, total: 0, snapshots: [], claims: [] })
  })

  it('loads an approved pack through the verified backend read and blocks a manifest mismatch', async () => {
    const approved = draft('draft-approved', 'approved')
    configureLoad([approved])
    client.getEvidencePack.mockResolvedValue({
      pack_id: 'pack-1', project_id: 'project-1', manifest_hash: 'b'.repeat(64),
      name: 'Frozen pack', cutoff_at: '2026-08-09T00:00:00Z', manifest: {}, created_at: '2026-08-09T00:00:00Z',
    })
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })

    await governance.load()

    expect(client.getEvidencePack).toHaveBeenCalledWith('pack-1')
    expect(governance.activePackVerification.value.status).toBe('mismatch')
    expect(governance.projection.value.scenario.gate_reasons.join(' ')).toContain('manifest_hash')
  })

  it('keeps an Evidence Pack 409 as an explicit scenario-approval blocker', async () => {
    const approved = draft('draft-approved', 'approved')
    configureLoad([approved])
    client.getEvidencePack.mockRejectedValue({
      response: { status: 409, data: { detail: 'Evidence pack integrity verification failed' } },
    })
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })

    await governance.load()

    expect(governance.activePackVerification.value.status).toBe('unavailable')
    expect(governance.activePackVerification.value.reason).toContain('409')
    expect(governance.projection.value.scenario.gate_reasons.join(' ')).toContain('409')
  })

  it('keeps submitted drafts blocked when Pack verification fails and does not dispatch approval', async () => {
    const submitted = draft('draft-submitted', 'submitted', {
      evidence_pack_id: 'pack-1', evidence_pack_hash: 'a'.repeat(64), draft_hash: 'd'.repeat(64),
    })
    configureLoad([submitted])
    client.getCurrentOrganization.mockResolvedValue(organization('admin'))
    client.getEvidencePack.mockRejectedValue({
      response: { status: 409, data: { detail: 'Evidence pack integrity verification failed' } },
    })
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })

    await governance.load()

    expect(governance.projection.value.scenario.gate_reasons.join(' ')).toContain('409')
    await expect(governance.reviewDraft('draft-submitted', { decision: 'approve' }))
      .rejects.toThrow('Evidence Pack')
    expect(client.reviewScenarioDraft).not.toHaveBeenCalled()
  })

  it('serializes all mutations and prevents duplicate dispatch before the first request starts', async () => {
    const editable = draft('draft-editable')
    configureLoad([editable])
    const pendingSync = deferred()
    client.syncProjectEvidence.mockReturnValue(pendingSync.promise)
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })
    await governance.load()

    const first = governance.syncEvidence('run-1')
    const duplicate = governance.syncEvidence('run-1')

    await expect(duplicate).rejects.toThrow('治理写操作')
    expect(governance.mutationBusy.value).toBe(true)
    await Promise.resolve()
    expect(client.syncProjectEvidence).toHaveBeenCalledTimes(1)
    pendingSync.resolve({ summary: summary() })
    await first
    expect(governance.mutationBusy.value).toBe(false)
  })

  it('rejects a conflicting mutation instead of returning the first action result', async () => {
    const editable = draft('draft-editable')
    configureLoad([editable])
    const pendingSync = deferred()
    client.syncProjectEvidence.mockReturnValue(pendingSync.promise)
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })
    await governance.load()

    const sync = governance.syncEvidence('run-1')
    const submit = governance.submitDraft('draft-editable')

    await expect(submit).rejects.toThrow('治理写操作')
    expect(client.submitScenarioDraft).not.toHaveBeenCalled()
    pendingSync.resolve({ summary: summary() })
    await sync
  })

  it('does not let a stale draft response overwrite a newer selection', async () => {
    const slow = draft('draft-slow')
    const fast = draft('draft-fast')
    const slowRequest = deferred()
    client.getScenarioDraft.mockImplementation((_orgId, _projectId, draftId) => (
      draftId === 'draft-slow' ? slowRequest.promise : Promise.resolve(fast)
    ))
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })
    governance.organization.value = organization()
    governance.drafts.value = [slow, fast]

    const staleSelection = governance.selectDraft('draft-slow')
    const currentSelection = governance.selectDraft('draft-fast')
    await currentSelection
    slowRequest.resolve(slow)
    await staleSelection

    expect(governance.activeDraft.value.draft_id).toBe('draft-fast')
    expect(governance.parentDraft.value).toBeNull()
    expect(governance.activePackVerification.value.draft_id).toBe('draft-fast')
  })

  it('does not let a stale Evidence search response overwrite the latest query', async () => {
    const slowSearch = deferred()
    client.searchEvidence.mockImplementation(({ query }) => (
      query === 'old' ? slowSearch.promise : Promise.resolve({ query, cutoff_at: null, total: 1, snapshots: [], claims: [] })
    ))
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })

    const oldSearch = governance.searchEvidence('old')
    const latestSearch = governance.searchEvidence('new')
    await latestSearch
    slowSearch.resolve({ query: 'old', cutoff_at: null, total: 1, snapshots: [], claims: [] })
    await oldSearch

    expect(governance.searchResult.value.query).toBe('new')
  })

  it('does not let a stale failed Evidence search overwrite the latest action state', async () => {
    const slowSearch = deferred()
    client.searchEvidence.mockImplementation(({ query }) => (
      query === 'old' ? slowSearch.promise : Promise.resolve({ query, cutoff_at: null, total: 1, snapshots: [], claims: [] })
    ))
    const governance = useGuidedResearchGovernance('project-1', { canWrite: true, canReview: true })

    const oldSearch = governance.searchEvidence('old')
    await governance.searchEvidence('new')
    slowSearch.reject(new Error('stale failure'))
    await expect(oldSearch).rejects.toThrow('stale failure')

    expect(governance.searchResult.value.query).toBe('new')
    expect(governance.actionError.value).toBe('')
  })
})
