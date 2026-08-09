import { readFileSync } from 'node:fs'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const sharedApi = vi.hoisted(() => ({
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

// The governance client is an application-facing contract, not a second HTTP
// transport. Organization and CSRF headers remain owned by api.js's shared
// Axios interceptor.
vi.mock('../src/api', () => sharedApi)

import { researchGovernanceClient } from '../src/api/researchGovernanceClient'

describe('Research Governance client transport boundary', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    Object.values(sharedApi).forEach((fn) => fn.mockResolvedValue({ transport: 'shared-api' }))
  })

  it('exposes each shared api.js operation directly with its canonical signature', async () => {
    expect(researchGovernanceClient.getCurrentOrganization).toBe(sharedApi.getCurrentOrganization)
    expect(researchGovernanceClient.getProjectEvidenceSummary).toBe(sharedApi.getProjectEvidenceSummary)
    expect(researchGovernanceClient.getEvidencePack).toBe(sharedApi.getEvidencePack)
    expect(researchGovernanceClient.syncProjectEvidence).toBe(sharedApi.syncProjectEvidence)
    expect(researchGovernanceClient.searchEvidence).toBe(sharedApi.searchEvidence)
    expect(researchGovernanceClient.listScenarioCandidates).toBe(sharedApi.listScenarioCandidates)
    expect(researchGovernanceClient.listScenarioDrafts).toBe(sharedApi.listScenarioDrafts)
    expect(researchGovernanceClient.getScenarioDraft).toBe(sharedApi.getScenarioDraft)
    expect(researchGovernanceClient.submitScenarioDraft).toBe(sharedApi.submitScenarioDraft)
    expect(researchGovernanceClient.reviewScenarioDraft).toBe(sharedApi.reviewScenarioDraft)
    expect(researchGovernanceClient.cloneScenarioDraft).toBe(sharedApi.cloneScenarioDraft)

    await expect(researchGovernanceClient.getCurrentOrganization()).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.getProjectEvidenceSummary('project-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.getEvidencePack('pack-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.syncProjectEvidence('project-1', 'run-2')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.searchEvidence({ project_id: 'project-1', query: 'supply' })).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.listScenarioCandidates('org-1', 'project-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.listScenarioDrafts('org-1', 'project-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.getScenarioDraft('org-1', 'project-1', 'draft-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.submitScenarioDraft('org-1', 'project-1', 'draft-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.reviewScenarioDraft('org-1', 'project-1', 'draft-1', { decision: 'approve', comment: 'ok' })).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchGovernanceClient.cloneScenarioDraft('org-1', 'project-1', 'draft-1')).resolves.toEqual({ transport: 'shared-api' })

    expect(sharedApi.getCurrentOrganization).toHaveBeenCalledWith()
    expect(sharedApi.getProjectEvidenceSummary).toHaveBeenCalledWith('project-1')
    expect(sharedApi.getEvidencePack).toHaveBeenCalledWith('pack-1')
    expect(sharedApi.syncProjectEvidence).toHaveBeenCalledWith('project-1', 'run-2')
    expect(sharedApi.searchEvidence).toHaveBeenCalledWith({ project_id: 'project-1', query: 'supply' })
    expect(sharedApi.listScenarioCandidates).toHaveBeenCalledWith('org-1', 'project-1')
    expect(sharedApi.listScenarioDrafts).toHaveBeenCalledWith('org-1', 'project-1')
    expect(sharedApi.getScenarioDraft).toHaveBeenCalledWith('org-1', 'project-1', 'draft-1')
    expect(sharedApi.submitScenarioDraft).toHaveBeenCalledWith('org-1', 'project-1', 'draft-1')
    expect(sharedApi.reviewScenarioDraft).toHaveBeenCalledWith('org-1', 'project-1', 'draft-1', { decision: 'approve', comment: 'ok' })
    expect(sharedApi.cloneScenarioDraft).toHaveBeenCalledWith('org-1', 'project-1', 'draft-1')
  })

  it('does not declare a second Axios transport', () => {
    const source = readFileSync(new URL('../src/api/researchGovernanceClient.ts', import.meta.url), 'utf8')
    expect(source).not.toMatch(/(?:from|require\s*\()\s*['"]axios['"]|\baxios\.create\b/)
  })
})
