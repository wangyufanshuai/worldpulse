import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000
})

export async function getRiskOverview() {
  const { data } = await api.get('/risk/overview', { timeout: 8000 })
  return data
}

export async function listProjects() {
  const { data } = await api.get('/projects')
  return data
}

export async function createProject(payload) {
  const { data } = await api.post('/projects', payload)
  return data
}

export async function getProject(projectId) {
  const { data } = await api.get(`/projects/${projectId}`)
  return data
}

export async function getProjectRun(projectId, runId) {
  const { data } = await api.get(`/projects/${projectId}/runs/${runId}`)
  return data
}

export async function compareProjectRuns(projectId, baseRunId, targetRunId) {
  const { data } = await api.get(`/projects/${projectId}/runs/compare`, {
    params: { base_run_id: baseRunId, target_run_id: targetRunId }
  })
  return data
}

export async function listProjectRuns(projectId) {
  const { data } = await api.get(`/projects/${projectId}/runs`)
  return data
}

export async function runProject(projectId, mode = 'fast') {
  const { data } = await api.post(`/projects/${projectId}/run`, null, { params: { mode } })
  return data
}

export async function getWarRoomPresets() {
  const { data } = await api.get('/war-room/presets')
  return data
}

export async function runProjectWarRoom(projectId, payload) {
  const { data } = await api.post(`/projects/${projectId}/war-room/run`, payload)
  return data
}

export async function createLifecycleRun(projectId, payload) {
  const { data } = await api.post(`/v2/projects/${projectId}/runs`, payload)
  return data
}

export async function getLifecycleRun(runId) {
  const { data } = await api.get(`/v2/runs/${runId}`)
  return data
}

export async function getLifecycleEvents(runId, afterSeq = 0) {
  const { data } = await api.get(`/v2/runs/${runId}/events`, { params: { after_seq: afterSeq } })
  return data
}

export async function getLifecycleAudit(runId) {
  const { data } = await api.get(`/v2/runs/${runId}/audit`)
  return data
}

export async function pauseLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/pause`)
  return data
}

export async function resumeLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/resume`)
  return data
}

export async function cancelLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/cancel`)
  return data
}

export async function retryLifecycleRun(runId) {
  const { data } = await api.post(`/v2/runs/${runId}/retry`)
  return data
}

export function lifecycleEventStreamUrl(runId, afterSeq = 0) {
  return `/api/v2/runs/${runId}/events/stream?after_seq=${encodeURIComponent(afterSeq)}`
}

export async function getWarRoomReplayPack(projectId, params = {}) {
  const { data } = await api.get(`/projects/${projectId}/war-room/replay-pack`, { params })
  return data
}

export async function getWarRoomWorkspace(projectId, params = {}) {
  const { data } = await api.get(`/projects/${projectId}/war-room/workspace`, { params })
  return data
}

export async function updateProjectGraph(projectId, payload) {
  const { data } = await api.patch(`/projects/${projectId}/graph`, payload)
  return data
}

export async function getProjectGraph(projectId) {
  const { data } = await api.get(`/projects/${projectId}/graph`)
  return data
}

export async function getProjectReport(projectId) {
  const { data } = await api.get(`/projects/${projectId}/report`)
  return data
}

export async function chatWithProject(projectId, message) {
  const { data } = await api.post(`/projects/${projectId}/chat`, { message })
  return data
}
