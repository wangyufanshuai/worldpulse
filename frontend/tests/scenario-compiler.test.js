import { describe, expect, it } from 'vitest'

import { acceptedCandidateIds, compactCompilerHash, compilerStepState, formatBytes, scenarioCompilerSummary } from '../src/composables/scenarioCompilerProjection'

describe('V1.9 scenario compiler projection', () => {
  const candidates = [
    { candidate_id: 'preset', validation_status: 'valid', latest_decision: { decision: 'accepted' } },
    { candidate_id: 'country', validation_status: 'valid', latest_decision: null },
    { candidate_id: 'invalid', validation_status: 'invalid', latest_decision: { decision: 'accepted' } },
  ]

  it('counts only pending valid candidates and approved lineage', () => {
    const approved = { draft_id: 'd1', status: 'approved', version: 2 }
    expect(scenarioCompilerSummary([{}], candidates, [{ status: 'submitted' }, approved])).toEqual({
      documentCount: 1, pendingCandidateCount: 1, pendingDraftCount: 1, latestApproved: approved,
    })
  })

  it('uses only valid accepted candidates for draft compilation', () => {
    expect(acceptedCandidateIds(candidates)).toEqual(['preset'])
  })

  it('projects the six-step gate without inventing backend status', () => {
    const state = { documents: [{}], jobs: [{ status: 'completed' }], candidates, drafts: [], lastRun: null }
    expect(compilerStepState('upload', state)).toBe('done')
    expect(compilerStepState('extract', state)).toBe('done')
    expect(compilerStepState('candidates', state)).toBe('done')
    expect(compilerStepState('draft', state)).toBe('active')
    expect(compilerStepState('review', state)).toBe('pending')
  })

  it('formats lineage hashes and quota bytes compactly', () => {
    expect(compactCompilerHash('abcdef0123456789')).toBe('abcdef012345…')
    expect(formatBytes(5 * 1024 ** 3)).toBe('5.00 GB')
  })
})
