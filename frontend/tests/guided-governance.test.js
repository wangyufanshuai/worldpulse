import { describe, expect, it } from 'vitest'

import { buildGuidedGovernanceProjection, buildGuidedScenarioDiff } from '../src/composables/guidedGovernanceProjection'

function draft(status = 'draft', overrides = {}) {
  return {
    draft_id: `draft-${status}`,
    organization_id: 'org_default',
    project_id: 'project-governance',
    parent_draft_id: null,
    version: 1,
    status,
    name: '能源冲击场景',
    scenario: { duration_days: 14, intensity: 0.6, propagation: 0.4 },
    manual_assumptions: { reason: 'fixture' },
    compiler_version: 'scenario-compiler.v1',
    evidence_pack_id: status === 'approved' ? 'pack-1' : null,
    evidence_pack_hash: status === 'approved' ? 'p'.repeat(64) : null,
    draft_hash: status === 'approved' ? 'd'.repeat(64) : '',
    created_by_user_id: 'analyst',
    candidate_ids: ['candidate-1'],
    reviews: [],
    created_at: '2026-08-09T00:00:00Z',
    ...overrides,
  }
}

function state(overrides = {}) {
  return {
    organization: { organization_id: 'org_default', member_role: 'owner' },
    evidenceSummary: {
      project_id: 'project-governance', source_count: 1, snapshot_count: 1, claim_count: 1,
      linked_claim_count: 1, pack_count: 1, coverage: 1, integrity_status: 'verified', cutoff_safe: true,
      sources: [], recent_snapshots: [], recent_claims: [], generated_at: '2026-08-09T00:00:00Z',
    },
    searchResult: { query: '', cutoff_at: null, total: 0, snapshots: [], claims: [] },
    candidates: [{ candidate_id: 'candidate-1', validation_status: 'valid', latest_decision: { decision: 'accepted' } }],
    drafts: [], activeDraft: null, approvedDraft: null, parentDraft: null,
    activePackVerification: null, approvedPackVerification: null,
    loading: false, mutationBusy: false, error: '', actionError: '',
    canWrite: true, canReview: true, ...overrides,
  }
}

