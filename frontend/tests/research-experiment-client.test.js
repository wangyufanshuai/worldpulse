import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sharedApi = vi.hoisted(() => ({
  listEvaluationBatches: vi.fn(),
  getEvaluation: vi.fn(),
  getEvaluationMembers: vi.fn(),
  getEvaluationMetrics: vi.fn(),
}))

vi.mock('../src/api', () => sharedApi)

import { researchExperimentClient } from '../src/api/researchExperimentClient'

describe('Research Experiment client transport boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.values(sharedApi).forEach(fn => fn.mockResolvedValue({ transport: 'shared-api' }))
  })

  it('delegates exact V10 read signatures through shared api.js', async () => {
    expect(researchExperimentClient.listEvaluationBatches).toBe(sharedApi.listEvaluationBatches)
    expect(researchExperimentClient.getEvaluation).toBe(sharedApi.getEvaluation)
    expect(researchExperimentClient.getEvaluationMembers).toBe(sharedApi.getEvaluationMembers)
    expect(researchExperimentClient.getEvaluationMetrics).toBe(sharedApi.getEvaluationMetrics)

    await researchExperimentClient.listEvaluationBatches('org-1')
    await researchExperimentClient.getEvaluation('batch-1')
    await researchExperimentClient.getEvaluationMembers('batch-1')
    await researchExperimentClient.getEvaluationMetrics('batch-1')

    expect(sharedApi.listEvaluationBatches).toHaveBeenCalledWith('org-1')
    expect(sharedApi.getEvaluation).toHaveBeenCalledWith('batch-1')
    expect(sharedApi.getEvaluationMembers).toHaveBeenCalledWith('batch-1')
    expect(sharedApi.getEvaluationMetrics).toHaveBeenCalledWith('batch-1')
  })

  it('does not create a second Axios transport or mutation route', () => {
    const source = readFileSync(new URL('../src/api/researchExperimentClient.ts', import.meta.url), 'utf8')
    expect(source).not.toMatch(/(?:from|require\s*\()\s*['"]axios['"]|\baxios\.create\b/)
    expect(source).not.toMatch(/\bcreate|\bpost\b|\bput\b|\bpatch\b|\bdelete\b/i)
  })
})
