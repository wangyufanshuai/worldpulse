import { describe, expect, it } from 'vitest'

import { canMutateEvidence, evidenceCoverage, evidenceSearchParams, evidenceVerdict } from '../src/composables/evidenceProjection'

describe('Evidence Registry projections', () => {
  it.each([
    [{ integrity_status: 'verified', cutoff_safe: true }, 'INTEGRITY VERIFIED'],
    [{ integrity_status: 'failed', cutoff_safe: true }, 'FAIL CLOSED'],
    [{ integrity_status: 'empty', cutoff_safe: true }, 'NOT INDEXED'],
    [{ integrity_status: 'verified', cutoff_safe: false }, 'CUTOFF VIOLATION'],
  ])('projects fail-closed integrity states', (summary, label) => {
    expect(evidenceVerdict(summary).label).toBe(label)
  })

  it('derives claim coverage without trusting a display-only field', () => {
    expect(evidenceCoverage({ claim_count: 8, linked_claim_count: 6 })).toBe(.75)
    expect(evidenceCoverage({ claim_count: 0, linked_claim_count: 0 })).toBe(0)
  })

  it('builds an explicit cutoff-safe search contract', () => {
    expect(evidenceSearchParams('project-1', ' energy ', '2026-06-30')).toEqual({
      query: 'energy', project_id: 'project-1', cutoff_at: '2026-06-30', limit: 100,
    })
  })

  it('keeps evidence mutation least-privilege', () => {
    expect(canMutateEvidence('admin')).toBe(true)
    expect(canMutateEvidence('analyst')).toBe(true)
    expect(canMutateEvidence('reviewer')).toBe(false)
    expect(canMutateEvidence('viewer')).toBe(false)
  })
})
