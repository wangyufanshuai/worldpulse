import { beforeEach, describe, expect, it, vi } from 'vitest'

const transport = vi.hoisted(() => ({
  create: vi.fn(),
  get: vi.fn(),
  post: vi.fn(),
  useRequestInterceptor: vi.fn(),
}))

vi.mock('axios', () => {
  transport.create.mockReturnValue({
    get: transport.get,
    post: transport.post,
    interceptors: { request: { use: transport.useRequestInterceptor } },
  })
  return { default: { create: transport.create } }
})

import { researchWorkspaceClient } from '../src/api/researchWorkspaceClient'

describe('Research Workspace client transport boundary', () => {
  beforeEach(() => {
    transport.get.mockReset()
    transport.post.mockReset()
    transport.get.mockResolvedValue({ data: { transport: 'shared-api' } })
    transport.post.mockResolvedValue({ data: { transport: 'shared-api' } })
  })

  it('delegates every workspace operation to the shared api.js transport and canonical URLs', async () => {
    await expect(researchWorkspaceClient.getProject('project-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchWorkspaceClient.getProjectRun('project-1', 'run-2')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchWorkspaceClient.listProjectRuns('project-1')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchWorkspaceClient.compareProjectRuns('project-1', 'run-1', 'run-2')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchWorkspaceClient.runProject('project-1', 'full')).resolves.toEqual({ transport: 'shared-api' })
    await expect(researchWorkspaceClient.chatWithProject('project-1', 'Where is the evidence?')).resolves.toEqual({ transport: 'shared-api' })

    expect(transport.get.mock.calls).toEqual([
      ['/projects/project-1'],
      ['/projects/project-1/runs/run-2'],
      ['/projects/project-1/runs'],
      ['/projects/project-1/runs/compare', {
        params: { base_run_id: 'run-1', target_run_id: 'run-2' },
      }],
    ])
    expect(transport.post.mock.calls).toEqual([
      ['/projects/project-1/run', null, { params: { mode: 'full' } }],
      ['/projects/project-1/chat', { message: 'Where is the evidence?' }],
    ])
    expect(transport.create).toHaveBeenCalledWith(expect.objectContaining({ baseURL: '/api' }))
    expect(transport.useRequestInterceptor).toHaveBeenCalledOnce()
  })
})