describe('Guided governance projection', () => {
  it.each([
    ['draft', 'draft'],
    ['submitted', 'review'],
    ['approved', 'frozen'],
  ])('maps %s to the governed state %s', (status, expected) => {
    const result = buildGuidedGovernanceProjection(state({ drafts: [draft(status)] }))
    expect(result.scenario.state).toBe(expected)
    expect(result.banner.title).toContain(status === 'approved' ? '已批准并冻结' : status === 'submitted' ? '审阅中' : '草稿上下文')
  })

  it('keeps a candidate-only workspace explicit and blocks scenario approval', () => {
    const result = buildGuidedGovernanceProjection(state({ drafts: [], candidates: state().candidates }))
    expect(result.scenario.state).toBe('candidate')
    expect(result.scenario.approvedDraft).toBeNull()
    expect(result.scenario.gate_reasons[0]).toContain('尚无受治理 Scenario Draft')
  })

  it('fails closed on evidence integrity and permission gaps', () => {
    const result = buildGuidedGovernanceProjection(state({
      evidenceSummary: { ...state().evidenceSummary, integrity_status: 'failed' },
      canWrite: false,
      canReview: false,
    }))
    expect(result.evidence.gate_reasons).toContain('Evidence 完整性校验失败。')
    expect(result.permissions.write.allowed).toBe(false)
    expect(result.permissions.review.allowed).toBe(false)
    expect(result.permissions.write.reason).toContain('无写入权限')
  })

  it('intersects global and organization permissions and defaults denied before organization loads', () => {
    const unloaded = buildGuidedGovernanceProjection(state({ organization: null, canWrite: true, canReview: true }))
    expect(unloaded.permissions.write.allowed).toBe(false)
    expect(unloaded.permissions.review.allowed).toBe(false)
    expect(unloaded.permissions.write.reason).toContain('默认拒绝')

    const orgViewer = buildGuidedGovernanceProjection(state({
      organization: { organization_id: 'org_default', member_role: 'viewer' },
      canWrite: true,
      canReview: true,
    }))
    expect(orgViewer.permissions.write.allowed).toBe(false)
    expect(orgViewer.permissions.review.allowed).toBe(false)

    const globalViewer = buildGuidedGovernanceProjection(state({
      organization: { organization_id: 'org_default', member_role: 'owner' },
      canWrite: false,
      canReview: false,
    }))
    expect(globalViewer.permissions.write.allowed).toBe(false)
    expect(globalViewer.permissions.review.allowed).toBe(false)

    const analyst = buildGuidedGovernanceProjection(state({
      organization: { organization_id: 'org_default', member_role: 'analyst' },
    }))
    expect(analyst.permissions.write.allowed).toBe(true)
    expect(analyst.permissions.review.allowed).toBe(false)
  })

  it('blocks an approved scenario when verified pack lineage mismatches or the backend returns 409', () => {
    const approved = draft('approved')
    const mismatch = buildGuidedGovernanceProjection(state({
      drafts: [approved],
      activeDraft: approved,
      approvedDraft: approved,
      activePackVerification: {
        draft_id: approved.draft_id,
        pack_id: approved.evidence_pack_id,
        expected_manifest_hash: approved.evidence_pack_hash,
        status: 'mismatch',
        reason: 'Evidence Pack manifest_hash 与 Scenario Draft evidence_pack_hash 不一致。',
        pack: null,
      },
    }))
    expect(mismatch.scenario.gate_reasons.join(' ')).toContain('manifest_hash')

    const conflict = buildGuidedGovernanceProjection(state({
      drafts: [approved],
      activeDraft: approved,
      approvedDraft: approved,
      activePackVerification: {
        draft_id: approved.draft_id,
        pack_id: approved.evidence_pack_id,
        expected_manifest_hash: approved.evidence_pack_hash,
        status: 'unavailable',
        reason: 'Evidence Pack 后端完整性校验失败（409）。',
        pack: null,
      },
    }))
    expect(conflict.scenario.gate_reasons.join(' ')).toContain('409')
  })

  it('shows stored parent/current fields only when parent lineage is available', () => {
    const parent = draft('approved', { draft_id: 'draft-parent', version: 1 })
    const current = draft('draft', {
      draft_id: 'draft-current', parent_draft_id: 'draft-parent', version: 2,
      scenario: { duration_days: 21, intensity: 0.6, propagation: 0.4 },
    })
    const diff = buildGuidedScenarioDiff(current, parent)
    expect(diff.available).toBe(true)
    expect(diff.changed_fields).toEqual([
      'scenario.duration_days',
      'draft_hash',
      'evidence_pack_id',
      'evidence_pack_hash',
    ])
    expect(diff.original.draft_hash).toBe(parent.draft_hash)
    expect(diff.current.evidence_pack_hash).toBe('')
    expect(buildGuidedScenarioDiff(current, null).unavailable_reason).toContain('父修订 detail 不可用')
  })

  it('keeps root approved detail and hashes available without a parent diff', () => {
    const approved = draft('approved', { draft_id: 'draft-root', parent_draft_id: null })
    const verification = {
      draft_id: approved.draft_id,
      pack_id: approved.evidence_pack_id,
      expected_manifest_hash: approved.evidence_pack_hash,
      status: 'verified',
      reason: 'verified',
      pack: { pack_id: approved.evidence_pack_id, project_id: approved.project_id, manifest_hash: approved.evidence_pack_hash },
    }
    const result = buildGuidedGovernanceProjection(state({
      drafts: [approved], activeDraft: approved, approvedDraft: approved,
      activePackVerification: verification, approvedPackVerification: verification,
    }))
    expect(result.scenario.activeDraft.draft_hash).toBe(approved.draft_hash)
    expect(result.scenario.activePackVerification.status).toBe('verified')
    expect(result.scenario.diff.available).toBe(false)
    expect(result.scenario.diff.unavailable_reason).toContain('根修订')
    expect(result.scenario.gate_reasons).toEqual([])
  })
})
