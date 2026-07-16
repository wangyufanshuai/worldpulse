import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 120000,
  withCredentials: true
})

const ORGANIZATION_STORAGE_KEY = 'worldpulse_organization'

export function getActiveOrganization() {
  if (typeof window === 'undefined') return ''
  return window.localStorage.getItem(ORGANIZATION_STORAGE_KEY) || ''
}

export function setActiveOrganization(organizationId) {
  if (typeof window === 'undefined') return
  if (organizationId) window.localStorage.setItem(ORGANIZATION_STORAGE_KEY, organizationId)
  else window.localStorage.removeItem(ORGANIZATION_STORAGE_KEY)
}

api.interceptors.request.use((config) => {
  config.headers ||= {}
  const organizationId = getActiveOrganization()
  if (organizationId && !config.skipOrganization) config.headers['X-WorldPulse-Org'] = organizationId
  const method = String(config.method || 'get').toLowerCase()
  if (['post', 'put', 'patch', 'delete'].includes(method)) {
    const token = document.cookie.split('; ').find(item => item.startsWith('worldpulse_csrf='))?.split('=').slice(1).join('=')
    if (token) config.headers['X-CSRF-Token'] = decodeURIComponent(token)
  }
  return config
})

export async function login(username, password) {
  const { data } = await api.post('/v3/auth/login', { username, password })
  return data
}

export async function logout() {
  const { data } = await api.post('/v3/auth/logout')
  return data
}

export async function getCurrentUser() {
  const { data } = await api.get('/v3/auth/me')
  return data
}

export async function getTrustSummary(projectId) {
  const { data } = await api.get(`/v3/projects/${projectId}/trust-summary`)
  return data
}

export async function getProjectEvidenceSummary(projectId) {
  const { data } = await api.get(`/v4/projects/${projectId}/evidence-summary`)
  return data
}

export async function syncProjectEvidence(projectId, runId = null) {
  const { data } = await api.post(`/v4/projects/${projectId}/evidence/sync`, null, { params: runId ? { run_id: runId } : {} })
  return data
}

export async function searchEvidence(params = {}) {
  const { data } = await api.get('/v4/evidence/search', { params })
  return data
}

export async function createEvidencePack(payload) {
  const { data } = await api.post('/v4/evidence/packs', payload)
  return data
}

export async function syncCalibrationEvidence() {
  const { data } = await api.post('/v4/evidence/calibration/sync')
  return data
}

export async function listOrganizations() {
  const { data } = await api.get('/v5/organizations', { skipOrganization: true })
  return data
}

export async function getCurrentOrganization() {
  const { data } = await api.get('/v5/organizations/current')
  return data
}

export async function listOrganizationMembers(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/members`)
  return data
}

export async function listOrganizationProjects(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/projects`)
  return data
}

export async function getIngestionSummary(organizationId) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/ingestion/summary`)
  return data
}

export async function createDataConnector(organizationId, payload) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/connectors`, payload)
  return data
}

export async function createIngestionJob(organizationId, payload) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs`, payload)
  return data
}

export async function executeIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/execute`)
  return data
}

export async function cancelIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/cancel`)
  return data
}

export async function retryIngestionJob(organizationId, jobId) {
  const { data } = await api.post(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/retry`)
  return data
}

export async function getIngestionEvents(organizationId, jobId, afterSeq = 0) {
  const { data } = await api.get(`/v5/organizations/${organizationId}/ingestion/jobs/${jobId}/events`, { params: { after_seq: afterSeq } })
  return data
}

export async function listReviews(status = null) {
  const { data } = await api.get('/v3/reviews', { params: status ? { status } : {} })
  return data
}

export async function decideReview(reviewId, decision, comment = '') {
  const { data } = await api.post(`/v3/reviews/${reviewId}/decision`, { decision, comment })
  return data
}

export async function listRulePacks() {
  const { data } = await api.get('/v3/rule-packs')
  return data
}

export async function listCalibrationCases() {
  const { data } = await api.get('/v3/calibration/cases')
  return data
}

export async function createCalibrationRun(rulePackId, caseIds = []) {
  const { data } = await api.post('/v3/calibration/runs', { rule_pack_id: rulePackId, case_ids: caseIds })
  return data
}

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
  const organizationId = getActiveOrganization()
  const organizationQuery = organizationId ? `&organization_id=${encodeURIComponent(organizationId)}` : ''
  return `/api/v2/runs/${runId}/events/stream?after_seq=${encodeURIComponent(afterSeq)}${organizationQuery}`
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
